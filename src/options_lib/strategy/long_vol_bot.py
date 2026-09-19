"""Long Volatility Straddle & Strangle Strategy Bot (Catalyst Breakout & Vol Expansion Engine).

Executes Volatility-Expansion Plays:
1. Implied Volatility Discount Screener: Identifies regimes where Implied Volatility (IV)
   is underpriced relative to Realized Volatility (RV), i.e. RV >= IV * 1.0.
2. Straddle / Strangle Matcher: Enters simultaneous Long ATM Call + Long ATM Put (or OTM Strangle)
   with defined risk strictly capped at Net Debit.
3. Convex Payoff Lifecycle:
   - Take Profit at 35% ROI on Net Debit.
   - Stop Loss at 25% on Net Debit decay.
   - Expiration harvest exit at DTE <= 1.0 day to avoid terminal zero theta cliff.
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
class LongVolConfig:
    """Configuration for Long Volatility Straddle & Strangle Strategy Bot."""

    asset: str = "BTC"
    paper_mode: bool = True
    initial_capital: float = 10000.0

    # Tenor selection
    min_dte: int = 5
    max_dte: int = 18

    # Edge parameters
    min_rv_iv_ratio: float = 1.00      # Realized vol >= Implied vol (IV Discount)
    target_profit_pct: float = 0.35    # Take profit at 35% ROI
    max_loss_pct: float = 0.25         # Stop loss at 25% loss
    exit_dte_threshold: float = 1.0    # Exit before terminal 24h decay
    max_concurrent_positions: int = 3
    poll_interval_seconds: int = 300

    # Persistence
    db_path: str = "portfolio_data/paper_trading.db"
    log_dir: str = "logs/long-vol"
    state_file: str = "portfolio_data/long_vol_state.json"

    @classmethod
    def from_env(cls, **overrides) -> LongVolConfig:
        config = cls(
            asset=os.getenv("LV_ASSET", cls.asset),
            paper_mode=os.getenv("LV_PAPER_MODE", "true").lower() == "true",
            initial_capital=float(os.getenv("LV_CAPITAL", cls.initial_capital)),
            min_dte=int(os.getenv("LV_MIN_DTE", cls.min_dte)),
            max_dte=int(os.getenv("LV_MAX_DTE", cls.max_dte)),
            min_rv_iv_ratio=float(os.getenv("LV_RV_IV_RATIO", cls.min_rv_iv_ratio)),
            target_profit_pct=float(os.getenv("LV_TP_PCT", cls.target_profit_pct)),
            max_loss_pct=float(os.getenv("LV_SL_PCT", cls.max_loss_pct)),
            max_concurrent_positions=int(os.getenv("LV_MAX_CONCURRENT", cls.max_concurrent_positions)),
            db_path=os.getenv("LV_DB_PATH", cls.db_path),
            log_dir=os.getenv("LV_LOG_DIR", cls.log_dir),
            state_file=os.getenv("LV_STATE_FILE", cls.state_file),
        )
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config


@dataclass
class LongVolCandidate:
    candidate_id: str
    asset: str
    atm_strike: float
    expiry: str
    dte: float
    call_leg: dict[str, Any]
    put_leg: dict[str, Any]
    net_debit: float
    iv: float


class LongVolBot:
    """Long Volatility Straddle & Strangle Strategy Engine."""

    def __init__(self, config: LongVolConfig):
        self.config = config
        self._running = False

        self.storage = PaperStorage(self.config.db_path)
        self.margin_calc = MarginCalculator()
        self.matching_engine = MatchingEngine()

        acct = self.storage.load_account(f"lv_{self.config.asset}")
        if acct:
            self.paper_account = acct
        else:
            self.paper_account = PaperAccount(
                account_id=f"lv_{self.config.asset.lower()}",
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
        realized_vol: float,
    ) -> LongVolCandidate | None:
        """Find optimal ATM Long Straddle when Realized Volatility exceeds Implied Volatility."""
        now = datetime.now(UTC)
        eligible_calls: list[dict[str, Any]] = []
        eligible_puts: list[dict[str, Any]] = []

        for c in contracts:
            c_type = str(c.get("option_type") or c.get("type", "")).lower()
            if c_type in ("c", "call"):
                norm_type = "call"
            elif c_type in ("p", "put"):
                norm_type = "put"
            else:
                continue

            exp_str = c.get("expiry", "")
            if not exp_str:
                continue
            try:
                exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            except Exception:
                continue

            dte = (exp_dt - now).total_seconds() / 86400.0
            if not (self.config.min_dte <= dte <= self.config.max_dte):
                continue

            item = {**c, "dte": dte, "expiry_str": exp_str}
            if norm_type == "call":
                eligible_calls.append(item)
            else:
                eligible_puts.append(item)

        if not eligible_calls or not eligible_puts:
            return None

        # Check IV Discount: Average IV vs Realized Vol
        iv_values = [float(c.get("iv", 0.55)) for c in eligible_calls + eligible_puts if float(c.get("iv", 0)) > 0]
        if not iv_values:
            return None
        avg_iv = sum(iv_values) / len(iv_values)

        if realized_vol < avg_iv * self.config.min_rv_iv_ratio:
            logger.info(f"Skipping Long Vol: RV {realized_vol:.1%} < IV {avg_iv:.1%} * {self.config.min_rv_iv_ratio}")
            return None

        # Find common strikes available in both Calls and Puts
        call_strikes = set(float(c["strike"]) for c in eligible_calls)
        put_strikes = set(float(c["strike"]) for c in eligible_puts)
        common = call_strikes.intersection(put_strikes)

        if not common:
            return None

        atm_strike = min(common, key=lambda s: abs(s - spot))
        if abs(atm_strike - spot) / spot > 0.03:
            return None

        call_cand = next(c for c in eligible_calls if float(c["strike"]) == atm_strike)
        put_cand = next(c for c in eligible_puts if float(c["strike"]) == atm_strike)

        c_mark = float(call_cand.get("mark_price", 0))
        p_mark = float(put_cand.get("mark_price", 0))
        net_debit = c_mark + p_mark

        if net_debit <= 0:
            return None

        return LongVolCandidate(
            candidate_id=f"lv_{uuid.uuid4().hex[:8]}",
            asset=self.config.asset,
            atm_strike=atm_strike,
            expiry=call_cand["expiry_str"],
            dte=call_cand["dte"],
            call_leg={"symbol": call_cand.get("symbol", ""), "strike": atm_strike, "mark": c_mark, "side": "Buy"},
            put_leg={"symbol": put_cand.get("symbol", ""), "strike": atm_strike, "mark": p_mark, "side": "Buy"},
            net_debit=net_debit,
            iv=avg_iv,
        )

    def evaluate_position(
        self,
        entry_debit: float,
        current_spread_value: float,
        dte: float,
        qty: float,
    ) -> tuple[str, float]:
        """Evaluate Take Profit, Stop Loss, or Expiration Exit for Long Straddle."""
        unrealized_pnl = (current_spread_value - entry_debit) * qty

        # 1. Expiration Exit (avoid terminal 24h theta collapse)
        if dte <= self.config.exit_dte_threshold:
            return "EXPIRY_EXIT", unrealized_pnl

        # 2. 35% Take Profit
        if current_spread_value >= entry_debit * (1.0 + self.config.target_profit_pct):
            return "TAKE_PROFIT", unrealized_pnl

        # 3. 25% Stop Loss
        if current_spread_value <= entry_debit * (1.0 - self.config.max_loss_pct):
            return "STOP_LOSS", unrealized_pnl

        return "HOLD", unrealized_pnl
