"""Read-only, multi-asset option opportunity scanning.

The public seam is :func:`scan_opportunities`.  It fits a volatility surface
without the candidate being scored, values the candidate at that fitted IV,
and only returns defined-risk long option ideas whose executable entry still
has positive model edge after costs.  This is a research signal, not an EV
validation or an order instruction.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from itertools import combinations
from typing import Literal

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionContract,
    OptionDataQualityIssue,
)

from .historical_volatility import (
    HistoricalVolatilityContext,
    HistoricalVolatilityContexts,
)
from .payoff_metrics import METHODOLOGY as PAYOFF_METRICS_METHODOLOGY
from .payoff_metrics import PayoffAssumptions, PayoffPoint, calculate_payoff_metrics
from .pricing import FairValueRequest, FairValueResult, PricingValidationError, price_fair_value
from .scenario_engine import ExecutionAssumptions, OptionLeg, StrategyDefinition
from .volatility_surface import (
    SurfaceConfig,
    VolatilityObservation,
    VolatilitySurfaceError,
    build_volatility_surface,
)

Strategy = Literal[
    "long_call",
    "long_put",
    "bull_call_vertical",
    "bear_call_vertical",
    "bull_put_vertical",
    "bear_put_vertical",
    "iron_condor",
    "iron_butterfly",
    "long_straddle",
    "long_strangle",
    "protective_put",
    "covered_call",
    "calendar_spread",
    "butterfly",
    "broken_wing_butterfly",
]
EvidenceStatus = Literal["not_validated", "insufficient_evidence"]
ValuationMode = Literal["executable", "theoretical", "synthetic"]
_THEORETICAL_IGNORED_FILTERS = (
    "max_spread_pct",
    "min_edge_after_costs",
    "max_loss",
)


@dataclass(frozen=True)
class ScanRequest:
    """Filters and cost assumptions for one deterministic scan.

    Rates, IVs, and slippage are decimals or basis points as named.  A scan
    never invents a rate or IV.  Single-leg, overlay, and defined-risk
    multi-leg structures are supported.  A covered call requires an existing
    underlying holding; the scanner only prices the option overlay and marks
    that requirement in the result.
    """

    risk_free_rate: float
    assets: tuple[str, ...] = ()
    min_dte: float | None = None
    max_dte: float | None = None
    min_delta: float | None = None
    max_delta: float | None = None
    min_volume_24h: float = 0.0
    min_open_interest: float = 0.0
    max_spread_pct: float | None = None
    min_iv_edge: float = 0.0
    min_edge_after_costs: float = 0.0
    max_loss: float | None = None
    fee_per_contract: float = 0.0
    slippage_bps: float = 0.0
    assumed_spread_bps: float = 100.0
    quantity: float = 1.0
    contract_multiplier: float = 1.0
    include_unvalidated: bool = True
    strategies: tuple[str, ...] = ("long_call", "long_put")
    max_results: int | None = None
    surface_config: SurfaceConfig | None = None
    valuation_mode: ValuationMode = "executable"

    def __post_init__(self) -> None:
        _finite("risk_free_rate", self.risk_free_rate)
        if self.valuation_mode not in {"executable", "theoretical", "synthetic"}:
            raise ValueError("valuation_mode must be executable, theoretical, or synthetic")
        for name in (
            "min_dte",
            "max_dte",
            "min_delta",
            "max_delta",
            "min_volume_24h",
            "min_open_interest",
            "max_spread_pct",
            "min_iv_edge",
            "min_edge_after_costs",
            "max_loss",
            "fee_per_contract",
            "slippage_bps",
            "assumed_spread_bps",
            "quantity",
            "contract_multiplier",
        ):
            value = getattr(self, name)
            if value is not None:
                _finite(name, value)
                if name not in {"min_iv_edge", "risk_free_rate"} and value < 0:
                    raise ValueError(f"{name} cannot be negative")
        if self.min_dte is not None and self.max_dte is not None and self.min_dte > self.max_dte:
            raise ValueError("min_dte cannot exceed max_dte")
        if (
            self.min_delta is not None
            and self.max_delta is not None
            and self.min_delta > self.max_delta
        ):
            raise ValueError("min_delta cannot exceed max_delta")
        if self.max_delta is not None and self.max_delta > 1:
            raise ValueError("max_delta cannot exceed 1")
        if self.max_spread_pct is not None and self.max_spread_pct > 1:
            raise ValueError("max_spread_pct cannot exceed 1")
        if self.assumed_spread_bps > 20_000:
            raise ValueError("assumed_spread_bps cannot exceed 20,000")
        if self.max_results is not None and self.max_results < 1:
            raise ValueError("max_results must be positive")
        if self.quantity <= 0 or self.contract_multiplier <= 0:
            raise ValueError("quantity and contract_multiplier must be positive")
        normalized_assets = tuple(
            sorted({str(asset).strip().upper() for asset in self.assets if str(asset).strip()})
        )
        normalized_strategies = tuple(
            dict.fromkeys(str(strategy).strip().lower() for strategy in self.strategies)
        )
        unsupported = set(normalized_strategies) - set(_SUPPORTED_STRATEGIES)
        if unsupported:
            raise ValueError(
                "unsupported strategy; naked short and order-placement strategies are not allowed"
            )
        object.__setattr__(self, "assets", normalized_assets)
        object.__setattr__(self, "strategies", normalized_strategies)


@dataclass(frozen=True)
class OpportunityLeg:
    """Auditable leg data carried with a single- or multi-leg opportunity."""

    symbol: str
    option_type: str
    strike: float
    expiry_at: datetime
    spot_price: float
    bid_price: float | None
    ask_price: float | None
    market_iv: float
    fair_iv: float
    fair_price: float
    delta: float
    volume_24h: float
    open_interest: float
    quote_timestamp: datetime
    position: int
    mark_price: float | None = None


@dataclass(frozen=True)
class Opportunity:
    asset: str
    symbol: str
    strategy: Strategy
    option_type: str
    strike: float
    expiry_at: datetime
    dte: float
    spot_price: float
    bid_price: float | None
    ask_price: float | None
    market_mid: float | None
    market_iv: float
    fair_iv: float
    iv_edge: float
    surface_status: str
    fair_price: float
    executable_entry: float | None
    fee: float
    slippage_cost: float
    edge_after_costs: float | None
    edge_pct: float | None
    max_loss: float | None
    delta: float
    volume_24h: float
    open_interest: float
    quote_timestamp: datetime
    evidence_status: EvidenceStatus
    expected_value_status: str = "not_validated"
    edge_source: str = "fitted_surface_minus_executable_entry_after_costs"
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    entry_slippage_cost: float = 0.0
    exit_slippage_cost: float = 0.0
    total_cost: float = 0.0
    estimated_entry: float | None = None
    execution_allowed: bool = False
    max_profit: float | None = 0.0
    long_symbol: str | None = None
    short_symbol: str | None = None
    long_strike: float | None = None
    short_strike: float | None = None
    legs: tuple[OpportunityLeg, ...] = ()
    breakevens: tuple[float, ...] = ()
    requires_underlying_position: bool = False
    risk_note: str | None = None
    payoff_curve: tuple[PayoffPoint, ...] = ()
    expected_value: float | None = None
    win_probability: float | None = None
    risk_reward: float | None = None
    payoff_metrics_status: str = "unavailable"
    win_probability_status: str = "unavailable"
    risk_reward_status: str = "unavailable"
    payoff_metrics_methodology: str = PAYOFF_METRICS_METHODOLOGY
    payoff_metrics_assumptions: PayoffAssumptions | None = None
    payoff_metrics_limitations: tuple[str, ...] = ()
    valuation_mode: ValuationMode = "executable"
    mark_price: float | None = None
    quote_source: str = "live_bid_ask"


@dataclass(frozen=True)
class RejectedCandidate:
    asset: str
    symbol: str
    option_type: str
    strike: float
    expiry_at: datetime
    reasons: tuple[str, ...]
    messages: tuple[str, ...]
    quote_timestamp: datetime
    strategy: Strategy | None = None
    long_symbol: str | None = None
    short_symbol: str | None = None


@dataclass(frozen=True)
class AssetScanFailure:
    asset: str
    code: str
    message: str


@dataclass(frozen=True)
class ScanResult:
    timestamp: datetime
    data_timestamp: datetime
    opportunities: tuple[Opportunity, ...]
    rejections: tuple[RejectedCandidate, ...]
    asset_failures: tuple[AssetScanFailure, ...]
    issues: tuple[OptionDataQualityIssue, ...]
    evidence_status: EvidenceStatus = "insufficient_evidence"
    evidence_gate_status: str = "blocked_unvalidated"
    execution_allowed: bool = False
    valuation_mode: ValuationMode = "executable"
    ignored_filters: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoricalContextScanResult:
    """A scan plus asset-level history metadata that did not affect pricing."""

    scan: ScanResult
    historical_volatility_contexts: tuple[HistoricalVolatilityContext, ...]


_SINGLE_LEG_STRATEGIES = ("long_call", "long_put")
_VERTICAL_STRATEGIES = (
    "bull_call_vertical",
    "bear_call_vertical",
    "bull_put_vertical",
    "bear_put_vertical",
)
_MULTI_LEG_STRATEGIES = ("iron_condor", "iron_butterfly")
_OVERLAY_STRATEGIES = ("protective_put", "covered_call")
_STRUCTURED_STRATEGIES = (
    "long_straddle",
    "long_strangle",
    "calendar_spread",
    "butterfly",
    "broken_wing_butterfly",
)
_SUPPORTED_STRATEGIES = (
    _SINGLE_LEG_STRATEGIES
    + _VERTICAL_STRATEGIES
    + _MULTI_LEG_STRATEGIES
    + _OVERLAY_STRATEGIES
    + _STRUCTURED_STRATEGIES
)
_MAX_MULTI_LEG_CANDIDATES = 10_000


def scan_opportunities(
    universe: NormalizedOptionUniverse,
    request: ScanRequest,
) -> ScanResult:
    """Return ranked, defined-risk opportunities and auditable rejections."""

    if not isinstance(universe, NormalizedOptionUniverse):
        raise TypeError("universe must be a NormalizedOptionUniverse")
    if not isinstance(request, ScanRequest):
        raise TypeError("request must be a ScanRequest")

    contracts_by_asset = universe.contracts_by_asset
    selected_assets = _selected_assets(universe, request)
    opportunities: list[Opportunity] = []
    rejections: list[RejectedCandidate] = []
    failures: list[AssetScanFailure] = []

    for asset in selected_assets:
        asset_contracts = tuple(
            sorted(
                contracts_by_asset.get(asset, ()),
                key=lambda item: (
                    _as_utc(item.expiry_at),
                    item.strike,
                    item.option_type,
                    item.symbol,
                ),
            )
        )
        asset_issues = tuple(issue for issue in universe.issues if issue.asset == asset)
        if not asset_contracts:
            code = next(
                (
                    issue.code
                    for issue in asset_issues
                    if issue.code in {"asset_fetch_failed", "asset_not_discovered"}
                ),
                "asset_not_available",
            )
            failures.append(
                AssetScanFailure(asset, code, _failure_message(asset, code, asset_issues))
            )
            continue

        if any(strategy in request.strategies for strategy in _SINGLE_LEG_STRATEGIES):
            for candidate in asset_contracts:
                rejection = _precheck(candidate, request, universe.valuation_time)
                if rejection:
                    rejections.append(rejection)
                    continue
                if request.valuation_mode in {"theoretical", "synthetic"}:
                    _scan_theoretical_candidate(
                        candidate,
                        asset_contracts,
                        request,
                        universe.valuation_time,
                        opportunities,
                        rejections,
                    )
                    continue
                try:
                    surface = build_volatility_surface(
                        _surface_observations(
                            asset_contracts,
                            excluded_symbols={candidate.symbol},
                            allow_unquoted=request.valuation_mode in {"theoretical", "synthetic"},
                        ),
                        valuation_time=_as_utc(universe.valuation_time),
                        config=request.surface_config,
                    ).surface_for(asset)
                    valued = price_fair_value(
                        FairValueRequest(
                            option_type=candidate.option_type,
                            spot=candidate.spot_price,
                            strike=candidate.strike,
                            expiry=_as_utc(candidate.expiry_at),
                            valuation_time=_as_utc(universe.valuation_time),
                            iv=None,
                            risk_free_rate=request.risk_free_rate,
                            surface=surface,
                            prefer_observed_surface=False,
                        )
                    )
                except (PricingValidationError, VolatilitySurfaceError, ValueError) as exc:
                    rejections.append(
                        _rejection(candidate, ("surface_or_pricing_failed",), (str(exc),))
                    )
                    continue

                iv_edge = valued.fair_iv - candidate.mark_iv
                scale = request.quantity * request.contract_multiplier
                entry_fee = request.fee_per_contract * scale
                exit_fee = request.fee_per_contract * scale
                entry_slippage = candidate.ask_price * request.slippage_bps / 10_000.0 * scale
                # The fair value is a model reference, while the current bid is
                # the only executable exit anchor available in this snapshot.
                exit_slippage = candidate.bid_price * request.slippage_bps / 10_000.0 * scale
                entry = candidate.ask_price * scale
                total_cost = entry_fee + exit_fee + entry_slippage + exit_slippage
                edge = valued.fair_price * scale - entry - total_cost
                max_loss = entry + entry_fee + entry_slippage
                reasons: list[str] = []
                messages: list[str] = []
                if iv_edge < request.min_iv_edge:
                    reasons.append("iv_edge_below_minimum")
                    messages.append(f"IV edge {iv_edge:.6f} is below {request.min_iv_edge:.6f}")
                if edge <= request.min_edge_after_costs:
                    reasons.append("edge_after_costs_below_minimum")
                    messages.append(
                        f"Edge after costs {edge:.6f} is not above {request.min_edge_after_costs:.6f}"
                    )
                if request.max_loss is not None and max_loss > request.max_loss:
                    reasons.append("max_loss_exceeded")
                    messages.append(f"Maximum loss {max_loss:.6f} exceeds {request.max_loss:.6f}")
                if not request.include_unvalidated:
                    reasons.append("evidence_not_validated")
                    messages.append("Historical out-of-sample evidence is not available")
                if reasons:
                    rejections.append(_rejection(candidate, tuple(reasons), tuple(messages)))
                    continue
                opportunities.append(
                    Opportunity(
                        asset=candidate.asset,
                        symbol=candidate.symbol,
                        strategy=_strategy_for(candidate),
                        option_type=candidate.option_type,
                        strike=candidate.strike,
                        expiry_at=_as_utc(candidate.expiry_at),
                        dte=_dte(candidate.expiry_at, universe.valuation_time),
                        spot_price=candidate.spot_price,
                        bid_price=candidate.bid_price,
                        ask_price=candidate.ask_price,
                        market_mid=(candidate.bid_price + candidate.ask_price) / 2.0,
                        market_iv=candidate.mark_iv,
                        fair_iv=valued.fair_iv,
                        iv_edge=iv_edge,
                        surface_status=valued.surface_status or "unknown",
                        fair_price=valued.fair_price,
                        executable_entry=entry,
                        fee=entry_fee,
                        slippage_cost=entry_slippage,
                        edge_after_costs=edge,
                        edge_pct=edge / max(entry, 1e-12),
                        max_loss=max_loss,
                        max_profit=_single_leg_max_profit(
                            candidate, entry_fee + entry_slippage, scale
                        ),
                        delta=valued.delta,
                        volume_24h=candidate.volume_24h,
                        open_interest=candidate.open_interest,
                        quote_timestamp=_as_utc(candidate.quote_timestamp),
                        evidence_status="insufficient_evidence",
                        entry_fee=entry_fee,
                        exit_fee=exit_fee,
                        entry_slippage_cost=entry_slippage,
                        exit_slippage_cost=exit_slippage,
                        total_cost=total_cost,
                        long_symbol=candidate.symbol,
                        long_strike=candidate.strike,
                        legs=(
                            OpportunityLeg(
                                symbol=candidate.symbol,
                                option_type=candidate.option_type,
                                strike=candidate.strike,
                                expiry_at=_as_utc(candidate.expiry_at),
                                spot_price=candidate.spot_price,
                                bid_price=candidate.bid_price,
                                ask_price=candidate.ask_price,
                                market_iv=candidate.mark_iv,
                                fair_iv=valued.fair_iv,
                                fair_price=valued.fair_price,
                                delta=valued.delta,
                                volume_24h=candidate.volume_24h,
                                open_interest=candidate.open_interest,
                                quote_timestamp=_as_utc(candidate.quote_timestamp),
                                position=1,
                            ),
                        ),
                    )
                )

        if any(strategy in request.strategies for strategy in _VERTICAL_STRATEGIES):
            _scan_verticals(
                asset_contracts,
                request,
                universe.valuation_time,
                opportunities,
                rejections,
            )
        if any(strategy in request.strategies for strategy in _MULTI_LEG_STRATEGIES):
            _scan_multi_legs(
                asset_contracts,
                request,
                universe.valuation_time,
                opportunities,
                rejections,
            )
        if any(strategy in request.strategies for strategy in _STRUCTURED_STRATEGIES):
            _scan_structured_strategies(
                asset_contracts,
                request,
                universe.valuation_time,
                opportunities,
                rejections,
            )
        if any(strategy in request.strategies for strategy in _OVERLAY_STRATEGIES):
            _scan_underlying_overlays(
                asset_contracts,
                request,
                universe.valuation_time,
                opportunities,
                rejections,
            )

    if request.valuation_mode == "synthetic":
        opportunities = [
            _with_synthetic_quote_metrics(opportunity, request)
            for opportunity in opportunities
        ]
    opportunities = [
        _with_payoff_metrics(opportunity, request, universe.valuation_time)
        for opportunity in opportunities
    ]
    if request.valuation_mode == "synthetic":
        opportunities = _apply_synthetic_filters(opportunities, request)
    if request.valuation_mode == "theoretical":
        opportunities.sort(
            key=lambda item: (-item.fair_price, -item.iv_edge, item.asset, item.symbol)
        )
    else:
        opportunities.sort(
            key=lambda item: (-item.edge_after_costs, -item.iv_edge, item.asset, item.symbol)
        )
    if request.max_results is not None:
        opportunities = opportunities[: request.max_results]
    return ScanResult(
        timestamp=_as_utc(universe.valuation_time),
        data_timestamp=min(
            (_as_utc(contract.quote_timestamp) for contract in universe.contracts),
            default=_as_utc(universe.valuation_time),
        ),
        opportunities=tuple(opportunities),
        rejections=tuple(
            sorted(
                rejections,
                key=lambda item: (item.asset, _as_utc(item.expiry_at), item.strike, item.symbol),
            )
        ),
        asset_failures=tuple(sorted(failures, key=lambda item: (item.asset, item.code))),
        issues=tuple(
            sorted(
                universe.issues, key=lambda item: (item.asset or "", item.code, item.symbol or "")
            )
        ),
        evidence_gate_status="open_unvalidated_signals"
        if request.include_unvalidated
        else "blocked_unvalidated",
        execution_allowed=False,
        valuation_mode=request.valuation_mode,
        ignored_filters=(
            _THEORETICAL_IGNORED_FILTERS
            if request.valuation_mode == "theoretical"
            else ()
        ),
    )


def scan_opportunities_with_historical_context(
    universe: NormalizedOptionUniverse,
    request: ScanRequest,
    historical_volatility: HistoricalVolatilityContexts,
) -> HistoricalContextScanResult:
    """Scan while carrying explicit historical-volatility quality metadata.

    The history context is attached only after :func:`scan_opportunities`
    completes.  It therefore cannot alter the current surface, fair IV,
    ranking, or evidence gates.
    """

    if not isinstance(historical_volatility, HistoricalVolatilityContexts):
        raise TypeError("historical_volatility must be HistoricalVolatilityContexts")
    scan = scan_opportunities(universe, request)
    contexts = historical_volatility.cover(
        tuple(_selected_assets(universe, request)),
        requested_at=_as_utc(universe.valuation_time),
    )
    return HistoricalContextScanResult(
        scan=scan,
        historical_volatility_contexts=contexts,
    )


def _selected_assets(
    universe: NormalizedOptionUniverse,
    request: ScanRequest,
) -> tuple[str, ...]:
    contracts_by_asset = universe.contracts_by_asset
    discovered_assets = {asset.base_coin.upper() for asset in universe.assets}
    discovered_assets.update(contracts_by_asset)
    return request.assets or tuple(sorted(discovered_assets))


def _with_payoff_metrics(
    opportunity: Opportunity,
    request: ScanRequest,
    valuation_time: datetime,
) -> Opportunity:
    """Attach one consistently calculated payoff contract to any candidate."""

    theoretical = opportunity.valuation_mode == "theoretical"
    synthetic = opportunity.valuation_mode == "synthetic"

    scenario_legs = (
        ()
        if opportunity.requires_underlying_position
        else tuple(
            OptionLeg(
                symbol=leg.symbol,
                option_type=leg.option_type,
                strike=leg.strike,
                expiry=leg.expiry_at,
                valuation_time=_as_utc(valuation_time),
                spot=leg.spot_price,
                iv=leg.fair_iv,
                risk_free_rate=request.risk_free_rate,
                bid=leg.fair_price if theoretical else leg.bid_price,
                ask=leg.fair_price if theoretical else leg.ask_price,
                position=leg.position,
            )
            for leg in opportunity.legs
        )
    )
    scenario_strategy = _scenario_strategy(opportunity.strategy)
    metrics = calculate_payoff_metrics(
        StrategyDefinition(
            strategy_type=scenario_strategy,  # type: ignore[arg-type]
            legs=scenario_legs,
        ),
        ExecutionAssumptions(
            fee_per_contract=request.fee_per_contract,
            slippage_bps=request.slippage_bps,
            contract_multiplier=request.contract_multiplier,
        ),
        quantity=request.quantity,
        entry_price_source=(
            "theoretical_fair_value"
            if theoretical
            else "synthetic_bid_ask"
            if synthetic
            else "long ask / short bid"
        ),
    )
    return replace(
        opportunity,
        payoff_curve=metrics.payoff_curve,
        expected_value=metrics.expected_value,
        win_probability=metrics.win_probability,
        risk_reward=metrics.risk_reward,
        payoff_metrics_status=metrics.status,
        expected_value_status=metrics.expected_value_status,
        win_probability_status=metrics.win_probability_status,
        risk_reward_status=metrics.risk_reward_status,
        payoff_metrics_methodology=metrics.methodology,
        payoff_metrics_assumptions=metrics.assumptions,
        payoff_metrics_limitations=metrics.limitations,
        max_loss=metrics.max_loss if theoretical or synthetic else opportunity.max_loss,
        max_profit=metrics.max_profit if theoretical or synthetic else opportunity.max_profit,
        breakevens=metrics.breakevens if theoretical or synthetic else opportunity.breakevens,
    )


def _with_synthetic_quote_metrics(
    opportunity: Opportunity,
    request: ScanRequest,
) -> Opportunity:
    """Attach an estimated quote and executable-shaped entry metrics.

    The midpoint comes from mark price when available, then the fitted fair
    value. The resulting bid/ask is
    deliberately synthetic and is never marked executable.
    """

    if not opportunity.legs:
        return opportunity

    legs = tuple(
        _with_synthetic_leg_quote(leg, request.assumed_spread_bps)
        for leg in opportunity.legs
    )
    positions = tuple(leg.position for leg in legs)
    scale = request.quantity * request.contract_multiplier
    entry_unit = sum(
        (leg.ask_price if position > 0 else -leg.bid_price)
        for leg, position in zip(legs, positions)
    )
    bid_unit = sum(
        (leg.bid_price if position > 0 else -leg.ask_price)
        for leg, position in zip(legs, positions)
    )
    market_mid_unit = sum(
        position * (leg.bid_price + leg.ask_price) / 2.0
        for leg, position in zip(legs, positions)
    )
    fair_price = sum(
        position * leg.fair_price for leg, position in zip(legs, positions)
    ) * scale
    entry = entry_unit * scale
    entry_fee = request.fee_per_contract * len(legs) * scale
    exit_fee = request.fee_per_contract * len(legs) * scale
    entry_slippage = sum(
        abs(leg.ask_price if position > 0 else leg.bid_price)
        * request.slippage_bps
        / 10_000.0
        * scale
        for leg, position in zip(legs, positions)
    )
    exit_slippage = sum(
        abs(leg.bid_price if position > 0 else leg.ask_price)
        * request.slippage_bps
        / 10_000.0
        * scale
        for leg, position in zip(legs, positions)
    )
    total_cost = entry_fee + exit_fee + entry_slippage + exit_slippage
    edge = fair_price - entry - total_cost
    spread_text = f"{request.assumed_spread_bps:g} bps"
    risk_note = opportunity.risk_note
    synthetic_note = (
        "Synthetic bid/ask estimated from mark/fair value with an assumed "
        f"{spread_text} spread; not executable."
    )
    risk_note = f"{risk_note} {synthetic_note}" if risk_note else synthetic_note
    return replace(
        opportunity,
        bid_price=bid_unit * scale,
        ask_price=entry,
        market_mid=market_mid_unit * scale,
        fair_price=fair_price,
        executable_entry=None,
        estimated_entry=entry,
        fee=entry_fee,
        slippage_cost=entry_slippage,
        edge_after_costs=edge,
        edge_pct=edge / max(abs(entry), 1e-12),
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        entry_slippage_cost=entry_slippage,
        exit_slippage_cost=exit_slippage,
        total_cost=total_cost,
        edge_source="fitted_surface_minus_synthetic_bid_ask_after_costs",
        risk_note=risk_note,
        valuation_mode="synthetic",
        quote_source="synthetic_mark_or_fair_value",
        legs=legs,
    )


def _apply_synthetic_filters(
    opportunities: list[Opportunity],
    request: ScanRequest,
) -> list[Opportunity]:
    """Apply quote-dependent filters to the estimated synthetic quote."""

    filtered: list[Opportunity] = []
    for opportunity in opportunities:
        if (
            opportunity.edge_after_costs is not None
            and opportunity.edge_after_costs <= request.min_edge_after_costs
        ):
            continue
        if (
            request.max_loss is not None
            and opportunity.max_loss is not None
            and opportunity.max_loss > request.max_loss
        ):
            continue
        if request.max_spread_pct is not None and any(
            _quote_spread_pct(leg.bid_price, leg.ask_price) > request.max_spread_pct
            for leg in opportunity.legs
        ):
            continue
        filtered.append(opportunity)
    return filtered


def _synthetic_midpoint(leg: OpportunityLeg) -> float:
    if leg.mark_price is not None and math.isfinite(leg.mark_price) and leg.mark_price > 0:
        return leg.mark_price
    return max(0.0, leg.fair_price)


def _synthetic_bid_ask(midpoint: float, spread_bps: float) -> tuple[float, float]:
    half_spread = spread_bps / 20_000.0
    return (
        max(0.0, midpoint * (1.0 - half_spread)),
        max(0.0, midpoint * (1.0 + half_spread)),
    )


def _with_synthetic_leg_quote(leg: OpportunityLeg, spread_bps: float) -> OpportunityLeg:
    bid, ask = _synthetic_bid_ask(_synthetic_midpoint(leg), spread_bps)
    return replace(leg, bid_price=bid, ask_price=ask)


def _quote_spread_pct(bid: float | None, ask: float | None) -> float:
    if bid is None or ask is None:
        return math.inf
    midpoint = (bid + ask) / 2.0
    if midpoint <= 0:
        return math.inf
    return (ask - bid) / midpoint


def _scenario_strategy(strategy: Strategy) -> str:
    if strategy in {"bull_call_vertical", "bear_call_vertical"}:
        return "call_vertical"
    if strategy in {"bull_put_vertical", "bear_put_vertical"}:
        return "put_vertical"
    return strategy


def _scan_theoretical_candidate(
    candidate: OptionContract,
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    """Value a single contract without turning reference data into a quote."""

    try:
        surface = build_volatility_surface(
            _surface_observations(
                asset_contracts,
                excluded_symbols={candidate.symbol},
                allow_unquoted=request.valuation_mode in {"theoretical", "synthetic"},
            ),
            valuation_time=_as_utc(valuation_time),
            config=request.surface_config,
        ).surface_for(candidate.asset)
        valued = price_fair_value(
            FairValueRequest(
                option_type=candidate.option_type,
                spot=candidate.spot_price,
                strike=candidate.strike,
                expiry=_as_utc(candidate.expiry_at),
                valuation_time=_as_utc(valuation_time),
                iv=None,
                risk_free_rate=request.risk_free_rate,
                surface=surface,
                prefer_observed_surface=False,
            )
        )
    except (PricingValidationError, VolatilitySurfaceError, ValueError, KeyError) as exc:
        rejections.append(_rejection(candidate, ("surface_or_pricing_failed",), (str(exc),)))
        return

    iv_edge = valued.fair_iv - candidate.mark_iv
    reasons: list[str] = []
    messages: list[str] = []
    if iv_edge < request.min_iv_edge:
        reasons.append("iv_edge_below_minimum")
        messages.append(f"IV edge {iv_edge:.6f} is below {request.min_iv_edge:.6f}")
    if not request.include_unvalidated:
        reasons.append("evidence_not_validated")
        messages.append("Historical out-of-sample evidence is not available")
    if reasons:
        rejections.append(_rejection(candidate, tuple(reasons), tuple(messages)))
        return

    market_mid = _positive_quote_mid(candidate.bid_price, candidate.ask_price)
    opportunities.append(
        Opportunity(
            asset=candidate.asset,
            symbol=candidate.symbol,
            strategy=_strategy_for(candidate),
            option_type=candidate.option_type,
            strike=candidate.strike,
            expiry_at=_as_utc(candidate.expiry_at),
            dte=_dte(candidate.expiry_at, valuation_time),
            spot_price=candidate.spot_price,
            bid_price=candidate.bid_price,
            ask_price=candidate.ask_price,
            market_mid=market_mid,
            market_iv=candidate.mark_iv,
            fair_iv=valued.fair_iv,
            iv_edge=iv_edge,
            surface_status=valued.surface_status or "unknown",
            fair_price=valued.fair_price,
            executable_entry=None,
            fee=0.0,
            slippage_cost=0.0,
            edge_after_costs=None,
            edge_pct=None,
            max_loss=None,
            max_profit=None,
            delta=valued.delta,
            volume_24h=candidate.volume_24h,
            open_interest=candidate.open_interest,
            quote_timestamp=_as_utc(candidate.quote_timestamp),
            evidence_status="insufficient_evidence",
            edge_source="theoretical_fair_value_only",
            execution_allowed=False,
            long_symbol=candidate.symbol,
            long_strike=candidate.strike,
            risk_note=(
                "Synthetic valuation only; bid/ask is estimated and not executable."
                if request.valuation_mode == "synthetic"
                else "Theoretical valuation only; bid/ask is not an executable quote."
            ),
            valuation_mode=request.valuation_mode,
            mark_price=candidate.mark_price,
            quote_source=(
                "synthetic_mark_or_fair_value"
                if request.valuation_mode == "synthetic"
                else "theoretical_fair_value"
            ),
            legs=(
                OpportunityLeg(
                    symbol=candidate.symbol,
                    option_type=candidate.option_type,
                    strike=candidate.strike,
                    expiry_at=_as_utc(candidate.expiry_at),
                    spot_price=candidate.spot_price,
                    bid_price=candidate.bid_price,
                    ask_price=candidate.ask_price,
                    market_iv=candidate.mark_iv,
                    fair_iv=valued.fair_iv,
                    fair_price=valued.fair_price,
                    delta=valued.delta,
                    volume_24h=candidate.volume_24h,
                    open_interest=candidate.open_interest,
                    quote_timestamp=_as_utc(candidate.quote_timestamp),
                    position=1,
                    mark_price=candidate.mark_price,
                ),
            ),
        )
    )


def _append_theoretical_multi_leg(
    strategy: str,
    legs: tuple[OptionContract, ...],
    positions: tuple[int, ...],
    valued: tuple[FairValueResult, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
    *,
    requires_underlying_position: bool = False,
    risk_note: str | None = None,
) -> None:
    """Append a model-only structure without deriving execution metrics."""

    fair_values = tuple(valued)
    fair_price = sum(
        position * value.fair_price
        for position, value in zip(positions, fair_values)
    ) * request.quantity * request.contract_multiplier
    fair_iv = sum(
        position * value.fair_iv for position, value in zip(positions, fair_values)
    )
    iv_edge = sum(
        position * (value.fair_iv - leg.mark_iv)
        for position, value, leg in zip(positions, fair_values, legs)
    )
    reasons: list[str] = []
    messages: list[str] = []
    if iv_edge < request.min_iv_edge:
        reasons.append("iv_edge_below_minimum")
        messages.append(f"IV edge {iv_edge:.6f} is below {request.min_iv_edge:.6f}")
    if not request.include_unvalidated:
        reasons.append("evidence_not_validated")
        messages.append("Historical out-of-sample evidence is not available")
    if reasons:
        rejections.append(
            _multi_leg_rejection(strategy, legs, tuple(reasons), tuple(messages))
        )
        return

    scale = request.quantity * request.contract_multiplier
    positive_quotes = all(
        _positive_quote_mid(leg.bid_price, leg.ask_price) is not None for leg in legs
    )
    market_mid = None
    bid_price = None
    ask_price = None
    if positive_quotes:
        market_mid = sum(
            position * (leg.bid_price + leg.ask_price) / 2.0
            for position, leg in zip(positions, legs)
        ) * scale
        bid_price = sum(
            (leg.bid_price if position > 0 else -leg.ask_price)
            for position, leg in zip(positions, legs)
        ) * scale
        ask_price = sum(
            (leg.ask_price if position > 0 else -leg.bid_price)
            for position, leg in zip(positions, legs)
        ) * scale
    first = legs[0]
    opportunities.append(
        Opportunity(
            asset=first.asset,
            symbol="/".join(leg.symbol for leg in legs),
            strategy=strategy,  # type: ignore[arg-type]
            option_type="multi" if len(legs) > 1 else first.option_type,
            strike=min(leg.strike for leg in legs),
            expiry_at=_as_utc(first.expiry_at),
            dte=_dte(first.expiry_at, valuation_time),
            spot_price=first.spot_price,
            bid_price=bid_price,
            ask_price=ask_price,
            market_mid=market_mid,
            market_iv=sum(position * leg.mark_iv for position, leg in zip(positions, legs)),
            fair_iv=fair_iv,
            iv_edge=iv_edge,
            surface_status=_surface_status(*(value.surface_status for value in fair_values)),
            fair_price=fair_price,
            executable_entry=None,
            fee=0.0,
            slippage_cost=0.0,
            edge_after_costs=None,
            edge_pct=None,
            max_loss=None,
            max_profit=None,
            delta=sum(position * value.delta for position, value in zip(positions, fair_values)) * scale,
            volume_24h=min(leg.volume_24h for leg in legs),
            open_interest=min(leg.open_interest for leg in legs),
            quote_timestamp=max(_as_utc(leg.quote_timestamp) for leg in legs),
            evidence_status="insufficient_evidence",
            edge_source="theoretical_fair_value_only",
            execution_allowed=False,
            long_symbol=next(
                (leg.symbol for leg, position in zip(legs, positions) if position > 0),
                None,
            ),
            short_symbol=next(
                (leg.symbol for leg, position in zip(legs, positions) if position < 0),
                None,
            ),
            long_strike=next(
                (leg.strike for leg, position in zip(legs, positions) if position > 0),
                None,
            ),
            short_strike=next(
                (leg.strike for leg, position in zip(legs, positions) if position < 0),
                None,
            ),
            requires_underlying_position=requires_underlying_position,
            risk_note=risk_note
            or (
                "Synthetic valuation only; bid/ask is estimated and not executable."
                if request.valuation_mode == "synthetic"
                else "Theoretical valuation only; bid/ask is not an executable quote."
            ),
            valuation_mode=request.valuation_mode,
            quote_source=(
                "synthetic_mark_or_fair_value"
                if request.valuation_mode == "synthetic"
                else "theoretical_fair_value"
            ),
            legs=tuple(
                OpportunityLeg(
                    symbol=leg.symbol,
                    option_type=leg.option_type,
                    strike=leg.strike,
                    expiry_at=_as_utc(leg.expiry_at),
                    spot_price=leg.spot_price,
                    bid_price=leg.bid_price,
                    ask_price=leg.ask_price,
                    market_iv=leg.mark_iv,
                    fair_iv=value.fair_iv,
                    fair_price=value.fair_price,
                    delta=value.delta,
                    volume_24h=leg.volume_24h,
                    open_interest=leg.open_interest,
                    quote_timestamp=_as_utc(leg.quote_timestamp),
                    position=position,
                    mark_price=leg.mark_price,
                )
                for leg, value, position in zip(legs, fair_values, positions)
            ),
        )
    )


def _scan_verticals(
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    """Enumerate same-expiry, same-type verticals for one asset."""

    by_expiry_and_type: dict[tuple[datetime, str], list[OptionContract]] = {}
    by_expiry: dict[datetime, list[OptionContract]] = {}
    for contract in asset_contracts:
        try:
            expiry = _as_utc(contract.expiry_at)
        except (AttributeError, TypeError, ValueError):
            continue
        by_expiry.setdefault(expiry, []).append(contract)
        option_kind = _option_kind(contract)
        if option_kind is not None:
            by_expiry_and_type.setdefault((expiry, option_kind), []).append(contract)

    for strategy in request.strategies:
        if strategy not in _VERTICAL_STRATEGIES:
            continue
        expected_type = _vertical_option_type(strategy)
        matching_groups = [
            (expiry, tuple(sorted(contracts, key=_contract_order)))
            for (expiry, option_type), contracts in by_expiry_and_type.items()
            if option_type == expected_type
        ]
        if not matching_groups:
            for contracts in by_expiry.values():
                representative = min(contracts, key=_contract_order)
                rejections.append(
                    _vertical_rejection(
                        strategy,
                        representative,
                        None,
                        ("missing_long_leg", "missing_short_leg", "missing_option_type"),
                        (
                            (
                                f"No {expected_type} contracts were available for a same-expiry "
                                "vertical"
                            ),
                        ),
                    )
                )
            continue

        for _, contracts in sorted(matching_groups, key=lambda item: item[0]):
            if len(contracts) < 2:
                representative = contracts[0]
                leg_rejection = _precheck(
                    representative,
                    request,
                    valuation_time,
                    check_strategy=False,
                )
                if leg_rejection:
                    reasons, messages = _prefixed_leg_reasons("leg", leg_rejection)
                    reasons.insert(0, "invalid_leg")
                    messages.insert(
                        0, "The only same-expiry leg failed market-data or filter validation"
                    )
                else:
                    reasons = ["missing_long_leg", "missing_short_leg"]
                    messages = [
                        (
                            "A vertical requires two executable contracts with distinct strikes; "
                            "the matching leg is missing"
                        )
                    ]
                rejections.append(
                    _vertical_rejection(
                        strategy,
                        representative,
                        None,
                        tuple(reasons),
                        tuple(messages),
                    )
                )
                continue

            for first, second in combinations(contracts, 2):
                if first.strike == second.strike:
                    rejections.append(
                        _vertical_rejection(
                            strategy,
                            first,
                            second,
                            ("distinct_strikes_required",),
                            ("Vertical legs must use distinct strikes",),
                        )
                    )
                    continue
                long_leg, short_leg = _vertical_legs(strategy, first, second)
                long_rejection = _precheck(
                    long_leg,
                    request,
                    valuation_time,
                    check_strategy=False,
                )
                short_rejection = _precheck(
                    short_leg,
                    request,
                    valuation_time,
                    check_strategy=False,
                )
                if long_rejection or short_rejection:
                    reasons: list[str] = []
                    messages: list[str] = []
                    if long_rejection:
                        leg_reasons, leg_messages = _prefixed_leg_reasons("long", long_rejection)
                        reasons.extend(leg_reasons)
                        messages.extend(leg_messages)
                    if short_rejection:
                        leg_reasons, leg_messages = _prefixed_leg_reasons("short", short_rejection)
                        reasons.extend(leg_reasons)
                        messages.extend(leg_messages)
                    rejections.append(
                        _vertical_rejection(
                            strategy,
                            long_leg,
                            short_leg,
                            tuple(reasons),
                            tuple(messages),
                        )
                    )
                    continue
                _scan_vertical_pair(
                    strategy,
                    long_leg,
                    short_leg,
                    asset_contracts,
                    request,
                    valuation_time,
                    opportunities,
                    rejections,
                )


def _scan_multi_legs(
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    """Enumerate four-leg iron condors and iron butterflies for one asset."""

    by_expiry: dict[datetime, tuple[OptionContract, ...]] = {}
    for contract in asset_contracts:
        expiry = _as_utc(contract.expiry_at)
        by_expiry[expiry] = tuple(
            sorted(
                (*by_expiry.get(expiry, ()), contract),
                key=_contract_order,
            )
        )

    for strategy in request.strategies:
        if strategy not in _MULTI_LEG_STRATEGIES:
            continue
        for _, contracts in sorted(by_expiry.items()):
            generated = (
                _iron_condor_leg_sets(contracts)
                if strategy == "iron_condor"
                else _iron_butterfly_leg_sets(contracts)
            )
            found = False
            for count, legs in enumerate(generated, start=1):
                found = True
                _scan_multi_leg_candidate(
                    strategy,
                    legs,
                    asset_contracts,
                    request,
                    valuation_time,
                    opportunities,
                    rejections,
                )
                if count >= _MAX_MULTI_LEG_CANDIDATES:
                    break
            if not found:
                representative = min(contracts, key=_contract_order)
                required = (
                    ("missing_put_wing", "missing_call_wing")
                    if strategy == "iron_condor"
                    else ("missing_put_wing", "missing_call_wing", "missing_equal_strike_bodies")
                )
                rejections.append(
                    _multi_leg_rejection(
                        strategy,
                        (representative,),
                        required,
                        (f"No valid {strategy.replace('_', ' ')} four-leg structure was found",),
                    )
                )


def _scan_structured_strategies(
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    """Enumerate long volatility, calendars, and butterfly structures."""

    by_expiry: dict[datetime, tuple[OptionContract, ...]] = {}
    for contract in asset_contracts:
        expiry = _as_utc(contract.expiry_at)
        by_expiry[expiry] = tuple(
            sorted((*by_expiry.get(expiry, ()), contract), key=_contract_order)
        )

    for strategy in request.strategies:
        if strategy not in _STRUCTURED_STRATEGIES:
            continue
        generated: Iterator[tuple[OptionContract, ...]]
        if strategy == "calendar_spread":
            generated = _calendar_leg_sets(asset_contracts)
        else:
            generated = _same_expiry_strategy_leg_sets(strategy, by_expiry)
        found = False
        for count, legs in enumerate(generated, start=1):
            found = True
            _scan_multi_leg_candidate(
                strategy,
                legs,
                asset_contracts,
                request,
                valuation_time,
                opportunities,
                rejections,
            )
            if count >= _MAX_MULTI_LEG_CANDIDATES:
                break
        if not found and asset_contracts:
            representative = min(asset_contracts, key=_contract_order)
            rejections.append(
                _multi_leg_rejection(
                    strategy,
                    (representative,),
                    ("required_legs_unavailable",),
                    (f"No valid {strategy.replace('_', ' ')} structure was found",),
                )
            )


def _same_expiry_strategy_leg_sets(
    strategy: str,
    by_expiry: dict[datetime, tuple[OptionContract, ...]],
) -> Iterator[tuple[OptionContract, ...]]:
    for _, contracts in sorted(by_expiry.items()):
        puts = tuple(item for item in contracts if _option_kind(item) == "put")
        calls = tuple(item for item in contracts if _option_kind(item) == "call")
        if strategy == "long_straddle":
            calls_by_strike = {item.strike: item for item in calls}
            puts_by_strike = {item.strike: item for item in puts}
            for strike in sorted(set(calls_by_strike) & set(puts_by_strike)):
                yield puts_by_strike[strike], calls_by_strike[strike]
        elif strategy == "long_strangle":
            for put_leg in puts:
                for call_leg in calls:
                    if put_leg.strike < put_leg.spot_price < call_leg.strike:
                        yield put_leg, call_leg
        elif strategy in {"butterfly", "broken_wing_butterfly"}:
            for option_legs in (puts, calls):
                for lower, middle, upper in combinations(option_legs, 3):
                    left_width = middle.strike - lower.strike
                    right_width = upper.strike - middle.strike
                    if (strategy == "butterfly" and left_width == right_width) or (
                        strategy == "broken_wing_butterfly" and left_width != right_width
                    ):
                        yield lower, middle, middle, upper


def _calendar_leg_sets(
    asset_contracts: tuple[OptionContract, ...],
) -> Iterator[tuple[OptionContract, ...]]:
    by_kind_and_strike: dict[tuple[str, float], list[OptionContract]] = {}
    for contract in asset_contracts:
        option_kind = _option_kind(contract)
        if option_kind is not None:
            by_kind_and_strike.setdefault((option_kind, contract.strike), []).append(contract)
    for contracts in by_kind_and_strike.values():
        ordered = tuple(sorted(contracts, key=lambda item: (_as_utc(item.expiry_at), item.symbol)))
        for near, far in combinations(ordered, 2):
            if _as_utc(near.expiry_at) < _as_utc(far.expiry_at):
                yield near, far


def _scan_underlying_overlays(
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    """Scan option overlays that assume an existing spot position."""

    for strategy in request.strategies:
        if strategy not in _OVERLAY_STRATEGIES:
            continue
        expected_kind = "put" if strategy == "protective_put" else "call"
        matching = tuple(item for item in asset_contracts if _option_kind(item) == expected_kind)
        if not matching and asset_contracts:
            representative = min(asset_contracts, key=_contract_order)
            rejections.append(
                _multi_leg_rejection(
                    strategy,
                    (representative,),
                    ("missing_option_type",),
                    (
                        f"No {expected_kind} contracts were available for {strategy.replace('_', ' ')}",
                    ),
                )
            )
        for contract in matching:
            _scan_overlay_candidate(
                strategy,
                contract,
                asset_contracts,
                request,
                valuation_time,
                opportunities,
                rejections,
            )


def _scan_overlay_candidate(
    strategy: str,
    candidate: OptionContract,
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    rejection = _precheck(candidate, request, valuation_time, check_strategy=False)
    if rejection:
        rejections.append(
            _rejection(
                candidate,
                rejection.reasons,
                rejection.messages,
                strategy=strategy,
            )
        )
        return
    position = 1 if strategy == "protective_put" else -1
    try:
        surface = build_volatility_surface(
            _surface_observations(
                asset_contracts,
                excluded_symbols={candidate.symbol},
                allow_unquoted=request.valuation_mode in {"theoretical", "synthetic"},
            ),
            valuation_time=_as_utc(valuation_time),
            config=request.surface_config,
        ).surface_for(candidate.asset)
        valued = price_fair_value(
            FairValueRequest(
                option_type=candidate.option_type,
                spot=candidate.spot_price,
                strike=candidate.strike,
                expiry=_as_utc(candidate.expiry_at),
                valuation_time=_as_utc(valuation_time),
                iv=None,
                risk_free_rate=request.risk_free_rate,
                surface=surface,
                prefer_observed_surface=False,
            )
        )
    except (PricingValidationError, VolatilitySurfaceError, ValueError, KeyError) as exc:
        rejections.append(
            _rejection(candidate, ("surface_or_pricing_failed",), (str(exc),), strategy=strategy)
        )
        return

    if request.valuation_mode in {"theoretical", "synthetic"}:
        _append_theoretical_multi_leg(
            strategy,
            (candidate,),
            (position,),
            (valued,),
            request,
            valuation_time,
            opportunities,
            rejections,
            requires_underlying_position=True,
            risk_note=(
                (
                    "Synthetic valuation only; protective put requires an existing spot/perpetual position."
                    if request.valuation_mode == "synthetic"
                    else "Theoretical valuation only; protective put requires an existing spot/perpetual position."
                )
                if strategy == "protective_put"
                else (
                    "Synthetic valuation only; covered call requires an existing spot/perpetual position."
                    if request.valuation_mode == "synthetic"
                    else "Theoretical valuation only; covered call requires an existing spot/perpetual position."
                )
            ),
        )
        return

    scale = request.quantity * request.contract_multiplier
    entry_unit = candidate.ask_price if position > 0 else -candidate.bid_price
    fair_unit = valued.fair_price * position
    entry = entry_unit * scale
    fair_price = fair_unit * scale
    entry_fee = request.fee_per_contract * scale
    exit_fee = request.fee_per_contract * scale
    entry_slippage = (
        abs(candidate.ask_price if position > 0 else candidate.bid_price)
        * request.slippage_bps
        / 10_000.0
        * scale
    )
    exit_slippage = (
        abs(candidate.bid_price if position > 0 else candidate.ask_price)
        * request.slippage_bps
        / 10_000.0
        * scale
    )
    total_cost = entry_fee + exit_fee + entry_slippage + exit_slippage
    edge = fair_price - entry - total_cost
    if strategy == "covered_call":
        edge = entry * -1 - valued.fair_price * scale - total_cost
    max_loss = (
        max(0.0, entry + entry_fee + entry_slippage) if strategy == "protective_put" else math.inf
    )
    max_profit = (
        math.inf if strategy == "protective_put" else max(0.0, -entry - entry_fee - entry_slippage)
    )
    reasons: list[str] = []
    messages: list[str] = []
    iv_edge = valued.fair_iv - candidate.mark_iv
    if strategy == "covered_call":
        iv_edge = candidate.mark_iv - valued.fair_iv
    if iv_edge < request.min_iv_edge:
        reasons.append("iv_edge_below_minimum")
        messages.append(f"IV edge {iv_edge:.6f} is below {request.min_iv_edge:.6f}")
    if edge <= request.min_edge_after_costs:
        reasons.append("edge_after_costs_below_minimum")
        messages.append(
            f"Edge after costs {edge:.6f} is not above {request.min_edge_after_costs:.6f}"
        )
    if request.max_loss is not None and max_loss > request.max_loss:
        reasons.append("max_loss_exceeded")
        messages.append(f"Maximum loss {max_loss:.6f} exceeds {request.max_loss:.6f}")
    if not request.include_unvalidated:
        reasons.append("evidence_not_validated")
        messages.append("Historical out-of-sample evidence is not available")
    if reasons:
        rejections.append(_rejection(candidate, tuple(reasons), tuple(messages), strategy=strategy))
        return

    opportunities.append(
        Opportunity(
            asset=candidate.asset,
            symbol=candidate.symbol,
            strategy=strategy,  # type: ignore[arg-type]
            option_type=candidate.option_type,
            strike=candidate.strike,
            expiry_at=_as_utc(candidate.expiry_at),
            dte=_dte(candidate.expiry_at, valuation_time),
            spot_price=candidate.spot_price,
            bid_price=(candidate.bid_price if position > 0 else -candidate.ask_price) * scale,
            ask_price=(candidate.ask_price if position > 0 else -candidate.bid_price) * scale,
            market_mid=position * (candidate.bid_price + candidate.ask_price) / 2.0 * scale,
            market_iv=candidate.mark_iv,
            fair_iv=valued.fair_iv,
            iv_edge=iv_edge,
            surface_status=valued.surface_status or "unknown",
            fair_price=fair_price,
            executable_entry=entry,
            fee=entry_fee,
            slippage_cost=entry_slippage,
            edge_after_costs=edge,
            edge_pct=edge / max(abs(entry), 1e-12),
            max_loss=max_loss,
            max_profit=max_profit,
            delta=position * valued.delta * scale,
            volume_24h=candidate.volume_24h,
            open_interest=candidate.open_interest,
            quote_timestamp=_as_utc(candidate.quote_timestamp),
            evidence_status="insufficient_evidence",
            edge_source="fitted_surface_overlay_minus_executable_entry_after_costs",
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            entry_slippage_cost=entry_slippage,
            exit_slippage_cost=exit_slippage,
            total_cost=total_cost,
            long_symbol=candidate.symbol if position > 0 else None,
            short_symbol=candidate.symbol if position < 0 else None,
            long_strike=candidate.strike if position > 0 else None,
            short_strike=candidate.strike if position < 0 else None,
            requires_underlying_position=True,
            risk_note=(
                "Requires an existing spot/perpetual holding; the scanner prices the put hedge only."
                if strategy == "protective_put"
                else "Requires an existing spot/perpetual holding; covered-call risk depends on its entry price."
            ),
            legs=(
                OpportunityLeg(
                    symbol=candidate.symbol,
                    option_type=candidate.option_type,
                    strike=candidate.strike,
                    expiry_at=_as_utc(candidate.expiry_at),
                    spot_price=candidate.spot_price,
                    bid_price=candidate.bid_price,
                    ask_price=candidate.ask_price,
                    market_iv=candidate.mark_iv,
                    fair_iv=valued.fair_iv,
                    fair_price=valued.fair_price,
                    delta=valued.delta,
                    volume_24h=candidate.volume_24h,
                    open_interest=candidate.open_interest,
                    quote_timestamp=_as_utc(candidate.quote_timestamp),
                    position=position,
                ),
            ),
        )
    )


def _iron_condor_leg_sets(
    contracts: tuple[OptionContract, ...],
) -> Iterator[tuple[OptionContract, ...]]:
    puts = tuple(
        sorted((item for item in contracts if _option_kind(item) == "put"), key=_contract_order)
    )
    calls = tuple(
        sorted((item for item in contracts if _option_kind(item) == "call"), key=_contract_order)
    )
    for put_wing, short_put in combinations(puts, 2):
        for short_call, call_wing in combinations(calls, 2):
            if put_wing.strike < short_put.strike < short_call.strike < call_wing.strike:
                yield (put_wing, short_put, short_call, call_wing)


def _iron_butterfly_leg_sets(
    contracts: tuple[OptionContract, ...],
) -> Iterator[tuple[OptionContract, ...]]:
    puts = tuple(
        sorted((item for item in contracts if _option_kind(item) == "put"), key=_contract_order)
    )
    calls = tuple(
        sorted((item for item in contracts if _option_kind(item) == "call"), key=_contract_order)
    )
    calls_by_strike = {item.strike: item for item in calls}
    puts_by_strike = {item.strike: item for item in puts}
    body_strikes = sorted(set(calls_by_strike) & set(puts_by_strike))
    for body_strike in body_strikes:
        short_put = puts_by_strike[body_strike]
        short_call = calls_by_strike[body_strike]
        for put_wing in puts:
            if put_wing.strike >= body_strike:
                break
            for call_wing in calls:
                if call_wing.strike > body_strike:
                    yield (put_wing, short_put, short_call, call_wing)


def _scan_multi_leg_candidate(
    strategy: str,
    legs: tuple[OptionContract, ...],
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    leg_rejections = [_precheck(leg, request, valuation_time, check_strategy=False) for leg in legs]
    if any(leg_rejections):
        reasons: list[str] = []
        messages: list[str] = []
        for index, rejection in enumerate(leg_rejections, start=1):
            if rejection is None:
                continue
            leg_reasons, leg_messages = _prefixed_leg_reasons(f"leg_{index}", rejection)
            reasons.extend(leg_reasons)
            messages.extend(leg_messages)
        rejections.append(_multi_leg_rejection(strategy, legs, tuple(reasons), tuple(messages)))
        return

    excluded = {leg.symbol for leg in legs}
    try:
        surface = build_volatility_surface(
            _surface_observations(
                asset_contracts,
                excluded_symbols=excluded,
                allow_unquoted=request.valuation_mode in {"theoretical", "synthetic"},
            ),
            valuation_time=_as_utc(valuation_time),
            config=request.surface_config,
        ).surface_for(legs[0].asset)
        valued = tuple(
            price_fair_value(
                FairValueRequest(
                    option_type=leg.option_type,
                    spot=leg.spot_price,
                    strike=leg.strike,
                    expiry=_as_utc(leg.expiry_at),
                    valuation_time=_as_utc(valuation_time),
                    iv=None,
                    risk_free_rate=request.risk_free_rate,
                    surface=surface,
                    prefer_observed_surface=False,
                )
            )
            for leg in legs
        )
    except (PricingValidationError, VolatilitySurfaceError, ValueError, KeyError) as exc:
        rejections.append(
            _multi_leg_rejection(
                strategy,
                legs,
                ("surface_or_pricing_failed",),
                (str(exc),),
            )
        )
        return

    if request.valuation_mode in {"theoretical", "synthetic"}:
        _append_theoretical_multi_leg(
            strategy,
            legs,
            _positions_for(strategy, legs),
            valued,
            request,
            valuation_time,
            opportunities,
            rejections,
            )
        return

    scale = request.quantity * request.contract_multiplier
    entry_unit = sum(
        (leg.ask_price if position > 0 else -leg.bid_price)
        for leg, position in zip(legs, _positions_for(strategy, legs))
    )
    fair_unit = sum(
        position * value.fair_price
        for position, value in zip(_positions_for(strategy, legs), valued)
    )
    market_mid_unit = sum(
        position * (leg.bid_price + leg.ask_price) / 2.0
        for position, leg in zip(_positions_for(strategy, legs), legs)
    )
    bid_unit = sum(
        (leg.bid_price if position > 0 else -leg.ask_price)
        for position, leg in zip(_positions_for(strategy, legs), legs)
    )
    ask_unit = entry_unit
    entry = entry_unit * scale
    entry_fee = request.fee_per_contract * len(legs) * scale
    exit_fee = request.fee_per_contract * len(legs) * scale
    entry_slippage = sum(
        abs(leg.ask_price if position > 0 else leg.bid_price)
        * request.slippage_bps
        / 10_000.0
        * scale
        for position, leg in zip(_positions_for(strategy, legs), legs)
    )
    exit_slippage = sum(
        abs(leg.bid_price if position > 0 else leg.ask_price)
        * request.slippage_bps
        / 10_000.0
        * scale
        for position, leg in zip(_positions_for(strategy, legs), legs)
    )
    total_cost = entry_fee + exit_fee + entry_slippage + exit_slippage
    fair_price = fair_unit * scale
    edge = fair_price - entry - total_cost
    iv_edge = sum(
        position * (value.fair_iv - leg.mark_iv)
        for position, value, leg in zip(_positions_for(strategy, legs), valued, legs)
    )
    max_loss, max_profit, breakevens = _multi_leg_payoff_bounds(
        legs,
        _positions_for(strategy, legs),
        entry,
        entry_fee,
        entry_slippage,
        scale,
        strategy,
    )
    reasons: list[str] = []
    messages: list[str] = []
    if iv_edge < request.min_iv_edge:
        reasons.append("iv_edge_below_minimum")
        messages.append(f"IV edge {iv_edge:.6f} is below {request.min_iv_edge:.6f}")
    if edge <= request.min_edge_after_costs:
        reasons.append("edge_after_costs_below_minimum")
        messages.append(
            f"Edge after costs {edge:.6f} is not above {request.min_edge_after_costs:.6f}"
        )
    if request.max_loss is not None and max_loss > request.max_loss:
        reasons.append("max_loss_exceeded")
        messages.append(f"Maximum loss {max_loss:.6f} exceeds {request.max_loss:.6f}")
    if not request.include_unvalidated:
        reasons.append("evidence_not_validated")
        messages.append("Historical out-of-sample evidence is not available")
    if reasons:
        rejections.append(_multi_leg_rejection(strategy, legs, tuple(reasons), tuple(messages)))
        return

    positions = _positions_for(strategy, legs)
    long_leg = next((leg for leg, position in zip(legs, positions) if position > 0), legs[0])
    short_leg = next((leg for leg, position in zip(legs, positions) if position < 0), None)
    opportunities.append(
        Opportunity(
            asset=legs[0].asset,
            symbol="/".join(leg.symbol for leg in legs),
            strategy=strategy,  # type: ignore[arg-type]
            option_type="multi",
            strike=min(leg.strike for leg in legs),
            expiry_at=_as_utc(legs[0].expiry_at),
            dte=_dte(legs[0].expiry_at, valuation_time),
            spot_price=legs[0].spot_price,
            bid_price=bid_unit * scale,
            ask_price=ask_unit * scale,
            market_mid=market_mid_unit * scale,
            market_iv=sum(position * leg.mark_iv for position, leg in zip(positions, legs)),
            fair_iv=sum(position * value.fair_iv for position, value in zip(positions, valued)),
            iv_edge=iv_edge,
            surface_status=_surface_status(*(value.surface_status for value in valued)),
            fair_price=fair_price,
            executable_entry=entry,
            fee=entry_fee,
            slippage_cost=entry_slippage,
            edge_after_costs=edge,
            edge_pct=edge / max(abs(entry), 1e-12),
            max_loss=max_loss,
            max_profit=max_profit,
            delta=sum(position * value.delta for position, value in zip(positions, valued)) * scale,
            volume_24h=min(leg.volume_24h for leg in legs),
            open_interest=min(leg.open_interest for leg in legs),
            quote_timestamp=max(_as_utc(leg.quote_timestamp) for leg in legs),
            evidence_status="insufficient_evidence",
            edge_source="fitted_surface_multi_leg_minus_executable_entry_after_costs",
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            entry_slippage_cost=entry_slippage,
            exit_slippage_cost=exit_slippage,
            total_cost=total_cost,
            long_symbol=long_leg.symbol,
            short_symbol=short_leg.symbol if short_leg is not None else None,
            long_strike=long_leg.strike if long_leg is not None else None,
            short_strike=short_leg.strike if short_leg is not None else None,
            legs=tuple(
                OpportunityLeg(
                    symbol=leg.symbol,
                    option_type=leg.option_type,
                    strike=leg.strike,
                    expiry_at=_as_utc(leg.expiry_at),
                    spot_price=leg.spot_price,
                    bid_price=leg.bid_price,
                    ask_price=leg.ask_price,
                    market_iv=leg.mark_iv,
                    fair_iv=value.fair_iv,
                    fair_price=value.fair_price,
                    delta=value.delta,
                    volume_24h=leg.volume_24h,
                    open_interest=leg.open_interest,
                    quote_timestamp=_as_utc(leg.quote_timestamp),
                    position=position,
                )
                for leg, value, position in zip(legs, valued, positions)
            ),
            breakevens=breakevens,
        )
    )


def _positions_for(strategy: str, legs: tuple[OptionContract, ...]) -> tuple[int, ...]:
    if strategy == "iron_condor":
        return (1, -1, -1, 1)
    if strategy == "iron_butterfly":
        return (1, -1, -1, 1)
    if strategy in {"long_straddle", "long_strangle"}:
        return (1, 1)
    if strategy == "calendar_spread":
        return (-1, 1)
    if strategy in {"butterfly", "broken_wing_butterfly"}:
        return (1, -1, -1, 1)
    raise ValueError(f"unsupported multi-leg strategy: {strategy}")


def _multi_leg_payoff_bounds(
    legs: tuple[OptionContract, ...],
    positions: tuple[int, ...],
    entry: float,
    entry_fee: float,
    entry_slippage: float,
    scale: float,
    strategy: str,
) -> tuple[float, float, tuple[float, ...]]:
    net_debit = entry + entry_fee + entry_slippage
    if strategy == "calendar_spread":
        return max(0.0, net_debit), math.inf, ()
    strikes = sorted({leg.strike for leg in legs})
    width = max(strikes[-1] - strikes[0], 1.0)
    points = [0.0, *strikes, strikes[-1] + width * 2.0]
    values = tuple(
        _multi_leg_expiry_pnl(price, legs, positions, net_debit, scale) for price in points
    )
    breakevens: list[float] = []
    for left, right, left_value, right_value in zip(points, points[1:], values, values[1:]):
        if left_value == 0:
            breakevens.append(left)
        if left_value * right_value < 0 and right_value != left_value:
            breakevens.append(left - left_value * (right - left) / (right_value - left_value))
    if values[-1] == 0:
        breakevens.append(points[-1])
    unique_breakevens = tuple(
        sorted(
            value
            for index, value in enumerate(sorted(breakevens))
            if index == 0 or abs(value - sorted(breakevens)[index - 1]) > 1e-9
        )
    )
    max_profit = (
        math.inf if strategy in {"long_straddle", "long_strangle"} else max(0.0, max(values))
    )
    return max(0.0, -min(values)), max_profit, unique_breakevens


def _multi_leg_expiry_pnl(
    price: float,
    legs: tuple[OptionContract, ...],
    positions: tuple[int, ...],
    net_debit: float,
    scale: float,
) -> float:
    intrinsic = 0.0
    for leg, position in zip(legs, positions):
        if _option_kind(leg) == "call":
            intrinsic += position * max(price - leg.strike, 0.0)
        else:
            intrinsic += position * max(leg.strike - price, 0.0)
    return intrinsic * scale - net_debit


def _multi_leg_rejection(
    strategy: str,
    legs: tuple[OptionContract, ...],
    reasons: tuple[str, ...],
    messages: tuple[str, ...],
) -> RejectedCandidate:
    first = legs[0]
    positions = _positions_for(strategy, legs) if len(legs) == 4 else ()
    long_symbol = next(
        (leg.symbol for leg, position in zip(legs, positions) if position > 0),
        None,
    )
    short_symbol = next(
        (leg.symbol for leg, position in zip(legs, positions) if position < 0),
        None,
    )
    return RejectedCandidate(
        asset=first.asset,
        symbol=f"{strategy}:" + "/".join(leg.symbol for leg in legs),
        option_type=first.option_type,
        strike=first.strike,
        expiry_at=_as_utc(first.expiry_at),
        reasons=tuple(dict.fromkeys(reasons)),
        messages=messages or tuple(_filter_messages(list(reasons))),
        quote_timestamp=max(_as_utc(leg.quote_timestamp) for leg in legs),
        strategy=strategy,  # type: ignore[arg-type]
        long_symbol=long_symbol,
        short_symbol=short_symbol,
    )


def _scan_vertical_pair(
    strategy: str,
    long_leg: OptionContract,
    short_leg: OptionContract,
    asset_contracts: tuple[OptionContract, ...],
    request: ScanRequest,
    valuation_time: datetime,
    opportunities: list[Opportunity],
    rejections: list[RejectedCandidate],
) -> None:
    """Value one executable long/short vertical pair."""

    try:
        excluded = {long_leg.symbol, short_leg.symbol}
        surface = build_volatility_surface(
            _surface_observations(
                asset_contracts,
                excluded_symbols=excluded,
                allow_unquoted=request.valuation_mode in {"theoretical", "synthetic"},
            ),
            valuation_time=_as_utc(valuation_time),
            config=request.surface_config,
        ).surface_for(long_leg.asset)
        long_valued = price_fair_value(
            FairValueRequest(
                option_type=long_leg.option_type,
                spot=long_leg.spot_price,
                strike=long_leg.strike,
                expiry=_as_utc(long_leg.expiry_at),
                valuation_time=_as_utc(valuation_time),
                iv=None,
                risk_free_rate=request.risk_free_rate,
                surface=surface,
                prefer_observed_surface=False,
            )
        )
        short_valued = price_fair_value(
            FairValueRequest(
                option_type=short_leg.option_type,
                spot=short_leg.spot_price,
                strike=short_leg.strike,
                expiry=_as_utc(short_leg.expiry_at),
                valuation_time=_as_utc(valuation_time),
                iv=None,
                risk_free_rate=request.risk_free_rate,
                surface=surface,
                prefer_observed_surface=False,
            )
        )
    except (PricingValidationError, VolatilitySurfaceError, ValueError, KeyError) as exc:
        rejections.append(
            _vertical_rejection(
                strategy,
                long_leg,
                short_leg,
                ("surface_or_pricing_failed",),
                (str(exc),),
            )
        )
        return

    if request.valuation_mode in {"theoretical", "synthetic"}:
        _append_theoretical_multi_leg(
            strategy,
            (long_leg, short_leg),
            (1, -1),
            (long_valued, short_valued),
            request,
            valuation_time,
            opportunities,
            rejections,
            )
        return

    scale = request.quantity * request.contract_multiplier
    entry = (long_leg.ask_price - short_leg.bid_price) * scale
    fair_price = long_valued.fair_price - short_valued.fair_price
    entry_fee = request.fee_per_contract * 2.0 * scale
    exit_fee = request.fee_per_contract * 2.0 * scale
    entry_slippage = (
        (long_leg.ask_price + short_leg.bid_price) * request.slippage_bps / 10_000.0 * scale
    )
    # Closing a vertical buys back the short at ask and sells the long at bid.
    exit_slippage = (
        (long_leg.bid_price + short_leg.ask_price) * request.slippage_bps / 10_000.0 * scale
    )
    total_cost = entry_fee + exit_fee + entry_slippage + exit_slippage
    edge = fair_price * scale - entry - total_cost
    max_loss, max_profit = _vertical_payoff_bounds(
        strategy,
        long_leg,
        short_leg,
        entry,
        entry_fee,
        entry_slippage,
        scale,
    )
    iv_edge = (long_valued.fair_iv - short_valued.fair_iv) - (long_leg.mark_iv - short_leg.mark_iv)
    reasons: list[str] = []
    messages: list[str] = []
    if iv_edge < request.min_iv_edge:
        reasons.append("iv_edge_below_minimum")
        messages.append(f"IV edge {iv_edge:.6f} is below {request.min_iv_edge:.6f}")
    if edge <= request.min_edge_after_costs:
        reasons.append("edge_after_costs_below_minimum")
        messages.append(
            f"Edge after costs {edge:.6f} is not above {request.min_edge_after_costs:.6f}"
        )
    if request.max_loss is not None and max_loss > request.max_loss:
        reasons.append("max_loss_exceeded")
        messages.append(f"Maximum loss {max_loss:.6f} exceeds {request.max_loss:.6f}")
    if not request.include_unvalidated:
        reasons.append("evidence_not_validated")
        messages.append("Historical out-of-sample evidence is not available")
    if reasons:
        rejections.append(
            _vertical_rejection(
                strategy,
                long_leg,
                short_leg,
                tuple(reasons),
                tuple(messages),
            )
        )
        return

    quote_timestamp = max(_as_utc(long_leg.quote_timestamp), _as_utc(short_leg.quote_timestamp))
    opportunities.append(
        Opportunity(
            asset=long_leg.asset,
            symbol=_vertical_symbol(long_leg, short_leg),
            strategy=strategy,  # type: ignore[arg-type]
            option_type=long_leg.option_type,
            strike=long_leg.strike,
            expiry_at=_as_utc(long_leg.expiry_at),
            dte=_dte(long_leg.expiry_at, valuation_time),
            spot_price=long_leg.spot_price,
            bid_price=(long_leg.bid_price - short_leg.ask_price) * scale,
            ask_price=(long_leg.ask_price - short_leg.bid_price) * scale,
            market_mid=(
                long_leg.bid_price + long_leg.ask_price - short_leg.bid_price - short_leg.ask_price
            )
            / 2.0
            * scale,
            market_iv=long_leg.mark_iv - short_leg.mark_iv,
            fair_iv=long_valued.fair_iv - short_valued.fair_iv,
            iv_edge=iv_edge,
            surface_status=_surface_status(long_valued.surface_status, short_valued.surface_status),
            fair_price=fair_price,
            executable_entry=entry,
            fee=entry_fee,
            slippage_cost=entry_slippage,
            edge_after_costs=edge,
            edge_pct=edge / max(abs(entry), 1e-12),
            max_loss=max_loss,
            max_profit=max_profit,
            delta=(long_valued.delta - short_valued.delta) * scale,
            volume_24h=min(long_leg.volume_24h, short_leg.volume_24h),
            open_interest=min(long_leg.open_interest, short_leg.open_interest),
            quote_timestamp=quote_timestamp,
            evidence_status="insufficient_evidence",
            edge_source="fitted_surface_net_vertical_minus_executable_entry_after_costs",
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            entry_slippage_cost=entry_slippage,
            exit_slippage_cost=exit_slippage,
            total_cost=total_cost,
            long_symbol=long_leg.symbol,
            short_symbol=short_leg.symbol,
            long_strike=long_leg.strike,
            short_strike=short_leg.strike,
            legs=(
                OpportunityLeg(
                    symbol=long_leg.symbol,
                    option_type=long_leg.option_type,
                    strike=long_leg.strike,
                    expiry_at=_as_utc(long_leg.expiry_at),
                    spot_price=long_leg.spot_price,
                    bid_price=long_leg.bid_price,
                    ask_price=long_leg.ask_price,
                    market_iv=long_leg.mark_iv,
                    fair_iv=long_valued.fair_iv,
                    fair_price=long_valued.fair_price,
                    delta=long_valued.delta * scale,
                    volume_24h=long_leg.volume_24h,
                    open_interest=long_leg.open_interest,
                    quote_timestamp=_as_utc(long_leg.quote_timestamp),
                    position=1,
                ),
                OpportunityLeg(
                    symbol=short_leg.symbol,
                    option_type=short_leg.option_type,
                    strike=short_leg.strike,
                    expiry_at=_as_utc(short_leg.expiry_at),
                    spot_price=short_leg.spot_price,
                    bid_price=short_leg.bid_price,
                    ask_price=short_leg.ask_price,
                    market_iv=short_leg.mark_iv,
                    fair_iv=short_valued.fair_iv,
                    fair_price=short_valued.fair_price,
                    delta=short_valued.delta * scale,
                    volume_24h=short_leg.volume_24h,
                    open_interest=short_leg.open_interest,
                    quote_timestamp=_as_utc(short_leg.quote_timestamp),
                    position=-1,
                ),
            ),
        )
    )


def _vertical_payoff_bounds(
    strategy: str,
    long_leg: OptionContract,
    short_leg: OptionContract,
    entry: float,
    entry_fee: float,
    entry_slippage: float,
    scale: float,
) -> tuple[float, float]:
    """Return bounded expiry loss/profit after opening costs."""

    net_debit = entry + entry_fee + entry_slippage
    width = abs(long_leg.strike - short_leg.strike) * scale
    if strategy in {"bull_call_vertical", "bear_put_vertical"}:
        return max(0.0, net_debit), max(0.0, width - net_debit)
    return max(0.0, width + net_debit), max(0.0, -net_debit)


def _single_leg_max_profit(
    candidate: OptionContract,
    opening_costs: float,
    scale: float,
) -> float:
    premium = candidate.ask_price * scale + opening_costs
    if _option_kind(candidate) == "call":
        return math.inf
    return max(0.0, candidate.strike * scale - premium)


def _vertical_legs(
    strategy: str,
    first: OptionContract,
    second: OptionContract,
) -> tuple[OptionContract, OptionContract]:
    lower, higher = sorted((first, second), key=_contract_order)
    long_is_lower = strategy.startswith("bull_")
    return (lower, higher) if long_is_lower else (higher, lower)


def _vertical_option_type(strategy: str) -> str:
    return "call" if "call" in strategy else "put"


def _option_kind(contract: OptionContract) -> str | None:
    normalized = str(contract.option_type).strip().lower()
    if normalized in {"call", "c"}:
        return "call"
    if normalized in {"put", "p"}:
        return "put"
    return None


def _contract_order(contract: OptionContract) -> tuple[float, str]:
    return (float(contract.strike), contract.symbol)


def _vertical_symbol(long_leg: OptionContract, short_leg: OptionContract) -> str:
    return f"{long_leg.symbol}/{short_leg.symbol}"


def _surface_status(*surface_statuses: str | None) -> str:
    statuses = {status or "unknown" for status in surface_statuses}
    if "extrapolated" in statuses:
        return "extrapolated"
    if "interpolated" in statuses:
        return "interpolated"
    if statuses == {"observed"}:
        return "observed"
    return "+".join(sorted(statuses))


def _prefixed_leg_reasons(
    role: str,
    rejection: RejectedCandidate,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    messages: list[str] = []
    for reason, message in zip(rejection.reasons, rejection.messages):
        reasons.append(reason)
        reasons.append(f"{role}_leg_{reason}")
        if reason == "invalid_market_data":
            reasons.append(f"invalid_{role}_leg")
        messages.append(f"{role.capitalize()} leg: {message}")
    return list(dict.fromkeys(reasons)), messages


def _vertical_rejection(
    strategy: str,
    long_leg: OptionContract,
    short_leg: OptionContract | None,
    reasons: tuple[str, ...],
    messages: tuple[str, ...],
) -> RejectedCandidate:
    symbol = (
        _vertical_symbol(long_leg, short_leg)
        if short_leg is not None
        else f"{strategy}:{long_leg.symbol}"
    )
    deduped_reasons = tuple(dict.fromkeys(reasons))
    return RejectedCandidate(
        asset=long_leg.asset,
        symbol=symbol,
        option_type=long_leg.option_type,
        strike=long_leg.strike,
        expiry_at=_as_utc(long_leg.expiry_at),
        reasons=deduped_reasons,
        messages=messages or tuple(_filter_messages(list(deduped_reasons))),
        quote_timestamp=_as_utc(long_leg.quote_timestamp),
        strategy=strategy,  # type: ignore[arg-type]
        long_symbol=long_leg.symbol,
        short_symbol=short_leg.symbol if short_leg is not None else None,
    )


def _precheck(
    candidate: OptionContract,
    request: ScanRequest,
    valuation_time: datetime,
    *,
    check_strategy: bool = True,
) -> RejectedCandidate | None:
    reasons: list[str] = []
    messages: list[str] = []
    strategy = _strategy_for(candidate)
    numeric_fields = (
        candidate.spot_price,
        candidate.mark_iv,
        candidate.delta,
        candidate.volume_24h,
        candidate.open_interest,
    )
    try:
        finite_market_data = all(math.isfinite(float(value)) for value in numeric_fields)
    except (TypeError, ValueError):
        finite_market_data = False
    quote_values = (candidate.bid_price, candidate.ask_price)
    quote_values_finite = all(
        value is None or math.isfinite(float(value)) for value in quote_values
    )
    quote_is_positive = all(value is not None and value > 0 for value in quote_values)
    quote_is_inverted = (
        candidate.bid_price is not None
        and candidate.ask_price is not None
        and candidate.ask_price < candidate.bid_price
    )
    quote_is_invalid = (
        not quote_values_finite
        or any(value is not None and value < 0 for value in quote_values)
        or quote_is_inverted
    )
    if not finite_market_data or quote_is_invalid:
        reasons.append("invalid_market_data")
        messages.append("Market quote contains a non-finite or invalid value")
    elif candidate.spot_price <= 0 or candidate.mark_iv <= 0:
        reasons.append("invalid_market_data")
        messages.append("Market quote must have a positive spot price and IV")
    elif request.valuation_mode == "executable" and not quote_is_positive:
        reasons.append("invalid_market_data")
        messages.append("Executable valuation requires positive bid and ask")
    if check_strategy and strategy not in request.strategies:
        reasons.append("strategy_not_allowed")
        messages.append(f"Strategy {strategy} was not selected")
    try:
        dte = _dte(candidate.expiry_at, valuation_time)
        strike_is_finite = math.isfinite(float(candidate.strike))
    except (TypeError, ValueError, AttributeError):
        dte = 0.0
        strike_is_finite = False
    if not strike_is_finite or candidate.strike <= 0:
        reasons.append("invalid_market_data")
        messages.append("Option strike must be a positive finite number")
    if finite_market_data and strike_is_finite:
        if request.min_dte is not None and dte < request.min_dte:
            reasons.append("dte_below_minimum")
        if request.max_dte is not None and dte > request.max_dte:
            reasons.append("dte_above_maximum")
        abs_delta = abs(candidate.delta)
        if request.min_delta is not None and abs_delta < request.min_delta:
            reasons.append("delta_below_minimum")
        if request.max_delta is not None and abs_delta > request.max_delta:
            reasons.append("delta_out_of_range")
        if candidate.volume_24h < request.min_volume_24h:
            reasons.append("volume_below_minimum")
        if candidate.open_interest < request.min_open_interest:
            reasons.append("open_interest_below_minimum")
        mid = _positive_quote_mid(candidate.bid_price, candidate.ask_price)
        if request.valuation_mode == "executable":
            if mid is not None:
                spread_pct = (candidate.ask_price - candidate.bid_price) / mid
                if request.max_spread_pct is not None and spread_pct > request.max_spread_pct:
                    reasons.append("spread_above_maximum")
            else:
                reasons.append("invalid_market_data")
                messages.append("Market quote midpoint must be positive")
    if reasons:
        messages.extend(_filter_messages(reasons))
        return _rejection(candidate, tuple(reasons), tuple(messages))
    return None


def _surface_observations(
    contracts: tuple[OptionContract, ...],
    *,
    excluded_symbols: set[str],
    allow_unquoted: bool,
) -> Iterator[VolatilityObservation]:
    for contract in contracts:
        if contract.symbol in excluded_symbols:
            continue
        observation = _to_observation(contract, allow_unquoted=allow_unquoted)
        if observation is not None:
            yield observation


def _to_observation(
    contract: OptionContract,
    *,
    allow_unquoted: bool,
) -> VolatilityObservation | None:
    bid = contract.bid_price if contract.bid_price is not None and contract.bid_price > 0 else None
    ask = contract.ask_price if contract.ask_price is not None and contract.ask_price > 0 else None
    if bid is None or ask is None:
        if not allow_unquoted:
            return None
        bid = None
        ask = None
    return VolatilityObservation(
        asset=contract.asset,
        expiry=_as_utc(contract.expiry_at),
        strike=contract.strike,
        spot=contract.spot_price,
        iv=contract.mark_iv,
        bid=bid,
        ask=ask,
        liquidity=max(contract.volume_24h, contract.open_interest),
    )


def _positive_quote_mid(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2.0


def _strategy_for(contract: OptionContract) -> Strategy:
    return "long_call" if contract.option_type.strip().lower() in {"call", "c"} else "long_put"


def _rejection(
    contract: OptionContract,
    reasons: tuple[str, ...],
    messages: tuple[str, ...],
    *,
    strategy: str | None = None,
) -> RejectedCandidate:
    return RejectedCandidate(
        asset=contract.asset,
        symbol=contract.symbol,
        option_type=contract.option_type,
        strike=contract.strike,
        expiry_at=_as_utc(contract.expiry_at),
        reasons=tuple(dict.fromkeys(reasons)),
        messages=messages,
        quote_timestamp=_as_utc(contract.quote_timestamp),
        strategy=strategy,  # type: ignore[arg-type]
    )


def _filter_messages(reasons: list[str]) -> list[str]:
    return [reason.replace("_", " ") for reason in reasons]


def _failure_message(asset: str, code: str, issues: tuple[OptionDataQualityIssue, ...]) -> str:
    for issue in issues:
        if issue.code == code:
            return issue.message
    return f"No usable option contracts were available for {asset}"


def _dte(expiry: datetime | date, valuation_time: datetime | date) -> float:
    return (_as_utc(expiry) - _as_utc(valuation_time)).total_seconds() / 86_400.0


def _as_utc(value: datetime | date) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _finite(name: str, value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


__all__ = [
    "AssetScanFailure",
    "Opportunity",
    "OpportunityLeg",
    "RejectedCandidate",
    "ScanRequest",
    "ScanResult",
    "ValuationMode",
    "scan_opportunities",
]
