"""Build chronological, costed examples for the strategy-selection head.

The builder replays the existing snapshot archive at each signal time.  The
scanner remains the only producer of candidate strategies; this module only
turns those candidates and their later archived observations into typed
training records.  It never uses a snapshot newer than the record's
``source_timestamp`` for its features and never places orders.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Literal

from bybit_api.option_history import (
    HistoricalDataUnavailable,
    HistoricalOptionQuote,
    HistoricalOptionSnapshot,
    JsonlOptionSnapshotArchive,
    SnapshotQuery,
)
from bybit_api.options_market_data import NormalizedOptionUniverse, OptionDataQualityIssue
from options_lib.backtest_engine import ExitPolicy
from options_lib.opportunity_scanner import (
    Opportunity,
    ScanRequest,
    ScanResult,
    scan_opportunities,
)

OutcomeLabel = Literal["PROFIT", "LOSS", "NO_TRADE"]
StrategyScanner = Callable[[NormalizedOptionUniverse, ScanRequest], ScanResult]


@dataclass(frozen=True)
class AsOfFeatures:
    """Numeric features calculated from one historical snapshot only."""

    asset: str
    source_timestamp: datetime
    retrieval_timestamp: datetime
    values: tuple[tuple[str, float], ...]
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, float]:
        """Return a LightGBM-friendly numeric feature mapping."""

        return dict(self.values)


@dataclass(frozen=True)
class AfterCostOutcome:
    """One replayed result after fees and slippage."""

    label: Literal["PROFIT", "LOSS"]
    gross_pnl: float
    costs: float
    net_pnl: float
    return_pct: float
    notional: float
    risk_base: float
    outcome_timestamp: datetime
    observation_timestamp: datetime
    exit_reason: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyHeadRecord:
    """One as-of row for one asset and one strategy family."""

    source_timestamp: datetime
    retrieval_timestamp: datetime
    asset: str
    strategy: str
    source: str
    features: tuple[tuple[str, float], ...]
    outcome_label: OutcomeLabel | None = None
    gross_pnl: float | None = None
    costs: float | None = None
    net_pnl: float | None = None
    return_pct: float | None = None
    notional: float | None = None
    risk_base: float | None = None
    outcome_timestamp: datetime | None = None
    outcome_source_timestamp: datetime | None = None
    exit_reason: str | None = None
    candidate_symbols: tuple[str, ...] = ()
    data_quality_warnings: tuple[str, ...] = ()
    proxy_warnings: tuple[str, ...] = ()
    scan_rejection_reasons: tuple[str, ...] = ()
    excluded_reasons: tuple[str, ...] = ()
    included: bool = False


@dataclass(frozen=True)
class DatasetQuality:
    """Dataset-level provenance and quality summary."""

    sources: tuple[str, ...]
    source_timestamps: tuple[datetime, ...]
    snapshot_count: int
    record_count: int
    included_count: int
    excluded_count: int
    lookahead_free: bool
    warnings: tuple[str, ...] = ()
    proxy_warnings: tuple[str, ...] = ()
    excluded_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyHeadDataset:
    """Immutable dataset plus the quality evidence needed by later training."""

    rows: tuple[StrategyHeadRecord, ...]
    quality: DatasetQuality

    @property
    def training_rows(self) -> tuple[StrategyHeadRecord, ...]:
        """Rows with a usable label; excluded rows remain available for audit."""

        return tuple(row for row in self.rows if row.included and row.outcome_label is not None)


@dataclass(frozen=True)
class StrategyHeadDatasetConfig:
    """Inputs for one deterministic chronological dataset build."""

    archive: JsonlOptionSnapshotArchive
    start_time: datetime
    end_time: datetime
    assets: tuple[str, ...]
    scan_request: ScanRequest
    strategy_families: tuple[str, ...] | None = None
    exit_policy: ExitPolicy = field(default_factory=ExitPolicy)
    signal_interval: timedelta = timedelta(hours=1)
    max_opportunities_per_strategy: int = 1

    def __post_init__(self) -> None:
        for name, value in (("start_time", self.start_time), ("end_time", self.end_time)):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.start_time > self.end_time:
            raise ValueError("start_time must not be after end_time")
        if self.signal_interval <= timedelta(0):
            raise ValueError("signal_interval must be positive")
        if (
            isinstance(self.max_opportunities_per_strategy, bool)
            or self.max_opportunities_per_strategy < 1
        ):
            raise ValueError("max_opportunities_per_strategy must be positive")
        if not isinstance(self.exit_policy, ExitPolicy):
            raise TypeError("exit_policy must be an ExitPolicy")
        if self.scan_request.valuation_mode != "executable":
            raise ValueError("strategy-head labels require executable valuation mode")

        assets = tuple(
            dict.fromkeys(str(asset).strip().upper() for asset in self.assets if str(asset).strip())
        )
        if not assets:
            raise ValueError("at least one asset is required")
        strategies = self.strategy_families or self.scan_request.strategies
        strategies = tuple(
            dict.fromkeys(
                str(strategy).strip().lower() for strategy in strategies if str(strategy).strip()
            )
        )
        if not strategies:
            raise ValueError("at least one strategy family is required")
        # Reuse ScanRequest's existing validation and supported-strategy list
        # without changing that shared scanner contract.
        for strategy in strategies:
            replace(self.scan_request, strategies=(strategy,))
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "strategy_families", strategies)


def extract_asof_features(snapshot: HistoricalOptionSnapshot) -> AsOfFeatures:
    """Extract numeric features from exactly one snapshot.

    No archive lookup, future observation, or outcome field is consulted here.
    Missing aggregates are represented as ``0.0`` and called out in warnings
    so a later model adapter can choose a stricter missing-value policy.
    """

    if not isinstance(snapshot, HistoricalOptionSnapshot):
        raise TypeError("snapshot must be a HistoricalOptionSnapshot")
    as_of = _utc(snapshot.source_timestamp)
    quotes = tuple(snapshot.quotes)
    underlying = _valid_values(quotes, "underlying_price", positive=True)
    mark_ivs = _valid_values(quotes, "mark_iv", positive=True)
    abs_deltas = [abs(value) for value in _valid_values(quotes, "delta")]
    volumes = _valid_values(quotes, "volume_24h", non_negative=True)
    open_interest = _valid_values(quotes, "open_interest", non_negative=True)
    spreads = [
        (float(quote.ask_price) - float(quote.bid_price))
        / max((float(quote.ask_price) + float(quote.bid_price)) / 2.0, 1e-12)
        for quote in quotes
        if _executable_quote(quote)
    ]
    dtes = [
        max(0.0, (quote.expiry_at - as_of).total_seconds() / 86_400.0)
        for quote in quotes
        if quote.expiry_at.tzinfo is not None and quote.expiry_at > as_of
    ]
    complete_quotes = [
        quote
        for quote in quotes
        if all(
            getattr(quote, field_name) is not None
            for field_name in (
                "underlying_price",
                "mark_iv",
                "delta",
                "volume_24h",
                "open_interest",
            )
        )
    ]
    warnings: list[str] = []
    for name, values in (
        ("underlying_price", underlying),
        ("mark_iv", mark_ivs),
        ("delta", abs_deltas),
        ("volume_24h", volumes),
        ("open_interest", open_interest),
        ("spread", spreads),
        ("dte", dtes),
    ):
        if not values:
            warnings.append(f"missing_feature_values:{name}")
    if not quotes:
        warnings.append("empty_snapshot")
    if snapshot.retrieval_timestamp < snapshot.source_timestamp:
        warnings.append("retrieval_before_source_timestamp")

    values = (
        ("underlying_price", _median_or_zero(underlying)),
        ("quote_count", float(len(quotes))),
        ("complete_quote_count", float(len(complete_quotes))),
        ("executable_quote_count", float(sum(_executable_quote(quote) for quote in quotes))),
        ("expiry_count", float(len({quote.expiry_at for quote in quotes}))),
        ("mean_mark_iv", _mean_or_zero(mark_ivs)),
        ("mean_abs_delta", _mean_or_zero(abs_deltas)),
        ("mean_volume_24h", _mean_or_zero(volumes)),
        ("mean_open_interest", _mean_or_zero(open_interest)),
        ("mean_spread_pct", _mean_or_zero(spreads)),
        ("mean_dte_days", _mean_or_zero(dtes)),
        ("min_dte_days", min(dtes, default=0.0)),
        ("max_dte_days", max(dtes, default=0.0)),
    )
    return AsOfFeatures(
        asset=snapshot.asset.upper(),
        source_timestamp=as_of,
        retrieval_timestamp=_utc(snapshot.retrieval_timestamp),
        values=values,
        warnings=tuple(warnings),
    )


def build_strategy_head_dataset(
    config: StrategyHeadDatasetConfig,
    *,
    scanner: StrategyScanner = scan_opportunities,
) -> StrategyHeadDataset:
    """Build one chronological row per snapshot, asset, and strategy family."""

    if not isinstance(config, StrategyHeadDatasetConfig):
        raise TypeError("config must be a StrategyHeadDatasetConfig")
    loaded = config.archive.load(
        SnapshotQuery(
            start_time=_utc(config.start_time),
            end_time=_utc(config.end_time),
            assets=config.assets,
        )
    )
    snapshots_by_asset: dict[str, list[HistoricalOptionSnapshot]] = defaultdict(list)
    for snapshot in loaded.snapshots:
        snapshots_by_asset[snapshot.asset.upper()].append(snapshot)
    for snapshots in snapshots_by_asset.values():
        snapshots.sort(key=lambda item: _utc(item.source_timestamp))

    rows: list[StrategyHeadRecord] = []
    dataset_warnings = [_format_issue(issue) for issue in loaded.issues]
    dataset_proxy_warnings: list[str] = []
    all_excluded_reasons: list[str] = []
    sources = tuple(dict.fromkeys(snapshot.source for snapshot in loaded.snapshots))
    source_timestamps = tuple(_utc(snapshot.source_timestamp) for snapshot in loaded.snapshots)

    for asset in config.assets:
        snapshots = snapshots_by_asset.get(asset, [])
        last_signal_time: datetime | None = None
        for snapshot in snapshots:
            signal_time = _utc(snapshot.source_timestamp)
            if (
                last_signal_time is not None
                and signal_time - last_signal_time < config.signal_interval
            ):
                continue
            last_signal_time = signal_time
            features = extract_asof_features(snapshot)
            asof_warnings = _unique(
                tuple(features.warnings) + tuple(_format_issue(issue) for issue in snapshot.issues)
            )
            asof_proxy_warnings = _proxy_warnings(snapshot)
            dataset_warnings.extend(asof_warnings)
            dataset_proxy_warnings.extend(asof_proxy_warnings)

            for strategy in config.strategy_families or ():
                row = _build_strategy_record(
                    config,
                    scanner,
                    asset,
                    strategy,
                    snapshot,
                    snapshots,
                    features,
                    asof_warnings,
                    asof_proxy_warnings,
                )
                rows.append(row)
                all_excluded_reasons.extend(row.excluded_reasons)
                dataset_warnings.extend(row.data_quality_warnings)
                dataset_proxy_warnings.extend(row.proxy_warnings)

    rows.sort(key=lambda row: (row.source_timestamp, row.asset, row.strategy))
    quality = DatasetQuality(
        sources=tuple(sources),
        source_timestamps=tuple(sorted(set(source_timestamps))),
        snapshot_count=len(loaded.snapshots),
        record_count=len(rows),
        included_count=sum(row.included for row in rows),
        excluded_count=sum(not row.included for row in rows),
        lookahead_free=True,
        warnings=_unique(tuple(dataset_warnings)),
        proxy_warnings=_unique(tuple(dataset_proxy_warnings)),
        excluded_reasons=_unique(tuple(all_excluded_reasons)),
    )
    return StrategyHeadDataset(rows=tuple(rows), quality=quality)


def _build_strategy_record(
    config: StrategyHeadDatasetConfig,
    scanner: StrategyScanner,
    asset: str,
    strategy: str,
    snapshot: HistoricalOptionSnapshot,
    snapshots: Sequence[HistoricalOptionSnapshot],
    features: AsOfFeatures,
    asof_warnings: tuple[str, ...],
    asof_proxy_warnings: tuple[str, ...],
) -> StrategyHeadRecord:
    common = {
        "source_timestamp": features.source_timestamp,
        "retrieval_timestamp": features.retrieval_timestamp,
        "asset": asset,
        "strategy": strategy,
        "source": snapshot.source,
        "features": features.values,
        "data_quality_warnings": asof_warnings,
        "proxy_warnings": asof_proxy_warnings,
    }
    try:
        universe = config.archive.replay_universe(
            as_of=features.source_timestamp,
            assets=(asset,),
            max_age=timedelta(0),
        )
    except HistoricalDataUnavailable as exc:
        return StrategyHeadRecord(
            **common,
            excluded_reasons=(f"as_of_data_unavailable:{exc}",),
        )

    request = replace(
        config.scan_request,
        assets=(asset,),
        strategies=(strategy,),
        max_results=config.max_opportunities_per_strategy,
    )
    try:
        scan = scanner(universe, request)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        # Scanner failures are data exclusions, not crashes in a batch.
        return StrategyHeadRecord(
            **common,
            excluded_reasons=(f"scanner_failed:{type(exc).__name__}",),
        )

    scan_warnings = tuple(_format_issue(issue) for issue in scan.issues)
    replay_warnings = tuple(_format_issue(issue) for issue in universe.issues)
    failure_reasons = tuple(
        f"asset_scan_failed:{failure.code}"
        for failure in scan.asset_failures
        if failure.asset.upper() == asset
    )
    candidate_rejections = _rejection_reasons(scan, strategy)
    common["data_quality_warnings"] = _unique(asof_warnings + replay_warnings + scan_warnings)

    candidates = tuple(
        opportunity
        for opportunity in scan.opportunities
        if str(opportunity.strategy).lower() == strategy
    )[: config.max_opportunities_per_strategy]
    if failure_reasons:
        return StrategyHeadRecord(
            **common,
            scan_rejection_reasons=candidate_rejections,
            excluded_reasons=_unique(failure_reasons),
        )
    if not candidates:
        return StrategyHeadRecord(
            **common,
            outcome_label="NO_TRADE",
            scan_rejection_reasons=candidate_rejections,
            included=True,
        )

    opportunity = candidates[0]
    symbols = tuple(leg.symbol for leg in opportunity.legs)
    if opportunity.requires_underlying_position:
        return StrategyHeadRecord(
            **common,
            candidate_symbols=symbols,
            scan_rejection_reasons=candidate_rejections,
            excluded_reasons=("underlying_position_not_in_snapshot_archive",),
        )
    replay = _replay_opportunity(opportunity, features.source_timestamp, snapshots, config)
    if replay.outcome is None:
        reasons = _unique(replay.reasons or ("future_outcome_unavailable",))
        common["data_quality_warnings"] = _unique(common["data_quality_warnings"] + replay.warnings)
        return StrategyHeadRecord(
            **common,
            candidate_symbols=symbols,
            scan_rejection_reasons=candidate_rejections,
            excluded_reasons=reasons,
        )

    outcome = replay.outcome
    common["data_quality_warnings"] = _unique(
        common["data_quality_warnings"] + replay.warnings + outcome.warnings
    )
    common["proxy_warnings"] = _unique(
        asof_proxy_warnings
        + tuple(warning for warning in replay.warnings if warning.startswith("proxy_source:"))
    )
    return StrategyHeadRecord(
        **common,
        outcome_label=outcome.label,
        gross_pnl=outcome.gross_pnl,
        costs=outcome.costs,
        net_pnl=outcome.net_pnl,
        return_pct=outcome.return_pct,
        notional=outcome.notional,
        risk_base=outcome.risk_base,
        outcome_timestamp=outcome.outcome_timestamp,
        outcome_source_timestamp=outcome.observation_timestamp,
        exit_reason=outcome.exit_reason,
        candidate_symbols=symbols,
        scan_rejection_reasons=candidate_rejections,
        included=True,
    )


@dataclass(frozen=True)
class _ReplayEvaluation:
    outcome: AfterCostOutcome | None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _replay_opportunity(
    opportunity: Opportunity,
    entry_time: datetime,
    snapshots: Sequence[HistoricalOptionSnapshot],
    config: StrategyHeadDatasetConfig,
) -> _ReplayEvaluation:
    legs = tuple(opportunity.legs)
    if not legs:
        return _ReplayEvaluation(None, ("missing_strategy_legs",))
    entry_values: dict[str, float] = {}
    for leg in legs:
        raw_entry = leg.ask_price if leg.position > 0 else leg.bid_price
        if raw_entry is None or raw_entry <= 0:
            return _ReplayEvaluation(None, (f"missing_entry_quote:{leg.symbol}",))
        entry_values[leg.symbol] = float(raw_entry)

    future = tuple(
        snapshot for snapshot in snapshots if _utc(snapshot.source_timestamp) > entry_time
    )
    expiry = _utc(opportunity.expiry_at)
    for future_snapshot in future:
        observed_at = _utc(future_snapshot.source_timestamp)
        if observed_at < expiry:
            quote_map = {quote.symbol: quote for quote in future_snapshot.quotes}
            if not all(_executable_quote(quote_map.get(leg.symbol)) for leg in legs):
                continue
            if config.exit_policy.type == "hold_to_expiry":
                continue
            if config.exit_policy.type == "min_dte":
                dte = (expiry - observed_at).total_seconds() / 86_400.0
                if dte > config.exit_policy.min_dte:
                    continue
            prices = {
                leg.symbol: _exit_quote_price(quote_map[leg.symbol], leg.position) for leg in legs
            }
            outcome = _make_after_cost_outcome(
                opportunity,
                entry_values,
                prices,
                observed_at,
                config,
                is_settlement=False,
                exit_reason=_early_exit_reason(config.exit_policy),
                observation_timestamp=observed_at,
            )
            if _exit_triggered(outcome, config.exit_policy):
                return _ReplayEvaluation(
                    outcome,
                    warnings=_unique(
                        _snapshot_warnings(future_snapshot) + _proxy_warnings(future_snapshot)
                    ),
                )
            continue

        underlying = _snapshot_underlying(future_snapshot)
        if underlying is None:
            continue
        prices = {leg.symbol: _intrinsic(leg.option_type, underlying, leg.strike) for leg in legs}
        warning = (
            "expiry settlement used the first archived underlying snapshot at or after expiry"
            if observed_at > expiry
            else None
        )
        outcome = _make_after_cost_outcome(
            opportunity,
            entry_values,
            prices,
            expiry,
            config,
            is_settlement=True,
            exit_reason="expiry",
            observation_timestamp=observed_at,
            warning=warning,
        )
        return _ReplayEvaluation(
            outcome,
            warnings=_unique(
                _snapshot_warnings(future_snapshot) + _proxy_warnings(future_snapshot)
            ),
        )

    if config.exit_policy.type == "end_of_test":
        for future_snapshot in reversed(future):
            quote_map = {quote.symbol: quote for quote in future_snapshot.quotes}
            if not all(_executable_quote(quote_map.get(leg.symbol)) for leg in legs):
                continue
            prices = {
                leg.symbol: _exit_quote_price(quote_map[leg.symbol], leg.position) for leg in legs
            }
            return _ReplayEvaluation(
                _make_after_cost_outcome(
                    opportunity,
                    entry_values,
                    prices,
                    _utc(future_snapshot.source_timestamp),
                    config,
                    is_settlement=False,
                    exit_reason="end_of_test",
                    observation_timestamp=_utc(future_snapshot.source_timestamp),
                ),
                warnings=_unique(
                    _snapshot_warnings(future_snapshot) + _proxy_warnings(future_snapshot)
                ),
            )
    return _ReplayEvaluation(None, ("future_outcome_unavailable",))


def _make_after_cost_outcome(
    opportunity: Opportunity,
    entry_values: dict[str, float],
    exit_prices: dict[str, float],
    outcome_timestamp: datetime,
    config: StrategyHeadDatasetConfig,
    *,
    is_settlement: bool,
    exit_reason: str,
    observation_timestamp: datetime,
    warning: str | None = None,
) -> AfterCostOutcome:
    scale = config.scan_request.quantity * config.scan_request.contract_multiplier
    slip_rate = config.scan_request.slippage_bps / 10_000.0
    entry_cash = 0.0
    exit_cash = 0.0
    notional = 0.0
    slippage = 0.0
    for leg in opportunity.legs:
        raw_entry = entry_values[leg.symbol]
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
    fees = config.scan_request.fee_per_contract * scale * 2.0 * len(opportunity.legs)
    costs = fees + slippage
    net_pnl = gross_pnl - costs
    risk_base = max(abs(float(opportunity.max_loss or 0.0)), abs(entry_cash), 1e-12)
    return AfterCostOutcome(
        label="PROFIT" if net_pnl > 0 else "LOSS",
        gross_pnl=gross_pnl,
        costs=costs,
        net_pnl=net_pnl,
        return_pct=net_pnl / risk_base * 100.0,
        notional=max(notional, 1e-12),
        risk_base=risk_base,
        outcome_timestamp=_utc(outcome_timestamp),
        observation_timestamp=_utc(observation_timestamp),
        exit_reason=("expiry" if is_settlement else exit_reason),
        warnings=(warning,) if warning else (),
    )


def _exit_triggered(outcome: AfterCostOutcome, policy: ExitPolicy) -> bool:
    if policy.type == "profit_target":
        # The backtest uses maximum loss as the risk base.  The outcome's
        # return is already after costs, so this comparison is intentionally
        # based on the same absolute return threshold.
        return outcome.return_pct >= policy.profit_target_pct * 100.0
    if policy.type == "stop_loss":
        return outcome.return_pct <= -policy.stop_loss_pct * 100.0
    return policy.type == "min_dte"


def _early_exit_reason(policy: ExitPolicy) -> str:
    return {
        "profit_target": "profit_target",
        "stop_loss": "stop_loss",
        "min_dte": "min_dte",
    }.get(policy.type, "quote_exit")


def _rejection_reasons(scan: ScanResult, strategy: str) -> tuple[str, ...]:
    reasons: list[str] = []
    for rejection in scan.rejections:
        rejection_strategy = str(rejection.strategy).lower() if rejection.strategy else None
        if rejection_strategy in {None, strategy}:
            reasons.extend(rejection.reasons)
    return _unique(tuple(reasons))


def _valid_values(
    quotes: Sequence[HistoricalOptionQuote],
    field_name: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> list[float]:
    values: list[float] = []
    for quote in quotes:
        value = getattr(quote, field_name)
        if value is None:
            continue
        parsed = float(value)
        if not math.isfinite(parsed):
            continue
        if positive and parsed <= 0:
            continue
        if non_negative and parsed < 0:
            continue
        values.append(parsed)
    return values


def _mean_or_zero(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median_or_zero(values: Sequence[float]) -> float:
    return float(median(values)) if values else 0.0


def _executable_quote(quote: HistoricalOptionQuote | None) -> bool:
    return bool(
        quote is not None
        and quote.bid_price is not None
        and quote.ask_price is not None
        and quote.bid_price > 0
        and quote.ask_price >= quote.bid_price
    )


def _exit_quote_price(quote: HistoricalOptionQuote, position: int) -> float:
    value = quote.bid_price if position > 0 else quote.ask_price
    if value is None or value <= 0:
        raise ValueError(f"missing executable exit quote for {quote.symbol}")
    return float(value)


def _snapshot_underlying(snapshot: HistoricalOptionSnapshot) -> float | None:
    values = _valid_values(snapshot.quotes, "underlying_price", positive=True)
    return values[0] if values else None


def _intrinsic(option_type: str, spot: float, strike: float) -> float:
    return (
        max(spot - strike, 0.0) if option_type.lower().startswith("c") else max(strike - spot, 0.0)
    )


def _proxy_warnings(snapshot: HistoricalOptionSnapshot) -> tuple[str, ...]:
    source = snapshot.source.lower()
    return (f"proxy_source:{snapshot.source}",) if "proxy" in source else ()


def _snapshot_warnings(snapshot: HistoricalOptionSnapshot) -> tuple[str, ...]:
    return tuple(_format_issue(issue) for issue in snapshot.issues)


def _format_issue(issue: OptionDataQualityIssue) -> str:
    return f"{issue.code}:{issue.message}"


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "AfterCostOutcome",
    "AsOfFeatures",
    "DatasetQuality",
    "OutcomeLabel",
    "StrategyHeadDataset",
    "StrategyHeadDatasetConfig",
    "StrategyHeadRecord",
    "build_strategy_head_dataset",
    "extract_asof_features",
]
