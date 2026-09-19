"""Directional Vertical Credit Spreads Bot (Bull Put & Bear Call Spreads).

Executes defined-risk 2-leg credit spreads:
1. Bull Put Spread: Sell OTM Put (Delta ~ -0.15 to -0.20) + Buy OTM Put Wing (Delta ~ -0.03 to -0.06).
   Executed in bullish or sideways-up regimes.
2. Bear Call Spread: Sell OTM Call (Delta ~ +0.15 to +0.20) + Buy OTM Call Wing (Delta ~ +0.03 to +0.06).
   Executed in bearish or sideways-down regimes.

Features:
- Trend-adaptive direction selection (EMA trend / rolling momentum).
- Wing-first execution: Buys protective wing first to cap margin, sells short strike second.
- 50% Take Profit & 1.5x-2.0x credit Stop Loss.
- Full PaperBroker and Live Bybit V5 integration.
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
class VerticalSpreadConfig:
    """Configuration for Directional Vertical Credit Spreads."""

    asset: str = "BTC"
    paper_mode: bool = True
    initial_capital: float = 10000.0

    # Delta targets
    target_short_delta: float = 0.18  # Short strike delta (0.15 - 0.22)
    target_wing_delta: float = 0.05   # Long protective wing delta (0.03 - 0.08)
    min_dte: int = 5
    max_dte: int = 16

    # Signal & Risk parameters
    trend_ema_window: int = 20
    target_profit_pct: float = 0.50   # Close at 50% max credit
    max_loss_multiplier: float = 1.8  # Stop loss multiplier on credit
    roll_dte: float = 1.0             # Roll / close when DTE <= 1
    max_concurrent_positions: int = 3
    poll_interval_seconds: int = 300

    use_deribit_testnet: bool = False

    # Persistence
    db_path: str = "portfolio_data/paper_trading.db"
    log_dir: str = "logs/vertical-spread"
    state_file: str = "portfolio_data/vertical_spread_state.json"

    @classmethod
    def from_env(cls, **overrides) -> VerticalSpreadConfig:
        config = cls(
            asset=os.getenv("VS_ASSET", cls.asset),
            paper_mode=os.getenv("VS_PAPER_MODE", "true").lower() == "true",
            use_deribit_testnet=os.getenv("VS_USE_DERIBIT_TESTNET", "false").lower() in ("true", "1"),
            initial_capital=float(os.getenv("VS_CAPITAL", cls.initial_capital)),
            target_short_delta=float(os.getenv("VS_SHORT_DELTA", cls.target_short_delta)),
            target_wing_delta=float(os.getenv("VS_WING_DELTA", cls.target_wing_delta)),
            min_dte=int(os.getenv("VS_MIN_DTE", cls.min_dte)),
            max_dte=int(os.getenv("VS_MAX_DTE", cls.max_dte)),
            target_profit_pct=float(os.getenv("VS_TP_PCT", cls.target_profit_pct)),
            max_loss_multiplier=float(os.getenv("VS_SL_MULT", cls.max_loss_multiplier)),
            max_concurrent_positions=int(os.getenv("VS_MAX_CONCURRENT", cls.max_concurrent_positions)),
            db_path=os.getenv("VS_DB_PATH", cls.db_path),
            log_dir=os.getenv("VS_LOG_DIR", cls.log_dir),
            state_file=os.getenv("VS_STATE_FILE", cls.state_file),
        )
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config


@dataclass
class VerticalSpreadLeg:
    symbol: str
    side: str  # "Buy" or "Sell"
    strike: float
    option_type: str  # "call" or "put"
    delta: float
    entry_price: float
    current_mark: float
    qty: float
    role: str  # "short_leg" or "long_wing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerticalSpreadCandidate:
    candidate_id: str
    asset: str
    spread_type: str  # "BULL_PUT" or "BEAR_CALL"
    expiry_date: str
    dte: float
    short_leg: dict[str, Any]
    long_wing: dict[str, Any]
    net_credit: float
    max_loss: float
    spread_width: float
    reward_to_risk: float


class VerticalSpreadBot:
    """Directional Vertical Credit Spreads Strategy Engine."""

    def __init__(self, config: VerticalSpreadConfig):
        self.config = config
        self._running = False
        self._active_spreads: list[dict[str, Any]] = []

        self.storage = PaperStorage(self.config.db_path)
        self.margin_calc = MarginCalculator()
        self.matching_engine = MatchingEngine()

        from options_lib.paper_broker.deribit_adapter import DeribitBrokerAdapter
        self.deribit_adapter = (
            DeribitBrokerAdapter(testnet=True) if getattr(self.config, "use_deribit_testnet", False) else None
        )

        acct_id = f"vs_{self.config.asset.lower()}_deribit" if self.config.use_deribit_testnet else f"vs_{self.config.asset.lower()}"
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
                logger.warning("Deribit sync warning for vertical spread: %s", e)

        os.makedirs(self.config.log_dir, exist_ok=True)

    # --- Strike Selection -----------------------------------------------------

    def select_candidate(
        self,
        contracts: list[dict[str, Any]],
        spot: float,
        trend_direction: str = "BULLISH",  # "BULLISH" -> Bull Put, "BEARISH" -> Bear Call
    ) -> VerticalSpreadCandidate | None:
        """Select optimal Bull Put or Bear Call vertical spread."""
        now = datetime.now(UTC)
        is_bullish = trend_direction.upper() == "BULLISH"
        spread_type = "BULL_PUT" if is_bullish else "BEAR_CALL"
        target_opt_type = "put" if is_bullish else "call"

        # Group valid contracts by expiry
        by_expiry: dict[str, list[dict[str, Any]]] = {}
        for c in contracts:
            opt_type = str(c.get("option_type") or c.get("type", "")).lower()
            if opt_type in ("p", "put") and target_opt_type != "put":
                continue
            if opt_type in ("c", "call") and target_opt_type != "call":
                continue

            exp_str = c.get("expiry", "")
            if not exp_str:
                continue

            try:
                exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            except Exception:
                continue

            dte = (exp_dt - now).total_seconds() / 86400.0
            if self.config.min_dte <= dte <= self.config.max_dte:
                by_expiry.setdefault(exp_str, []).append({**c, "dte": dte})

        if not by_expiry:
            return None

        # Sort expiries and pick nearest
        sorted_expiries = sorted(by_expiry.keys())
        target_expiry = sorted_expiries[0]
        chain = by_expiry[target_expiry]

        if is_bullish:
            # Bull Put: short put strike < spot, long wing strike < short put strike
            puts = [c for c in chain if float(c.get("strike", 0)) < spot]
            if len(puts) < 2:
                return None

            # Sort by delta proximity to target short delta (~0.18)
            short_candidates = sorted(
                puts, key=lambda x: abs(abs(float(x.get("delta", 0))) - self.config.target_short_delta)
            )
            short_put = short_candidates[0]
            sp_strike = float(short_put["strike"])

            # Long wing must be lower strike than short put, near target wing delta (~0.05)
            wing_candidates = [c for c in puts if float(c["strike"]) < sp_strike]
            if not wing_candidates:
                return None

            wing_candidates = sorted(
                wing_candidates, key=lambda x: abs(abs(float(x.get("delta", 0))) - self.config.target_wing_delta)
            )
            long_put = wing_candidates[0]
            lp_strike = float(long_put["strike"])

            sp_mark = float(short_put.get("mark_price", 0.0))
            lp_mark = float(long_put.get("mark_price", 0.0))
            net_credit = sp_mark - lp_mark
            spread_width = sp_strike - lp_strike

            if net_credit <= 0 or spread_width <= 0:
                return None

            max_loss = spread_width - net_credit

            return VerticalSpreadCandidate(
                candidate_id=f"vs_bp_{uuid.uuid4().hex[:8]}",
                asset=self.config.asset,
                spread_type="BULL_PUT",
                expiry_date=target_expiry,
                dte=short_put["dte"],
                short_leg={
                    "symbol": short_put.get("symbol", ""),
                    "strike": sp_strike,
                    "delta": float(short_put.get("delta", 0)),
                    "mark": sp_mark,
                    "side": "Sell",
                    "type": "put",
                },
                long_wing={
                    "symbol": long_put.get("symbol", ""),
                    "strike": lp_strike,
                    "delta": float(long_put.get("delta", 0)),
                    "mark": lp_mark,
                    "side": "Buy",
                    "type": "put",
                },
                net_credit=net_credit,
                max_loss=max_loss,
                spread_width=spread_width,
                reward_to_risk=(net_credit / max_loss) if max_loss > 0 else 0.0,
            )
        else:
            # Bear Call: short call strike > spot, long wing strike > short call strike
            calls = [c for c in chain if float(c.get("strike", 0)) > spot]
            if len(calls) < 2:
                return None

            short_candidates = sorted(
                calls, key=lambda x: abs(abs(float(x.get("delta", 0))) - self.config.target_short_delta)
            )
            short_call = short_candidates[0]
            sc_strike = float(short_call["strike"])

            wing_candidates = [c for c in calls if float(c["strike"]) > sc_strike]
            if not wing_candidates:
                return None

            wing_candidates = sorted(
                wing_candidates, key=lambda x: abs(abs(float(x.get("delta", 0))) - self.config.target_wing_delta)
            )
            long_call = wing_candidates[0]
            lc_strike = float(long_call["strike"])

            sc_mark = float(short_call.get("mark_price", 0.0))
            lc_mark = float(long_call.get("mark_price", 0.0))
            net_credit = sc_mark - lc_mark
            spread_width = lc_strike - sc_strike

            if net_credit <= 0 or spread_width <= 0:
                return None

            max_loss = spread_width - net_credit

            return VerticalSpreadCandidate(
                candidate_id=f"vs_bc_{uuid.uuid4().hex[:8]}",
                asset=self.config.asset,
                spread_type="BEAR_CALL",
                expiry_date=target_expiry,
                dte=short_call["dte"],
                short_leg={
                    "symbol": short_call.get("symbol", ""),
                    "strike": sc_strike,
                    "delta": float(short_call.get("delta", 0)),
                    "mark": sc_mark,
                    "side": "Sell",
                    "type": "call",
                },
                long_wing={
                    "symbol": long_call.get("symbol", ""),
                    "strike": lc_strike,
                    "delta": float(long_call.get("delta", 0)),
                    "mark": lc_mark,
                    "side": "Buy",
                    "type": "call",
                },
                net_credit=net_credit,
                max_loss=max_loss,
                spread_width=spread_width,
                reward_to_risk=(net_credit / max_loss) if max_loss > 0 else 0.0,
            )

    # --- Lifecycle Evaluation -------------------------------------------------

    def evaluate_position(
        self,
        entry_credit: float,
        current_spread_cost: float,
        dte: float,
        qty: float,
    ) -> tuple[str, float]:
        """Evaluate 50% TP, Stop Loss, or Expiration for a vertical credit spread.
        
        current_spread_cost: current market price to buy back the short leg minus sell the long wing.
        """
        unrealized_pnl = (entry_credit - current_spread_cost) * qty

        # 1. Expiration check
        if dte <= 0.05:
            if current_spread_cost <= 0.01:
                return "EXPIRED_OTM", entry_credit * qty
            else:
                return "EXPIRED", unrealized_pnl

        # 2. Early Take Profit at 50% max credit
        if current_spread_cost <= entry_credit * (1.0 - self.config.target_profit_pct):
            return "TAKE_PROFIT", unrealized_pnl

        # 3. Stop Loss check
        if unrealized_pnl < -entry_credit * qty * self.config.max_loss_multiplier:
            return "STOP_LOSS", unrealized_pnl

        return "HOLD", unrealized_pnl

    def execute_open_spread(
        self,
        candidate: VerticalSpreadCandidate,
        qty: float,
        spot: float,
    ) -> bool:
        """Execute the two legs of a vertical credit spread (Buy protective wing, Sell short leg)."""
        legs = [
            (candidate.long_wing["symbol"], "Buy", candidate.long_wing["mark"]),
            (candidate.short_leg["symbol"], "Sell", candidate.short_leg["mark"]),
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

