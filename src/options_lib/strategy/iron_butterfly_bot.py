"""Dynamic Iron Butterfly Strategy Bot for Bybit & Deribit Options.

Executes defined-risk 4-leg Iron Butterfly combinations:
1. Sells ATM Straddle at identical strike: Short Call (Delta ~ 0.50) + Short Put (Delta ~ -0.50).
2. Buys OTM Wings for margin protection: Long Call Wing (Delta ~ 0.05 - 0.10) + Long Put Wing (Delta ~ -0.05 - 0.10).
3. Wing-first execution engine: Buys both wings first to lock margin, then sells ATM straddle legs.
4. High-velocity profit taking: Early Take Profit at 25% - 35% max credit.
5. Tight risk management: Stop loss at 0.8x - 1.0x net credit.
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
class IronButterflyConfig:
    """Configuration for Dynamic Iron Butterfly Bot."""

    asset: str = "BTC"
    paper_mode: bool = True
    initial_capital: float = 10000.0

    # Delta targets
    target_atm_delta: float = 0.50   # ATM short straddle strike
    target_wing_delta: float = 0.08  # OTM wings
    min_dte: int = 3
    max_dte: int = 14

    # Signal & Risk parameters
    target_profit_pct: float = 0.30   # Take profit at 30% of max credit
    max_loss_multiplier: float = 1.0  # Stop loss at 1.0x credit
    roll_dte: float = 1.0             # Roll / close when DTE <= 1
    max_concurrent_positions: int = 3
    poll_interval_seconds: int = 300

    # Persistence
    db_path: str = "portfolio_data/paper_trading.db"
    log_dir: str = "logs/iron-butterfly"
    state_file: str = "portfolio_data/iron_butterfly_state.json"

    @classmethod
    def from_env(cls, **overrides) -> IronButterflyConfig:
        config = cls(
            asset=os.getenv("IB_ASSET", cls.asset),
            paper_mode=os.getenv("IB_PAPER_MODE", "true").lower() == "true",
            initial_capital=float(os.getenv("IB_CAPITAL", cls.initial_capital)),
            target_atm_delta=float(os.getenv("IB_ATM_DELTA", cls.target_atm_delta)),
            target_wing_delta=float(os.getenv("IB_WING_DELTA", cls.target_wing_delta)),
            min_dte=int(os.getenv("IB_MIN_DTE", cls.min_dte)),
            max_dte=int(os.getenv("IB_MAX_DTE", cls.max_dte)),
            target_profit_pct=float(os.getenv("IB_TP_PCT", cls.target_profit_pct)),
            max_loss_multiplier=float(os.getenv("IB_SL_MULT", cls.max_loss_multiplier)),
            max_concurrent_positions=int(os.getenv("IB_MAX_CONCURRENT", cls.max_concurrent_positions)),
            db_path=os.getenv("IB_DB_PATH", cls.db_path),
            log_dir=os.getenv("IB_LOG_DIR", cls.log_dir),
            state_file=os.getenv("IB_STATE_FILE", cls.state_file),
        )
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config


@dataclass
class IronButterflyCandidate:
    candidate_id: str
    asset: str
    expiry_date: str
    dte: float
    atm_strike: float
    long_put_strike: float
    long_call_strike: float
    short_put: dict[str, Any]
    short_call: dict[str, Any]
    long_put: dict[str, Any]
    long_call: dict[str, Any]
    net_credit: float
    max_loss: float
    reward_to_risk: float


class IronButterflyBot:
    """Dynamic Iron Butterfly Execution & Lifecycle Engine."""

    def __init__(self, config: IronButterflyConfig):
        self.config = config
        self._running = False

        self.storage = PaperStorage(self.config.db_path)
        self.margin_calc = MarginCalculator()
        self.matching_engine = MatchingEngine()

        acct = self.storage.load_account(f"ib_{self.config.asset}")
        if acct:
            self.paper_account = acct
        else:
            self.paper_account = PaperAccount(
                account_id=f"ib_{self.config.asset.lower()}",
                initial_capital=self.config.initial_capital,
                cash_balance=self.config.initial_capital,
                currency="USDT",
            )
            self.storage.save_account(self.paper_account)

        os.makedirs(self.config.log_dir, exist_ok=True)

    def select_candidate(
        self,
        contracts: list[dict[str, Any]],
        spot: float,
    ) -> IronButterflyCandidate | None:
        """Find the optimal 4-leg Iron Butterfly centered at ATM strike."""
        now = datetime.now(UTC)

        by_expiry: dict[str, list[dict[str, Any]]] = {}
        for c in contracts:
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

        target_expiry = sorted(by_expiry.keys())[0]
        chain = by_expiry[target_expiry]

        calls = [c for c in chain if str(c.get("option_type") or c.get("type", "")).lower() in ("c", "call")]
        puts = [c for c in chain if str(c.get("option_type") or c.get("type", "")).lower() in ("p", "put")]

        if not calls or not puts:
            return None

        # 1. Find the strike closest to Spot (ATM Strike)
        common_strikes = set(float(c["strike"]) for c in calls).intersection(set(float(p["strike"]) for p in puts))
        if not common_strikes:
            return None

        atm_strike = min(common_strikes, key=lambda s: abs(s - spot))

        short_call = next(c for c in calls if float(c["strike"]) == atm_strike)
        short_put = next(p for p in puts if float(p["strike"]) == atm_strike)

        # 2. Find Call Wing (strike > atm_strike) and Put Wing (strike < atm_strike)
        call_wings = [c for c in calls if float(c["strike"]) > atm_strike]
        put_wings = [p for p in puts if float(p["strike"]) < atm_strike]

        if not call_wings or not put_wings:
            return None

        # Sort wings by delta proximity to target_wing_delta
        call_wings.sort(key=lambda x: abs(abs(float(x.get("delta", 0))) - self.config.target_wing_delta))
        put_wings.sort(key=lambda x: abs(abs(float(x.get("delta", 0))) - self.config.target_wing_delta))

        long_call = call_wings[0]
        long_put = put_wings[0]

        lc_strike = float(long_call["strike"])
        lp_strike = float(long_put["strike"])

        # Calculate credit
        sc_mark = float(short_call.get("mark_price", 0))
        sp_mark = float(short_put.get("mark_price", 0))
        lc_mark = float(long_call.get("mark_price", 0))
        lp_mark = float(long_put.get("mark_price", 0))

        net_credit = (sc_mark + sp_mark) - (lc_mark + lp_mark)
        max_wing_width = max(lc_strike - atm_strike, atm_strike - lp_strike)
        max_loss = max_wing_width - net_credit

        if net_credit <= 0 or max_loss <= 0:
            return None

        return IronButterflyCandidate(
            candidate_id=f"ib_{uuid.uuid4().hex[:8]}",
            asset=self.config.asset,
            expiry_date=target_expiry,
            dte=short_call["dte"],
            atm_strike=atm_strike,
            long_put_strike=lp_strike,
            long_call_strike=lc_strike,
            short_put={"symbol": short_put.get("symbol", ""), "strike": atm_strike, "mark": sp_mark, "side": "Sell", "type": "put"},
            short_call={"symbol": short_call.get("symbol", ""), "strike": atm_strike, "mark": sc_mark, "side": "Sell", "type": "call"},
            long_put={"symbol": long_put.get("symbol", ""), "strike": lp_strike, "mark": lp_mark, "side": "Buy", "type": "put"},
            long_call={"symbol": long_call.get("symbol", ""), "strike": lc_strike, "mark": lc_mark, "side": "Buy", "type": "call"},
            net_credit=net_credit,
            max_loss=max_loss,
            reward_to_risk=(net_credit / max_loss) if max_loss > 0 else 0.0,
        )

    def evaluate_position(
        self,
        entry_credit: float,
        current_combo_debit: float,
        dte: float,
        qty: float,
    ) -> tuple[str, float]:
        """Evaluate early 30% TP, 1.0x SL, or Expiry for Iron Butterfly."""
        unrealized_pnl = (entry_credit - current_combo_debit) * qty

        if dte <= 0.05:
            if current_combo_debit <= 0.01:
                return "EXPIRED_OTM", entry_credit * qty
            return "EXPIRED", unrealized_pnl

        # 1. Take Profit at 30% max credit
        if current_combo_debit <= entry_credit * (1.0 - self.config.target_profit_pct):
            return "TAKE_PROFIT", unrealized_pnl

        # 2. Stop Loss at 1.0x credit
        if unrealized_pnl < -entry_credit * qty * self.config.max_loss_multiplier:
            return "STOP_LOSS", unrealized_pnl

        return "HOLD", unrealized_pnl

