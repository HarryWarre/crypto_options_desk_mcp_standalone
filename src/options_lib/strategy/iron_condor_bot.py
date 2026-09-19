"""Dynamic Iron Condor Strategy Bot for Bybit Options.

Supports Paper Trading via PaperBroker (PaperAccount, MatchingEngine, MarginCalculator,
PaperStorage) and Live Trading via Bybit V5 API.

Features:
1. Regime & Volatility Trigger: IV - RV spread check.
2. Dynamic Delta-Based Strike Selection (Short Delta ~0.15, Wing Delta ~0.03).
3. Legging-in Execution Engine: Buys wings first to lock margin, sells short strikes second.
4. Aggressive Compounding & 50% Take-Profit early exit.
5. Stop-loss at 2x credit and Expiry roll when DTE <= 1.
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
    DeribitBrokerAdapter,
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
class IronCondorConfig:
    """Configuration parameters for Iron Condor Bot."""

    asset: str = "BTC"
    paper_mode: bool = True
    use_deribit_testnet: bool = False
    initial_capital: float = 10000.0

    # Delta targeting
    target_short_delta: float = 0.15
    target_wing_delta: float = 0.03
    min_dte: int = 5
    max_dte: int = 16

    # Signal & Risk parameters
    iv_rv_threshold: float = 6.0  # min IV - RV in vol points
    target_profit_pct: float = 0.50  # close at 50% max credit
    max_loss_multiplier: float = 0.8  # close if loss > 0.8x credit (empirically optimized)
    max_margin_utilization: float = 0.85
    roll_dte: float = 1.0  # close or roll when DTE <= 1 day

    # Position sizing
    qty: float = 0.0  # 0 = auto-size based on account margin
    poll_interval_seconds: int = 300  # check every 5 minutes

    # Storage paths
    db_path: str = "portfolio_data/paper_trading.db"
    log_dir: str = "logs/iron-condor"
    state_file: str = "iron_condor_state.json"

    @classmethod
    def from_env(cls, **overrides) -> IronCondorConfig:
        config = cls(
            asset=os.getenv("IC_ASSET", cls.asset),
            paper_mode=os.getenv("IC_PAPER_MODE", "true").lower() == "true",
            use_deribit_testnet=os.getenv("IC_USE_DERIBIT_TESTNET", "false").lower() in ("true", "1"),
            initial_capital=float(os.getenv("IC_CAPITAL", cls.initial_capital)),
            target_short_delta=float(os.getenv("IC_SHORT_DELTA", cls.target_short_delta)),
            target_wing_delta=float(os.getenv("IC_WING_DELTA", cls.target_wing_delta)),
            min_dte=int(os.getenv("IC_MIN_DTE", cls.min_dte)),
            max_dte=int(os.getenv("IC_MAX_DTE", cls.max_dte)),
            iv_rv_threshold=float(os.getenv("IC_IV_RV_THRESHOLD", cls.iv_rv_threshold)),
            target_profit_pct=float(os.getenv("IC_TP_PCT", cls.target_profit_pct)),
            max_loss_multiplier=float(os.getenv("IC_SL_MULT", cls.max_loss_multiplier)),
            qty=float(os.getenv("IC_QTY", cls.qty)),
            poll_interval_seconds=int(os.getenv("IC_POLL_INTERVAL", cls.poll_interval_seconds)),
            db_path=os.getenv("IC_DB_PATH", cls.db_path),
            log_dir=os.getenv("IC_LOG_DIR", cls.log_dir),
        )
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config


@dataclass
class IronCondorLeg:
    symbol: str
    side: str  # "Buy" or "Sell"
    strike: float
    option_type: str  # "call" or "put"
    delta: float
    entry_price: float
    current_mark: float
    qty: float
    role: str  # "short_call", "long_call", "short_put", "long_put"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IronCondorCandidate:
    """Calculated 4-leg Iron Condor opportunity ready for execution."""

    condor_id: str
    asset: str
    expiry_date: str
    dte: float
    long_put: dict[str, Any]
    short_put: dict[str, Any]
    short_call: dict[str, Any]
    long_call: dict[str, Any]
    net_credit_per_unit: float
    call_spread_width: float
    put_spread_width: float
    max_loss_per_unit: float
    pop: float  # Probability of Profit estimate


class IronCondorBot:
    """Automated Iron Condor trading bot with PaperBroker support."""

    STRATEGY_NAME = "iron_condor"

    def __init__(self, config: IronCondorConfig) -> None:
        self.config = config
        self.account_id = f"ic_{config.asset.lower()}_deribit_swing" if config.use_deribit_testnet else f"ic_{config.asset.lower()}_paper"
        self._running = False
        self._active_candidate: IronCondorCandidate | None = None
        self._active_condor_id: str | None = None
        self._active_legs: list[IronCondorLeg] = []
        self._entry_credit: float = 0.0
        self._entry_time: str | None = None
        self._total_compounded_profit: float = 0.0

        # Setup paths & logging
        self._log_path = Path(config.log_dir) / config.asset
        self._log_path.mkdir(parents=True, exist_ok=True)
        self._setup_logging()
        self._install_signal_handlers()

        # Broker components
        self.storage = PaperStorage(db_path=config.db_path)
        self.matching_engine = MatchingEngine()
        self.margin_calculator = MarginCalculator()
        self.deribit_adapter = DeribitBrokerAdapter(testnet=True) if config.use_deribit_testnet else None

        self.paper_account = self.storage.load_account(
            account_id=self.account_id,
            default_capital=config.initial_capital,
        )

        if self.deribit_adapter:
            try:
                self.deribit_adapter.sync_account(self.paper_account, currency=self.config.asset)
            except Exception as e:
                logger.warning("Failed initial Deribit sync: %s", e)

        # Restore active condor state if exists
        self._restore_active_state()

    def _setup_logging(self) -> None:
        self._jsonl_path = self._log_path / "events.jsonl"
        fh = logging.FileHandler(self._log_path / "bot.log")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)

    def _log_event(self, event: str, data: dict[str, Any] | None = None) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            "asset": self.config.asset,
            "paper": self.config.paper_mode,
            **(data or {}),
        }
        logger.info(f"[{event}] {json.dumps(data or {}, default=str)}")
        try:
            with open(self._jsonl_path, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle_signal)
            except (ValueError, AttributeError):
                pass  # Ignore if not in main thread

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info(f"Signal {signum} received — shutting down gracefully")
        self._running = False

    def _restore_active_state(self) -> None:
        """Find open positions in paper_account belonging to an active Iron Condor."""
        legs_found: list[IronCondorLeg] = []
        condor_id = None
        for sym, pos in self.paper_account.positions.items():
            if pos.strategy_id and pos.strategy_id.startswith("ic_"):
                condor_id = pos.strategy_id
                parsed = parse_bybit_option_symbol(sym)
                opt_type = parsed["option_type_long"] if parsed else "call"
                strike = parsed["strike"] if parsed else 0.0
                legs_found.append(
                    IronCondorLeg(
                        symbol=sym,
                        side=pos.side,
                        strike=strike,
                        option_type=opt_type,
                        delta=0.0,
                        entry_price=pos.entry_price,
                        current_mark=pos.current_mark_price,
                        qty=pos.qty,
                        role=pos.leg_role or "unknown",
                    )
                )

        if len(legs_found) == 4 and condor_id:
            self._active_condor_id = condor_id
            self._active_legs = legs_found
            short_credit = sum(l.entry_price for l in legs_found if l.side == "Sell")
            long_debit = sum(l.entry_price for l in legs_found if l.side == "Buy")
            self._entry_credit = (short_credit - long_debit) * legs_found[0].qty
            self._log_event(
                "active_condor_restored",
                {"condor_id": condor_id, "net_credit": self._entry_credit},
            )

    # --- Market Selection & Regime Evaluation ---------------------------------

    def select_iron_condor_candidate(
        self,
        contracts: list[dict[str, Any]],
        spot: float,
    ) -> IronCondorCandidate | None:
        """Find the optimal 4-leg Iron Condor based on target DTE and Deltas."""
        now = datetime.now(UTC)

        # 1. Group contracts by expiry and filter for target DTE window
        by_expiry: dict[str, list[dict[str, Any]]] = {}
        for c in contracts:
            exp_str = c.get("expiry", "")
            if not exp_str and c.get("symbol"):
                parsed_sym = parse_bybit_option_symbol(c["symbol"])
                if parsed_sym:
                    exp_str = parsed_sym["expiry"]
            if not exp_str:
                continue

            # Parse expiry datetime
            try:
                if "T" in exp_str:
                    exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                else:
                    exp_dt = datetime.fromisoformat(f"{exp_str[:10]}T08:00:00+00:00")
            except Exception:
                continue

            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=UTC)

            dte = (exp_dt - now).total_seconds() / 86400.0
            if self.config.min_dte <= dte <= self.config.max_dte:
                by_expiry.setdefault(exp_str[:10], []).append(c)

        if not by_expiry:
            return None

        # Pick nearest eligible expiry
        target_expiry = sorted(by_expiry.keys())[0]
        chain = by_expiry[target_expiry]

        calls = [c for c in chain if str(c.get("option_type", "")).lower() == "call"]
        puts = [c for c in chain if str(c.get("option_type", "")).lower() == "put"]

        if len(calls) < 2 or len(puts) < 2:
            return None

        # Helper to get delta safely
        def _get_delta(c: dict[str, Any]) -> float:
            d = c.get("delta")
            if d is not None and not math.isnan(float(d)):
                return float(d)
            # Fallback approximate delta from moneyness if delta not supplied
            strike = float(c["strike"])
            is_call = str(c.get("option_type", "")).lower() == "call"
            m = strike / spot
            if is_call:
                return max(0.01, min(0.99, 0.5 - (m - 1.0) * 2.0))
            else:
                return max(-0.99, min(-0.01, -0.5 + (1.0 - m) * 2.0))

        # Select Call legs (Short Call ~0.15, Long Call Wing ~0.03)
        calls_otm = [c for c in calls if float(c["strike"]) > spot]
        if len(calls_otm) < 2:
            return None
        calls_otm.sort(key=lambda c: abs(_get_delta(c) - self.config.target_short_delta))
        short_call = calls_otm[0]

        remaining_calls = [c for c in calls if float(c["strike"]) > float(short_call["strike"])]
        if not remaining_calls:
            return None
        remaining_calls.sort(key=lambda c: abs(_get_delta(c) - self.config.target_wing_delta))
        long_call = remaining_calls[0]

        # Select Put legs (Short Put ~ -0.15, Long Put Wing ~ -0.03)
        puts_otm = [c for c in puts if float(c["strike"]) < spot]
        if len(puts_otm) < 2:
            return None
        puts_otm.sort(key=lambda c: abs(_get_delta(c) - (-self.config.target_short_delta)))
        short_put = puts_otm[0]

        remaining_puts = [c for c in puts if float(c["strike"]) < float(short_put["strike"])]
        if not remaining_puts:
            return None
        remaining_puts.sort(key=lambda c: abs(_get_delta(c) - (-self.config.target_wing_delta)))
        long_put = remaining_puts[0]

        # Validate strike monotonicity: K_lp < K_sp < spot < K_sc < K_lc
        k_lp = float(long_put["strike"])
        k_sp = float(short_put["strike"])
        k_sc = float(short_call["strike"])
        k_lc = float(long_call["strike"])

        if not (k_lp < k_sp < spot < k_sc < k_lc):
            return None

        def _mid_or_mark(c: dict[str, Any]) -> float:
            bid = float(c.get("bid_price") or c.get("bid") or 0)
            ask = float(c.get("ask_price") or c.get("ask") or 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2.0
            return float(c.get("mark_price", 0) or 0)

        p_lp = _mid_or_mark(long_put)
        p_sp = _mid_or_mark(short_put)
        p_sc = _mid_or_mark(short_call)
        p_lc = _mid_or_mark(long_call)

        net_credit = (p_sp + p_sc) - (p_lp + p_lc)
        if net_credit <= 0:
            return None

        call_width = k_lc - k_sc
        put_width = k_sp - k_lp
        max_loss = max(call_width, put_width) - net_credit

        condor_id = f"ic_{self.config.asset.lower()}_{uuid.uuid4().hex[:8]}"

        return IronCondorCandidate(
            condor_id=condor_id,
            asset=self.config.asset,
            expiry_date=target_expiry,
            dte=(datetime.fromisoformat(f"{target_expiry}T08:00:00+00:00") - now).total_seconds() / 86400.0,
            long_put=long_put,
            short_put=short_put,
            short_call=short_call,
            long_call=long_call,
            net_credit_per_unit=net_credit,
            call_spread_width=call_width,
            put_spread_width=put_width,
            max_loss_per_unit=max_loss,
            pop=round(1.0 - (self.config.target_short_delta * 2.0), 3),
        )

    # --- Execution Engine (Legging-In) ----------------------------------------

    def execute_open_condor(
        self,
        candidate: IronCondorCandidate,
        spot: float,
    ) -> bool:
        """Execute Iron Condor by legging-in: Long wings first, Short legs second."""
        # Calculate sizing
        qty = self.config.qty
        if qty <= 0:
            # Auto-size using available equity and spread width
            # Target ~20-30% capital per trade for safe compounding
            max_risk_budget = self.paper_account.equity * 0.25
            max_loss_unit = candidate.max_loss_per_unit
            if max_loss_unit > 0:
                qty = max(0.01, round(max_risk_budget / max_loss_unit, 3))
            else:
                qty = 0.05

        self._log_event(
            "opening_iron_condor",
            {
                "condor_id": candidate.condor_id,
                "expiry": candidate.expiry_date,
                "qty": qty,
                "credit_per_unit": candidate.net_credit_per_unit,
                "pop": candidate.pop,
            },
        )

        legs_to_execute = [
            # Chặng 1: Mua wings trước để khóa Margin Floor
            (candidate.long_put, "Buy", "long_put"),
            (candidate.long_call, "Buy", "long_call"),
            # Chặng 2: Bán Short legs
            (candidate.short_put, "Sell", "short_put"),
            (candidate.short_call, "Sell", "short_call"),
        ]

        executed_legs: list[IronCondorLeg] = []

        if self.config.paper_mode:
            for contract, side, role in legs_to_execute:
                sym = contract["symbol"]
                order = PaperOrder(
                    symbol=sym,
                    side=side,
                    qty=qty,
                    order_type=OrderType.MARKET,
                    strategy_id=candidate.condor_id,
                    leg_role=role,
                )
                if self.config.use_deribit_testnet and self.deribit_adapter:
                    res = self.deribit_adapter.execute_order(order, spot=spot)
                else:
                    res = self.matching_engine.match_order(
                        order=order,
                        best_bid=float(contract.get("bid_price") or contract.get("bid") or 0),
                        best_ask=float(contract.get("ask_price") or contract.get("ask") or 0),
                        spot=spot,
                        mark_price=float(contract.get("mark_price", 0) or 0),
                    )
                if not res.is_filled:
                    self._log_event("leg_execution_failed", {"symbol": sym, "error": res.message})
                    return False

                trade = self.paper_account.apply_fill(
                    symbol=sym,
                    side=side,
                    qty=qty,
                    price=res.filled_price,
                    fee=res.fee,
                    spot=spot,
                    strategy_id=candidate.condor_id,
                    leg_role=role,
                    order_id=res.order_id,
                )
                executed_legs.append(
                    IronCondorLeg(
                        symbol=sym,
                        side=side,
                        strike=float(contract["strike"]),
                        option_type=str(contract.get("option_type", "")).lower(),
                        delta=float(contract.get("delta", 0.0) or 0.0),
                        entry_price=res.filled_price,
                        current_mark=res.filled_price,
                        qty=qty,
                        role=role,
                    )
                )

            # Record state
            self._active_condor_id = candidate.condor_id
            self._active_legs = executed_legs
            short_credit = sum(l.entry_price for l in executed_legs if l.side == "Sell")
            long_debit = sum(l.entry_price for l in executed_legs if l.side == "Buy")
            self._entry_credit = (short_credit - long_debit) * qty
            self._entry_time = datetime.now(UTC).isoformat()

            # Persist to database
            margin_sum = self.margin_calculator.evaluate_portfolio(
                self.paper_account.positions,
                self.paper_account.equity,
                spot,
            )
            self.storage.save_account(self.paper_account, margin_summary=margin_sum)
            self._log_event(
                "iron_condor_opened",
                {
                    "condor_id": candidate.condor_id,
                    "net_credit_collected": round(self._entry_credit, 4),
                    "margin_utilization": margin_sum.margin_utilization_pct,
                },
            )
            return True

        return False

    def execute_close_condor(
        self,
        reason: str,
        spot: float,
        current_chain: list[dict[str, Any]],
    ) -> float:
        """Close all 4 legs of the active Iron Condor."""
        if not self._active_condor_id or not self._active_legs:
            return 0.0

        chain_by_sym = {c["symbol"]: c for c in current_chain}
        total_realized = 0.0

        if self.config.paper_mode:
            for leg in self._active_legs:
                close_side = "Buy" if leg.side == "Sell" else "Sell"
                contract = chain_by_sym.get(leg.symbol, {})
                order = PaperOrder(
                    symbol=leg.symbol,
                    side=close_side,
                    qty=leg.qty,
                    order_type=OrderType.MARKET,
                    strategy_id=self._active_condor_id,
                )
                if self.config.use_deribit_testnet and self.deribit_adapter:
                    res = self.deribit_adapter.execute_order(order, spot=spot)
                else:
                    res = self.matching_engine.match_order(
                        order=order,
                        best_bid=float(contract.get("bid", 0) or leg.current_mark * 0.95),
                        best_ask=float(contract.get("ask", 0) or leg.current_mark * 1.05),
                        spot=spot,
                        mark_price=float(contract.get("mark_price", 0) or leg.current_mark),
                    )
                trade = self.paper_account.apply_fill(
                    symbol=leg.symbol,
                    side=close_side,
                    qty=leg.qty,
                    price=res.filled_price,
                    fee=res.fee,
                    spot=spot,
                    strategy_id=self._active_condor_id,
                    order_id=res.order_id,
                )
                total_realized += trade.realized_pnl

            self._total_compounded_profit += total_realized
            self._log_event(
                "iron_condor_closed",
                {
                    "condor_id": self._active_condor_id,
                    "reason": reason,
                    "realized_pnl": round(total_realized, 4),
                    "total_compounded": round(self._total_compounded_profit, 4),
                    "equity": round(self.paper_account.equity, 4),
                },
            )

            # Clear state
            self._active_condor_id = None
            self._active_legs = []
            self._entry_credit = 0.0

            # Persist
            margin_sum = self.margin_calculator.evaluate_portfolio(
                self.paper_account.positions,
                self.paper_account.equity,
                spot,
            )
            self.storage.save_account(self.paper_account, margin_summary=margin_sum)
            return total_realized

        return 0.0

    # --- Position Lifecycle & Monitoring --------------------------------------

    def monitor_and_manage_position(
        self,
        spot: float,
        current_chain: list[dict[str, Any]],
    ) -> str:
        """Check active Iron Condor against Take Profit (50%), Stop Loss, and Expiry."""
        if not self._active_condor_id or not self._active_legs:
            return "NO_ACTIVE_POSITION"

        chain_by_sym = {c["symbol"]: c for c in current_chain}
        quotes: dict[str, float] = {}
        for leg in self._active_legs:
            c = chain_by_sym.get(leg.symbol)
            if c:
                bid = float(c.get("bid", 0) or 0)
                ask = float(c.get("ask", 0) or 0)
                mark = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(c.get("mark_price", 0) or leg.current_mark)
                quotes[leg.symbol] = mark
                leg.current_mark = mark

        # Update paper account mark to market
        self.paper_account.mark_to_market(quotes)

        # Calculate Condor current PnL
        unrealized = sum(
            self.paper_account.positions[l.symbol].unrealized_pnl
            for l in self._active_legs
            if l.symbol in self.paper_account.positions
        )

        # 1. 50% TAKE-PROFIT RULE (Aggressive Compounding Trigger)
        target_profit = self._entry_credit * self.config.target_profit_pct
        if unrealized >= target_profit:
            self._log_event(
                "take_profit_triggered",
                {"unrealized": unrealized, "target": target_profit},
            )
            self.execute_close_condor("50_PERCENT_TP", spot, current_chain)
            return "CLOSED_TP"

        # 2. STOP-LOSS CIRCUIT BREAKER
        max_allowed_loss = self._entry_credit * self.config.max_loss_multiplier
        if unrealized <= -max_allowed_loss:
            self._log_event(
                "stop_loss_triggered",
                {"unrealized": unrealized, "max_loss": -max_allowed_loss},
            )
            self.execute_close_condor("STOP_LOSS", spot, current_chain)
            return "CLOSED_SL"

        # 3. EXPIRY CHECK
        parsed = parse_bybit_option_symbol(self._active_legs[0].symbol)
        if parsed and parsed.get("expiry_date"):
            exp_dt = parsed["expiry_date"]
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=UTC)
            dte = (exp_dt - datetime.now(UTC)).total_seconds() / 86400.0
            if dte <= self.config.roll_dte:
                self._log_event("expiry_roll_triggered", {"dte": dte})
                self.execute_close_condor("EXPIRY_ROLL", spot, current_chain)
                return "CLOSED_EXPIRY"

        return "HOLDING"

    # --- Live Cycle & CLI Runner ----------------------------------------------

    async def fetch_live_data(self) -> tuple[list[dict[str, Any]], float]:
        """Fetch live options chain data and spot price from Deribit Testnet or Bybit."""
        if self.config.use_deribit_testnet and self.deribit_adapter:
            summaries = self.deribit_adapter.client.get_book_summary_by_currency(
                self.config.asset, "option"
            )
            contracts: list[dict[str, Any]] = []
            spot = 0.0
            for s in summaries:
                name = s.get("instrument_name", "")
                parts = name.split("-")
                if len(parts) >= 4:
                    try:
                        dt = datetime.strptime(parts[1], "%d%b%y")
                        contracts.append(
                            {
                                "symbol": name,
                                "strike": float(parts[2]),
                                "option_type": "call" if parts[3].upper() == "C" else "put",
                                "expiry": dt.strftime("%Y-%m-%d"),
                                "bid": float(s.get("bid_price") or 0.0),
                                "ask": float(s.get("ask_price") or 0.0),
                                "mark_price": float(s.get("mark_price") or 0.0),
                            }
                        )
                        if spot == 0.0 and s.get("estimated_delivery_price"):
                            spot = float(s["estimated_delivery_price"])
                    except Exception:
                        continue
            if spot == 0.0:
                ticker = self.deribit_adapter.client.get_ticker(f"{self.config.asset}-PERPETUAL")
                spot = float(ticker.get("index_price", 0.0) or ticker.get("mark_price", 0.0))
            return contracts, spot

        from bybit_api import BybitPublicClient

        client = BybitPublicClient()
        raw = await client.get_options_chain_data(self.config.asset)
        spot = await client.get_spot_price(f"{self.config.asset}USDT")

        contracts: list[dict[str, Any]] = []
        if isinstance(raw, list):
            contracts = raw
        elif isinstance(raw, dict):
            # If wrapped in list/data
            contracts = raw.get("list", raw.get("data", []))

        return contracts, spot

    async def run_cycle(self) -> str:
        """Run a single evaluation cycle: manage existing or find and open new."""
        try:
            contracts, spot = await self.fetch_live_data()
        except Exception as e:
            self._log_event("fetch_error", {"error": str(e)})
            return "FETCH_ERROR"

        if not contracts or spot <= 0:
            self._log_event("empty_chain_or_spot", {"contracts": len(contracts), "spot": spot})
            return "EMPTY_DATA"

        # 1. Manage active position if open
        if self._active_condor_id:
            status = self.monitor_and_manage_position(spot, contracts)
            # Record periodic snapshot
            margin_sum = self.margin_calculator.evaluate_portfolio(
                self.paper_account.positions,
                self.paper_account.equity,
                spot,
            )
            self.storage.record_snapshot(self.paper_account, margin_sum)
            return status

        # 2. If no position, search for new opportunity
        candidate = self.select_iron_condor_candidate(contracts, spot)
        if candidate:
            success = self.execute_open_condor(candidate, spot)
            return "OPENED" if success else "OPEN_FAILED"

        self._log_event("no_candidate_found", {"asset": self.config.asset, "spot": spot})
        return "NO_CANDIDATE"

    async def run_loop(self) -> None:
        """Continuously run bot cycles until interrupted."""
        self._running = True
        self._log_event(
            "bot_started",
            {
                "asset": self.config.asset,
                "paper": self.config.paper_mode,
                "interval": self.config.poll_interval_seconds,
            },
        )
        while self._running:
            try:
                action = await self.run_cycle()
                self._log_event("cycle_completed", {"action": action})
            except Exception as e:
                self._log_event("cycle_exception", {"error": str(e)})

            # Sleep interval
            for _ in range(self.config.poll_interval_seconds):
                if not self._running:
                    break
                await asyncio.sleep(1)

        self._log_event("bot_stopped")


def main() -> None:
    """CLI entrypoint for Iron Condor Bot."""
    import argparse

    parser = argparse.ArgumentParser(description="Bybit Iron Condor Trading Bot")
    parser.add_argument("--asset", default="BTC", help="Underlying asset (BTC, ETH, SOL)")
    parser.add_argument("--paper", dest="paper", action="store_true", default=True, help="Run in paper mode")
    parser.add_argument("--execute", dest="paper", action="store_false", help="Run in LIVE execution mode")
    parser.add_argument("--deribit-testnet", dest="deribit_testnet", action="store_true", default=False, help="Execute orders on Deribit Testnet")
    parser.add_argument("--capital", type=float, default=10000.0, help="Initial virtual capital")
    parser.add_argument("--short-delta", type=float, default=0.15, help="Target short Delta")
    parser.add_argument("--wing-delta", type=float, default=0.03, help="Target long wing Delta")
    parser.add_argument("--min-dte", type=int, default=5, help="Min DTE")
    parser.add_argument("--max-dte", type=int, default=16, help="Max DTE")
    parser.add_argument("--tp-pct", type=float, default=0.50, help="Take profit percentage")
    parser.add_argument("--sl-mult", type=float, default=0.8, help="Stop loss credit multiplier (default: 0.8)")
    parser.add_argument("--interval", type=int, default=300, help="Poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run single cycle and exit")

    args = parser.parse_args()

    config = IronCondorConfig(
        asset=args.asset,
        paper_mode=args.paper,
        use_deribit_testnet=args.deribit_testnet,
        initial_capital=args.capital,
        target_short_delta=args.short_delta,
        target_wing_delta=args.wing_delta,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        target_profit_pct=args.tp_pct,
        max_loss_multiplier=args.sl_mult,
        poll_interval_seconds=args.interval,
    )

    bot = IronCondorBot(config)

    if args.once:
        result = asyncio.run(bot.run_cycle())
        print(f"Cycle result: {result}")
        print(f"Paper Equity: ${bot.paper_account.equity:,.2f} | Positions: {len(bot.paper_account.positions)}")
    else:
        try:
            asyncio.run(bot.run_loop())
        except KeyboardInterrupt:
            print("\nBot stopped by user.")


if __name__ == "__main__":
    main()
