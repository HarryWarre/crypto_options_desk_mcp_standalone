"""The Wheel Strategy Bot (Cash-Secured Put + Covered Call Yield Bot).

Implements systematic options yield generation:
1. Phase 1 (Cash-Secured Put): Sell OTM Puts (Delta ~ 0.15 - 0.25) to collect premium.
2. Phase 2 (Assignment): If assigned at expiry, acquire Spot asset at discounted cost basis.
3. Phase 3 (Covered Call): Sell OTM Calls (Delta ~ 0.15 - 0.25) with Strike >= Cost Basis.
4. Phase 4 (Called Away): If underlying closes above strike, sell Spot at profit and return to Phase 1.

Supports Paper Trading via PaperBroker and Live Trading via Bybit V5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import signal
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
class WheelConfig:
    """Configuration parameters for The Wheel Strategy Bot."""

    asset: str = "BTC"
    paper_mode: bool = True
    initial_capital: float = 10000.0

    # Delta targets
    target_put_delta: float = 0.20  # Delta for selling puts (0.15 - 0.25)
    target_call_delta: float = 0.20  # Delta for selling calls (0.15 - 0.25)
    min_dte: int = 5
    max_dte: int = 21

    # Signal & Risk parameters
    iv_rv_threshold: float = 0.0  # Min IV - RV spread
    target_profit_pct: float = 0.50  # Take profit at 50% max credit
    max_loss_multiplier: float = 2.0  # Stop loss multiplier on credit
    roll_dte: float = 1.0  # DTE threshold to close/roll before expiry

    # Position sizing
    qty: float = 0.0  # 0 = auto-size based on cash/spot balance
    max_concurrent_positions: int = 2
    poll_interval_seconds: int = 300  # 5 minutes

    # Persistence
    db_path: str = "portfolio_data/paper_trading.db"
    log_dir: str = "logs/wheel"
    state_file: str = "portfolio_data/wheel_state.json"

    @classmethod
    def from_env(cls, **overrides) -> WheelConfig:
        config = cls(
            asset=os.getenv("WHEEL_ASSET", cls.asset),
            paper_mode=os.getenv("WHEEL_PAPER_MODE", "true").lower() == "true",
            initial_capital=float(os.getenv("WHEEL_CAPITAL", cls.initial_capital)),
            target_put_delta=float(os.getenv("WHEEL_PUT_DELTA", cls.target_put_delta)),
            target_call_delta=float(os.getenv("WHEEL_CALL_DELTA", cls.target_call_delta)),
            min_dte=int(os.getenv("WHEEL_MIN_DTE", cls.min_dte)),
            max_dte=int(os.getenv("WHEEL_MAX_DTE", cls.max_dte)),
            target_profit_pct=float(os.getenv("WHEEL_TP_PCT", cls.target_profit_pct)),
            max_loss_multiplier=float(os.getenv("WHEEL_SL_MULT", cls.max_loss_multiplier)),
            qty=float(os.getenv("WHEEL_QTY", cls.qty)),
            poll_interval_seconds=int(os.getenv("WHEEL_POLL_INTERVAL", cls.poll_interval_seconds)),
            db_path=os.getenv("WHEEL_DB_PATH", cls.db_path),
            log_dir=os.getenv("WHEEL_LOG_DIR", cls.log_dir),
            state_file=os.getenv("WHEEL_STATE_FILE", cls.state_file),
        )
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config


@dataclass
class WheelLeg:
    symbol: str
    side: str  # "Sell"
    strike: float
    option_type: str  # "put" or "call"
    delta: float
    entry_price: float
    current_mark: float
    qty: float
    role: str  # "cash_secured_put" or "covered_call"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WheelCandidate:
    candidate_id: str
    asset: str
    phase: str  # "CSP" or "CC"
    symbol: str
    option_type: str
    strike: float
    expiry_date: str
    dte: float
    delta: float
    bid: float
    ask: float
    mark_price: float
    premium_collected: float
    required_collateral: float


class WheelBot:
    """The Wheel Strategy Execution & Lifecycle Engine."""

    def __init__(self, config: WheelConfig):
        self.config = config
        self._running = False

        # State tracking
        self.phase: str = "CSP"  # "CSP" (holding cash) or "CC" (holding spot)
        self.cash_balance: float = config.initial_capital
        self.spot_holdings: float = 0.0
        self.cost_basis: float = 0.0  # Average price per unit of assigned spot
        self.total_premiums_collected: float = 0.0
        self.completed_cycles: int = 0

        self._active_positions: list[WheelLeg] = []

        # Broker integration
        self.storage = PaperStorage(self.config.db_path)
        self.margin_calc = MarginCalculator()
        self.matching_engine = MatchingEngine()

        # Restore or create paper account
        acct = self.storage.load_account(self.config.asset)
        if acct:
            self.paper_account = acct
        else:
            self.paper_account = PaperAccount(
                account_id=f"wheel_{self.config.asset.lower()}",
                initial_capital=self.config.initial_capital,
                cash_balance=self.config.initial_capital,
                currency="USDT",
            )
            self.storage.save_account(self.paper_account)

        os.makedirs(self.config.log_dir, exist_ok=True)
        self._load_state()

    def _load_state(self) -> None:
        state_path = Path(self.config.state_file)
        if state_path.exists():
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.phase = data.get("phase", "CSP")
                    self.spot_holdings = float(data.get("spot_holdings", 0.0))
                    self.cost_basis = float(data.get("cost_basis", 0.0))
                    self.total_premiums_collected = float(data.get("total_premiums_collected", 0.0))
                    self.completed_cycles = int(data.get("completed_cycles", 0))
            except Exception as e:
                logger.warning(f"Failed to load Wheel state from {state_path}: {e}")

    def _save_state(self) -> None:
        state_path = Path(self.config.state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "phase": self.phase,
            "spot_holdings": self.spot_holdings,
            "cost_basis": self.cost_basis,
            "total_premiums_collected": self.total_premiums_collected,
            "completed_cycles": self.completed_cycles,
            "active_positions": [p.to_dict() for p in self._active_positions],
            "last_updated": datetime.now(UTC).isoformat(),
        }
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # --- Strike & Candidate Selection -----------------------------------------

    def select_csp_candidate(
        self, contracts: list[dict[str, Any]], spot: float
    ) -> WheelCandidate | None:
        """Locate optimal OTM Put contract for Cash-Secured Put Phase."""
        now = datetime.now(UTC)
        put_candidates: list[dict[str, Any]] = []

        for c in contracts:
            opt_type = c.get("option_type") or c.get("type", "")
            if str(opt_type).lower() not in ("put", "p"):
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

            strike = float(c.get("strike", 0))
            if strike >= spot:  # Must be strictly OTM put
                continue

            delta = abs(float(c.get("delta", 0.0)))
            bid = float(c.get("bid", 0.0))
            mark = float(c.get("mark_price", (bid + float(c.get("ask", 0.0))) / 2.0))

            if mark <= 0:
                continue

            # Check delta proximity
            delta_diff = abs(delta - self.config.target_put_delta)
            put_candidates.append({
                "contract": c,
                "dte": dte,
                "strike": strike,
                "delta": delta,
                "delta_diff": delta_diff,
                "mark": mark,
                "bid": bid,
                "ask": float(c.get("ask", 0.0)),
                "expiry": exp_str,
                "symbol": c.get("symbol", ""),
            })

        if not put_candidates:
            return None

        # Sort by closest to target delta
        put_candidates.sort(key=lambda x: (x["delta_diff"], -x["mark"]))
        best = put_candidates[0]

        return WheelCandidate(
            candidate_id=f"csp_{uuid.uuid4().hex[:8]}",
            asset=self.config.asset,
            phase="CSP",
            symbol=best["symbol"],
            option_type="put",
            strike=best["strike"],
            expiry_date=best["expiry"],
            dte=best["dte"],
            delta=best["delta"],
            bid=best["bid"],
            ask=best["ask"],
            mark_price=best["mark"],
            premium_collected=best["mark"],
            required_collateral=best["strike"],
        )

    def select_cc_candidate(
        self, contracts: list[dict[str, Any]], spot: float, cost_basis: float
    ) -> WheelCandidate | None:
        """Locate optimal OTM Call contract for Covered Call Phase satisfying Cost-Basis Floor."""
        now = datetime.now(UTC)
        call_candidates: list[dict[str, Any]] = []

        effective_floor = max(cost_basis, spot)

        for c in contracts:
            opt_type = c.get("option_type") or c.get("type", "")
            if str(opt_type).lower() not in ("call", "c"):
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

            strike = float(c.get("strike", 0))
            # Critical Cost-Basis Floor Rule
            if strike < effective_floor:
                continue

            delta = abs(float(c.get("delta", 0.0)))
            bid = float(c.get("bid", 0.0))
            mark = float(c.get("mark_price", (bid + float(c.get("ask", 0.0))) / 2.0))

            if mark <= 0:
                continue

            delta_diff = abs(delta - self.config.target_call_delta)
            call_candidates.append({
                "contract": c,
                "dte": dte,
                "strike": strike,
                "delta": delta,
                "delta_diff": delta_diff,
                "mark": mark,
                "bid": bid,
                "ask": float(c.get("ask", 0.0)),
                "expiry": exp_str,
                "symbol": c.get("symbol", ""),
            })

        if not call_candidates:
            return None

        call_candidates.sort(key=lambda x: (x["delta_diff"], -x["mark"]))
        best = call_candidates[0]

        return WheelCandidate(
            candidate_id=f"cc_{uuid.uuid4().hex[:8]}",
            asset=self.config.asset,
            phase="CC",
            symbol=best["symbol"],
            option_type="call",
            strike=best["strike"],
            expiry_date=best["expiry"],
            dte=best["dte"],
            delta=best["delta"],
            bid=best["bid"],
            ask=best["ask"],
            mark_price=best["mark"],
            premium_collected=best["mark"],
            required_collateral=spot,
        )

    # --- Lifecycle Evaluation -------------------------------------------------

    def evaluate_active_position(
        self, pos: WheelLeg, current_mark: float, current_spot: float, now: datetime, expiry_dt: datetime
    ) -> tuple[str, float]:
        """Evaluate TP, SL, Assignment, or Expiry for an active Wheel position.
        
        Returns (action, pnl):
        action in ('HOLD', 'TAKE_PROFIT', 'EXPIRED_OTM', 'ASSIGNED', 'CALLED_AWAY', 'STOP_LOSS')
        """
        # Premium collected at entry per unit
        entry_credit = pos.entry_price
        current_cost = current_mark
        unrealized_pnl = (entry_credit - current_cost) * pos.qty

        dte = (expiry_dt - now).total_seconds() / 86400.0

        # 1. Expiry or DTE <= 0.05
        if dte <= 0.05:
            if pos.role == "cash_secured_put":
                if current_spot < pos.strike:
                    # In The Money: Assigned Spot!
                    return "ASSIGNED", unrealized_pnl
                else:
                    # Out of The Money: Full Profit!
                    return "EXPIRED_OTM", entry_credit * pos.qty
            else:  # covered_call
                if current_spot > pos.strike:
                    # In The Money: Called Away!
                    return "CALLED_AWAY", unrealized_pnl
                else:
                    return "EXPIRED_OTM", entry_credit * pos.qty

        # 2. Take Profit at 50% max credit
        if current_cost <= entry_credit * (1.0 - self.config.target_profit_pct):
            return "TAKE_PROFIT", unrealized_pnl

        # 3. Stop loss check
        if unrealized_pnl < -entry_credit * pos.qty * self.config.max_loss_multiplier:
            return "STOP_LOSS", unrealized_pnl

        return "HOLD", unrealized_pnl
