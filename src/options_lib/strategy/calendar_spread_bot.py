"""Calendar & Diagonal Spread Strategy Bot (Term Structure & Theta Harvest).

Executes multi-tenor Time Spreads:
1. Sells near-term contract (Front-Month, 5–12 DTE) at ATM strike to harvest rapid Theta decay.
2. Buys longer-term contract (Back-Month, 25–50 DTE) at the same strike to provide Vega protection.
3. Automatically rolls front-month contract as it approaches expiration or reaches profit targets.
4. Exploits Volatility Term Structure Contango (Near IV <= Far IV).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from options_lib.paper_broker import (
    MarginCalculator,
    MatchingEngine,
    OrderType,
    PaperAccount,
    PaperOrder,
    PaperStorage,
)
from options_lib.symbol_parser import parse_bybit_option_symbol

logger = logging.getLogger(__name__)


@dataclass
class CalendarSpreadConfig:
    """Configuration for Calendar Spread Strategy Bot."""

    asset: str = "BTC"
    paper_mode: bool = True
    initial_capital: float = 10000.0

    # Tenor pairs
    min_near_dte: int = 5
    max_near_dte: int = 12
    min_far_dte: int = 25
    max_far_dte: int = 50

    # Risk & Profit parameters
    target_profit_pct: float = 0.30   # Take profit at 30% return on net debit
    max_loss_pct: float = 0.35        # Stop loss if spread value drops by 35%
    roll_near_dte: float = 1.0        # Roll near-term leg when DTE <= 1
    max_concurrent_positions: int = 3
    poll_interval_seconds: int = 300

    use_deribit_testnet: bool = False

    # Persistence
    db_path: str = "portfolio_data/paper_trading.db"
    log_dir: str = "logs/calendar-spread"
    state_file: str = "portfolio_data/calendar_spread_state.json"

    @classmethod
    def from_env(cls, **overrides) -> CalendarSpreadConfig:
        config = cls(
            asset=os.getenv("CS_ASSET", cls.asset),
            paper_mode=os.getenv("CS_PAPER_MODE", "true").lower() == "true",
            use_deribit_testnet=os.getenv("CS_USE_DERIBIT_TESTNET", "false").lower() in ("true", "1"),
            initial_capital=float(os.getenv("CS_CAPITAL", cls.initial_capital)),
            min_near_dte=int(os.getenv("CS_MIN_NEAR_DTE", cls.min_near_dte)),
            max_near_dte=int(os.getenv("CS_MAX_NEAR_DTE", cls.max_near_dte)),
            min_far_dte=int(os.getenv("CS_MIN_FAR_DTE", cls.min_far_dte)),
            max_far_dte=int(os.getenv("CS_MAX_FAR_DTE", cls.max_far_dte)),
            target_profit_pct=float(os.getenv("CS_TP_PCT", cls.target_profit_pct)),
            max_loss_pct=float(os.getenv("CS_SL_PCT", cls.max_loss_pct)),
            max_concurrent_positions=int(os.getenv("CS_MAX_CONCURRENT", cls.max_concurrent_positions)),
            db_path=os.getenv("CS_DB_PATH", cls.db_path),
            log_dir=os.getenv("CS_LOG_DIR", cls.log_dir),
            state_file=os.getenv("CS_STATE_FILE", cls.state_file),
        )
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config


@dataclass
class CalendarSpreadCandidate:
    candidate_id: str
    asset: str
    strike: float
    option_type: str  # "call" or "put"
    near_expiry: str
    far_expiry: str
    near_dte: float
    far_dte: float
    near_leg: dict[str, Any]  # Sell
    far_leg: dict[str, Any]   # Buy
    net_debit: float


class CalendarSpreadBot:
    """Calendar Spread Strategy Engine."""

    def __init__(self, config: CalendarSpreadConfig):
        self.config = config
        self._running = False

        self.storage = PaperStorage(self.config.db_path)
        self.margin_calc = MarginCalculator()
        self.matching_engine = MatchingEngine()

        from options_lib.paper_broker.deribit_adapter import DeribitBrokerAdapter
        self.deribit_adapter = (
            DeribitBrokerAdapter(testnet=True) if getattr(self.config, "use_deribit_testnet", False) else None
        )

        acct_id = f"cs_{self.config.asset.lower()}_deribit" if self.config.use_deribit_testnet else f"cs_{self.config.asset.lower()}"
        acct = self.storage.load_account(acct_id)
        if acct:
            self.paper_account = acct
        else:
            self.paper_account = PaperAccount(
                account_id=acct_id,
                initial_capital=self.config.initial_capital,
                cash_balance=self.config.initial_capital,
                currency="BTC" if self.config.use_deribit_testnet else "USDT",
            )
            self.storage.save_account(self.paper_account)

        if self.deribit_adapter:
            try:
                self.deribit_adapter.sync_account(self.paper_account, currency=self.config.asset)
            except Exception as e:
                logger.warning("Deribit sync warning for calendar spread: %s", e)

        os.makedirs(self.config.log_dir, exist_ok=True)

    def select_candidate(
        self,
        contracts: list[dict[str, Any]],
        spot: float,
        option_type: str = "call",
    ) -> CalendarSpreadCandidate | None:
        """Find optimal ATM Calendar Spread matching near and far tenors."""
        now = datetime.now(UTC)
        target_type = option_type.lower()

        near_contracts: list[dict[str, Any]] = []
        far_contracts: list[dict[str, Any]] = []

        for c in contracts:
            c_type = str(c.get("option_type") or c.get("type", "")).lower()
            if c_type in ("c", "call"):
                norm_type = "call"
            elif c_type in ("p", "put"):
                norm_type = "put"
            else:
                continue

            if norm_type != target_type:
                continue

            exp_str = c.get("expiry", "")
            if not exp_str:
                continue
            try:
                exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            except Exception:
                continue

            dte = (exp_dt - now).total_seconds() / 86400.0

            if self.config.min_near_dte <= dte <= self.config.max_near_dte:
                near_contracts.append({**c, "dte": dte, "expiry_str": exp_str})
            elif self.config.min_far_dte <= dte <= self.config.max_far_dte:
                far_contracts.append({**c, "dte": dte, "expiry_str": exp_str})

        if not near_contracts or not far_contracts:
            return None

        # Find common strikes available in both tenors
        near_strikes = set(float(c["strike"]) for c in near_contracts)
        far_strikes = set(float(c["strike"]) for c in far_contracts)
        common = near_strikes.intersection(far_strikes)

        if not common:
            return None

        # Pick ATM strike closest to spot
        atm_strike = min(common, key=lambda s: abs(s - spot))

        near_leg_cand = next(c for c in near_contracts if float(c["strike"]) == atm_strike)
        far_leg_cand = next(c for c in far_contracts if float(c["strike"]) == atm_strike)

        near_mark = float(near_leg_cand.get("mark_price", 0))
        far_mark = float(far_leg_cand.get("mark_price", 0))

        net_debit = far_mark - near_mark
        if net_debit <= 0:
            return None

        return CalendarSpreadCandidate(
            candidate_id=f"cs_{uuid.uuid4().hex[:8]}",
            asset=self.config.asset,
            strike=atm_strike,
            option_type=target_type,
            near_expiry=near_leg_cand["expiry_str"],
            far_expiry=far_leg_cand["expiry_str"],
            near_dte=near_leg_cand["dte"],
            far_dte=far_leg_cand["dte"],
            near_leg={"symbol": near_leg_cand.get("symbol", ""), "strike": atm_strike, "mark": near_mark, "side": "Sell"},
            far_leg={"symbol": far_leg_cand.get("symbol", ""), "strike": atm_strike, "mark": far_mark, "side": "Buy"},
            net_debit=net_debit,
        )

    def evaluate_position(
        self,
        entry_debit: float,
        current_spread_value: float,
        near_dte: float,
        qty: float,
    ) -> tuple[str, float]:
        """Evaluate 30% TP, 35% SL, or Near-term expiration for Calendar Spread.
        
        current_spread_value: current value to close (Sell far leg mark - Buy back near leg mark).
        """
        unrealized_pnl = (current_spread_value - entry_debit) * qty

        # 1. Near-term expiration (time to roll front month or close)
        if near_dte <= 0.05:
            return "NEAR_EXPIRY_ROLL", unrealized_pnl

        # 2. 30% Take Profit on net debit
        if current_spread_value >= entry_debit * (1.0 + self.config.target_profit_pct):
            return "TAKE_PROFIT", unrealized_pnl

        # 3. Stop loss
        if current_spread_value <= entry_debit * (1.0 - self.config.max_loss_pct):
            return "STOP_LOSS", unrealized_pnl

        return "HOLD", unrealized_pnl

    def execute_open_candidate(
        self,
        candidate: CalendarSpreadCandidate,
        qty: float,
        spot: float,
    ) -> bool:
        """Execute the two legs of a calendar spread (Buy far leg, Sell near leg)."""
        legs = [
            (candidate.far_leg["symbol"], "Buy", candidate.far_leg["mark"]),
            (candidate.near_leg["symbol"], "Sell", candidate.near_leg["mark"]),
        ]
        for sym, side, mark in legs:
            order = PaperOrder(
                symbol=sym,
                side=side,
                qty=qty,
                order_type=OrderType.MARKET,
                strategy_id=candidate.candidate_id,
            )
            if self.config.use_deribit_testnet and self.deribit_adapter:
                res = self.deribit_adapter.execute_order(order, spot=spot)
            else:
                res = self.matching_engine.match_order(
                    order=order,
                    best_bid=mark * 0.95,
                    best_ask=mark * 1.05,
                    spot=spot,
                    mark_price=mark,
                )
            if not res.is_filled:
                return False
            self.paper_account.apply_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=res.filled_price,
                fee=res.fee,
                spot=spot,
                strategy_id=candidate.candidate_id,
                order_id=res.order_id,
            )
        self.storage.save_account(self.paper_account)
        return True

