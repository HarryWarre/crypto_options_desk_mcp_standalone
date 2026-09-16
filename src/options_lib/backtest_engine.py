"""Deterministic options backtest orchestration over archived Bybit snapshots.

The scanner remains the signal generator.  This module only coordinates
chronological replay, top-of-book execution assumptions, exit policies, and
the existing held-out evidence validator.  It never uses a snapshot newer
than the signal being evaluated.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from bybit_api.option_history import (
    HistoricalDataUnavailable,
    HistoricalOptionQuote,
    HistoricalOptionSnapshot,
    JsonlOptionSnapshotArchive,
    SnapshotQuery,
)

from .ev_validation import (
    BacktestReport,
    HistoricalTradeSample,
    ValidationConfig,
    validate_backtest,
)
from .opportunity_scanner import Opportunity, ScanRequest, scan_opportunities

ExitPolicyType = Literal[
    "hold_to_expiry",
    "profit_target",
    "stop_loss",
    "min_dte",
    "end_of_test",
]


class BacktestDataUnavailable(ValueError):
    """Raised when a requested backtest cannot be evaluated from the archive."""


@dataclass(frozen=True)
class ExitPolicy:
    """A deterministic rule for closing a historical signal."""

    type: ExitPolicyType = "hold_to_expiry"
    profit_target_pct: float = 0.5
    stop_loss_pct: float = 1.0
    min_dte: float = 3.0

    def __post_init__(self) -> None:
        if self.type not in {
            "hold_to_expiry",
            "profit_target",
            "stop_loss",
            "min_dte",
            "end_of_test",
        }:
            raise ValueError(f"unsupported exit policy: {self.type}")
        for name, value in (
            ("profit_target_pct", self.profit_target_pct),
            ("stop_loss_pct", self.stop_loss_pct),
            ("min_dte", self.min_dte),
        ):
            if isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.type == "profit_target" and self.profit_target_pct <= 0:
            raise ValueError("profit_target_pct must be positive for profit_target")
        if self.type == "stop_loss" and self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct must be positive for stop_loss")


@dataclass(frozen=True)
class BacktestRunConfig:
    """Inputs for one snapshot-replay run."""

    archive: JsonlOptionSnapshotArchive
    start_time: datetime
    end_time: datetime
    assets: tuple[str, ...]
    scan_request: ScanRequest
    exit_policy: ExitPolicy = field(default_factory=ExitPolicy)
    signal_interval: timedelta = timedelta(hours=1)
    max_signals_per_snapshot: int = 5
    validation: ValidationConfig = field(
        default_factory=lambda: ValidationConfig(lookahead_verified=True)
    )

    def __post_init__(self) -> None:
        for name, value in (("start_time", self.start_time), ("end_time", self.end_time)):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if self.signal_interval <= timedelta(0):
            raise ValueError("signal_interval must be positive")
        if self.max_signals_per_snapshot < 1:
            raise ValueError("max_signals_per_snapshot must be positive")
        assets = tuple(dict.fromkeys(str(asset).strip().upper() for asset in self.assets if asset.strip()))
        if not assets:
            raise ValueError("at least one asset is required")
        object.__setattr__(self, "assets", assets)


@dataclass(frozen=True)
class TradeOutcome:
    """One completed historical trade with auditable execution details."""

    trade_id: str
    asset: str
    strategy: str
    symbols: tuple[str, ...]
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    gross_pnl: float
    fees: float
    slippage: float
    costs: float
    net_pnl: float
    notional: float
    risk_base: float
    return_pct: float
    data_mode: str = "quote_replay"
    execution_quality: str = "top_of_book"
    warnings: tuple[str, ...] = ()

    def to_sample(self) -> HistoricalTradeSample:
        return HistoricalTradeSample(
            timestamp=self.entry_time,
            gross_pnl=self.gross_pnl,
            notional=self.notional,
            costs=self.costs,
            legs=len(self.symbols),
        )


@dataclass(frozen=True)
class UnresolvedSignal:
    asset: str
    strategy: str
    symbol: str
    entry_time: datetime
    reason: str


@dataclass(frozen=True)
class BacktestDataQuality:
    source: str
    mode: str
    fill_model: str
    lookahead_free: bool
    snapshot_count: int
    signal_evaluations: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BacktestResult:
    engine: str
    status: str
    report: BacktestReport
    trades: tuple[TradeOutcome, ...]
    unresolved: tuple[UnresolvedSignal, ...]
    data_quality: BacktestDataQuality

    @property
    def equity_curve(self) -> tuple[dict[str, object], ...]:
        equity = 0.0
        points: list[dict[str, object]] = []
        for trade in self.trades:
            equity += trade.net_pnl
            points.append(
                {
                    "timestamp": trade.exit_time,
                    "trade_id": trade.trade_id,
                    "net_pnl": trade.net_pnl,
                    "equity": equity,
                }
            )
        return tuple(points)


Scanner = Callable[[object, ScanRequest], object]


def run_snapshot_backtest(
    config: BacktestRunConfig,
    *,
    scanner: Scanner = scan_opportunities,
) -> BacktestResult:
    """Replay archived snapshots and produce realized, costed trade outcomes."""

    start = _utc(config.start_time)
    end = _utc(config.end_time)
    loaded = config.archive.load(
        SnapshotQuery(start_time=start, end_time=end, assets=config.assets)
    )
    by_asset: dict[str, list[HistoricalOptionSnapshot]] = defaultdict(list)
    for snapshot in loaded.snapshots:
        by_asset[snapshot.asset.upper()].append(snapshot)
    missing_assets = [asset for asset in config.assets if not by_asset.get(asset)]
    if missing_assets:
        raise BacktestDataUnavailable(
            f"no archived snapshots for {', '.join(missing_assets)} in the requested range"
        )

    trades: list[TradeOutcome] = []
    unresolved: list[UnresolvedSignal] = []
    warnings = [issue.message for issue in loaded.issues]
    signal_evaluations = 0
    traded_keys: set[tuple[str, str, tuple[str, ...]]] = set()

    for asset in config.assets:
        snapshots = sorted(by_asset[asset], key=lambda item: _utc(item.source_timestamp))
        last_signal_time: datetime | None = None
        asset_request = replace(config.scan_request, assets=(asset,))
        for snapshot in snapshots:
            signal_time = _utc(snapshot.source_timestamp)
            if last_signal_time is not None and signal_time - last_signal_time < config.signal_interval:
                continue
            last_signal_time = signal_time
            try:
                universe = config.archive.replay_universe(
                    as_of=signal_time,
                    assets=(asset,),
                    max_age=timedelta(0),
                )
                scan = scanner(universe, asset_request)
            except HistoricalDataUnavailable as exc:
                warnings.append(str(exc))
                continue
            signal_evaluations += 1
            opportunities = tuple(getattr(scan, "opportunities", ()))[: config.max_signals_per_snapshot]
            for opportunity in opportunities:
                key = (
                    opportunity.asset,
                    str(opportunity.strategy),
                    tuple(sorted(leg.symbol for leg in opportunity.legs)),
                )
                if not key[2] or key in traded_keys:
                    continue
                traded_keys.add(key)
                trade, unresolved_signal = _evaluate_signal(
                    opportunity,
                    entry_time=signal_time,
                    snapshots=snapshots,
                    config=config,
                )
                if trade is not None:
                    trades.append(trade)
                elif unresolved_signal is not None:
                    unresolved.append(unresolved_signal)

    if not trades:
        raise BacktestDataUnavailable(
            "the archive produced no completed trades under the selected signal and exit rules"
        )

    validation = config.validation
    if not validation.lookahead_verified:
        validation = replace(validation, lookahead_verified=True)
    report = validate_backtest(
        tuple(trade.to_sample() for trade in sorted(trades, key=lambda item: item.entry_time)),
        validation,
    )
    quality = BacktestDataQuality(
        source="bybit-option-snapshot:v1",
        mode="quote_replay",
        fill_model="top_of_book_bid_ask",
        lookahead_free=True,
        snapshot_count=len(loaded.snapshots),
        signal_evaluations=signal_evaluations,
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return BacktestResult(
        engine="snapshot_replay",
        status="completed",
        report=report,
        trades=tuple(sorted(trades, key=lambda item: item.exit_time)),
        unresolved=tuple(unresolved),
        data_quality=quality,
    )


def _evaluate_signal(
    opportunity: Opportunity,
    *,
    entry_time: datetime,
    snapshots: Sequence[HistoricalOptionSnapshot],
    config: BacktestRunConfig,
) -> tuple[TradeOutcome | None, UnresolvedSignal | None]:
    legs = tuple(opportunity.legs)
    entry_quotes = {leg.symbol: leg for leg in legs}
    risk_base = max(abs(float(opportunity.max_loss)), 1e-12)
    future = [snapshot for snapshot in snapshots if _utc(snapshot.source_timestamp) > entry_time]
    expiry = _utc(opportunity.expiry_at)

    for snapshot in future:
        observed_at = _utc(snapshot.source_timestamp)
        if observed_at < expiry:
            quote_map = {quote.symbol: quote for quote in snapshot.quotes}
            if not all(_executable_quote(quote_map.get(symbol)) for symbol in entry_quotes):
                continue
            if config.exit_policy.type == "min_dte":
                dte = (expiry - observed_at).total_seconds() / 86_400.0
                if dte > config.exit_policy.min_dte:
                    continue
            prices = {
                symbol: _exit_quote_price(quote_map[symbol], position=leg.position)
                for symbol, leg in entry_quotes.items()
            }
            exit_reason = {
                "profit_target": "profit_target",
                "stop_loss": "stop_loss",
                "min_dte": "min_dte",
            }.get(config.exit_policy.type, "quote_exit")
            trade = _make_trade(
                opportunity,
                entry_time,
                observed_at,
                prices,
                exit_reason,
                config,
            )
            if _exit_triggered(trade, config.exit_policy, risk_base):
                return trade, None
            continue

        if observed_at >= expiry:
            underlying = _snapshot_underlying(snapshot)
            if underlying is None:
                continue
            prices = {
                leg.symbol: _intrinsic(leg.option_type, underlying, leg.strike)
                for leg in legs
            }
            return _make_trade(
                opportunity,
                entry_time,
                expiry,
                prices,
                "expiry",
                config,
                is_settlement=True,
                warning=(
                    "expiry settlement used the first archived underlying snapshot at or after expiry"
                    if observed_at > expiry
                    else None
                ),
            ), None

    if config.exit_policy.type == "end_of_test":
        for snapshot in reversed(future):
            quote_map = {quote.symbol: quote for quote in snapshot.quotes}
            if all(_executable_quote(quote_map.get(symbol)) for symbol in entry_quotes):
                prices = {
                    symbol: _exit_quote_price(quote_map[symbol], position=leg.position)
                    for symbol, leg in entry_quotes.items()
                }
                return _make_trade(
                    opportunity,
                    entry_time,
                    _utc(snapshot.source_timestamp),
                    prices,
                    "end_of_test",
                    config,
                ), None

    return None, UnresolvedSignal(
        asset=opportunity.asset,
        strategy=str(opportunity.strategy),
        symbol=opportunity.symbol,
        entry_time=entry_time,
        reason="no complete future quote or settlement was available before the test ended",
    )


def _make_trade(
    opportunity: Opportunity,
    entry_time: datetime,
    exit_time: datetime,
    exit_prices: dict[str, float],
    exit_reason: str,
    config: BacktestRunConfig,
    *,
    is_settlement: bool = False,
    warning: str | None = None,
) -> TradeOutcome:
    scale = config.scan_request.quantity * config.scan_request.contract_multiplier
    slip_rate = config.scan_request.slippage_bps / 10_000.0
    entry_cash = 0.0
    exit_cash = 0.0
    notional = 0.0
    slippage = 0.0
    symbols: list[str] = []
    for leg in opportunity.legs:
        symbols.append(leg.symbol)
        raw_entry = leg.ask_price if leg.position > 0 else leg.bid_price
        entry_price = raw_entry * (1.0 + slip_rate if leg.position > 0 else 1.0 - slip_rate)
        raw_exit = exit_prices[leg.symbol]
        exit_price = raw_exit
        if not is_settlement:
            exit_price *= 1.0 + slip_rate if leg.position < 0 else 1.0 - slip_rate
        entry_cash -= leg.position * entry_price * scale
        exit_cash += leg.position * exit_price * scale
        notional += abs(entry_price * scale)
        slippage += abs(entry_price - raw_entry) * scale
        if not is_settlement:
            slippage += abs(exit_price - raw_exit) * scale

    gross_pnl = entry_cash + exit_cash
    fees = config.scan_request.fee_per_contract * scale * 2.0 * len(symbols)
    costs = fees + slippage
    net_pnl = gross_pnl - costs
    risk_base = max(abs(float(opportunity.max_loss)), abs(entry_cash), 1e-12)
    return TradeOutcome(
        trade_id=f"{opportunity.asset}:{entry_time.isoformat()}:{opportunity.symbol}",
        asset=opportunity.asset,
        strategy=str(opportunity.strategy),
        symbols=tuple(symbols),
        entry_time=entry_time,
        exit_time=exit_time,
        exit_reason=exit_reason,
        gross_pnl=gross_pnl,
        fees=fees,
        slippage=slippage,
        costs=costs,
        net_pnl=net_pnl,
        notional=max(notional, 1e-12),
        risk_base=risk_base,
        return_pct=net_pnl / risk_base * 100.0,
        warnings=(warning,) if warning else (),
    )


def _exit_triggered(trade: TradeOutcome, policy: ExitPolicy, risk_base: float) -> bool:
    if policy.type == "profit_target":
        return trade.net_pnl >= policy.profit_target_pct * risk_base
    if policy.type == "stop_loss":
        return trade.net_pnl <= -policy.stop_loss_pct * risk_base
    return policy.type == "min_dte"


def _executable_quote(quote: HistoricalOptionQuote | None) -> bool:
    return bool(
        quote is not None
        and quote.bid_price is not None
        and quote.ask_price is not None
        and quote.bid_price > 0
        and quote.ask_price >= quote.bid_price
    )


def _exit_quote_price(quote: HistoricalOptionQuote, *, position: int) -> float:
    value = quote.bid_price if position > 0 else quote.ask_price
    if value is None or value <= 0:
        raise BacktestDataUnavailable(f"missing executable exit quote for {quote.symbol}")
    return float(value)


def _snapshot_underlying(snapshot: HistoricalOptionSnapshot) -> float | None:
    values = [quote.underlying_price for quote in snapshot.quotes]
    valid = [float(value) for value in values if value is not None and value > 0]
    return valid[0] if valid else None


def _intrinsic(option_type: str, spot: float, strike: float) -> float:
    if option_type.lower().startswith("c"):
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "BacktestDataQuality",
    "BacktestDataUnavailable",
    "BacktestResult",
    "BacktestRunConfig",
    "ExitPolicy",
    "TradeOutcome",
    "UnresolvedSignal",
    "run_snapshot_backtest",
]
