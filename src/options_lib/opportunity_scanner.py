"""Read-only, multi-asset option opportunity scanning.

The public seam is :func:`scan_opportunities`.  It fits a volatility surface
without the candidate being scored, values the candidate at that fitted IV,
and only returns defined-risk long option ideas whose executable entry still
has positive model edge after costs.  This is a research signal, not an EV
validation or an order instruction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionContract,
    OptionDataQualityIssue,
)

from .pricing import FairValueRequest, PricingValidationError, price_fair_value
from .volatility_surface import (
    SurfaceConfig,
    VolatilityObservation,
    VolatilitySurfaceError,
    build_volatility_surface,
)

Strategy = Literal["long_call", "long_put"]
EvidenceStatus = Literal["not_validated", "insufficient_evidence"]


@dataclass(frozen=True)
class ScanRequest:
    """Filters and cost assumptions for one deterministic scan.

    Rates, IVs, and slippage are decimals or basis points as named.  A scan
    never invents a rate or IV.  Only long calls and long puts are supported in
    this ticket; both have a bounded loss and neither can create a naked short.
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
    quantity: float = 1.0
    contract_multiplier: float = 1.0
    include_unvalidated: bool = True
    strategies: tuple[str, ...] = ("long_call", "long_put")
    max_results: int | None = None
    surface_config: SurfaceConfig | None = None

    def __post_init__(self) -> None:
        _finite("risk_free_rate", self.risk_free_rate)
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
        if self.min_delta is not None and self.max_delta is not None and self.min_delta > self.max_delta:
            raise ValueError("min_delta cannot exceed max_delta")
        if self.max_delta is not None and self.max_delta > 1:
            raise ValueError("max_delta cannot exceed 1")
        if self.max_spread_pct is not None and self.max_spread_pct > 1:
            raise ValueError("max_spread_pct cannot exceed 1")
        if self.max_results is not None and self.max_results < 1:
            raise ValueError("max_results must be positive")
        if self.quantity <= 0 or self.contract_multiplier <= 0:
            raise ValueError("quantity and contract_multiplier must be positive")
        normalized_assets = tuple(sorted({str(asset).strip().upper() for asset in self.assets if str(asset).strip()}))
        normalized_strategies = tuple(dict.fromkeys(str(strategy).strip().lower() for strategy in self.strategies))
        unsupported = set(normalized_strategies) - set(_SUPPORTED_STRATEGIES)
        if unsupported:
            raise ValueError(
                "unsupported strategy; naked short and order-placement strategies are not allowed"
            )
        object.__setattr__(self, "assets", normalized_assets)
        object.__setattr__(self, "strategies", normalized_strategies)


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
    bid_price: float
    ask_price: float
    market_mid: float
    market_iv: float
    fair_iv: float
    iv_edge: float
    surface_status: str
    fair_price: float
    executable_entry: float
    fee: float
    slippage_cost: float
    edge_after_costs: float
    edge_pct: float
    max_loss: float
    delta: float
    volume_24h: float
    open_interest: float
    quote_timestamp: datetime
    evidence_status: EvidenceStatus
    expected_value_status: Literal["not_validated"] = "not_validated"
    edge_source: str = "fitted_surface_minus_executable_entry_after_costs"
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    entry_slippage_cost: float = 0.0
    exit_slippage_cost: float = 0.0
    total_cost: float = 0.0
    execution_allowed: bool = False


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


_SUPPORTED_STRATEGIES = ("long_call", "long_put")


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
    discovered_assets = {asset.base_coin.upper() for asset in universe.assets}
    discovered_assets.update(contracts_by_asset)
    selected_assets = request.assets or tuple(sorted(discovered_assets))
    opportunities: list[Opportunity] = []
    rejections: list[RejectedCandidate] = []
    failures: list[AssetScanFailure] = []

    for asset in selected_assets:
        asset_contracts = tuple(
            sorted(
                contracts_by_asset.get(asset, ()),
                key=lambda item: (_as_utc(item.expiry_at), item.strike, item.option_type, item.symbol),
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
            failures.append(AssetScanFailure(asset, code, _failure_message(asset, code, asset_issues)))
            continue

        for candidate in asset_contracts:
            rejection = _precheck(candidate, request, universe.valuation_time)
            if rejection:
                rejections.append(rejection)
                continue
            try:
                surface = build_volatility_surface(
                    (_to_observation(contract) for contract in asset_contracts if contract.symbol != candidate.symbol),
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
                messages.append(f"Edge after costs {edge:.6f} is not above {request.min_edge_after_costs:.6f}")
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
                    delta=candidate.delta,
                    volume_24h=candidate.volume_24h,
                    open_interest=candidate.open_interest,
                    quote_timestamp=_as_utc(candidate.quote_timestamp),
                    evidence_status="insufficient_evidence",
                    entry_fee=entry_fee,
                    exit_fee=exit_fee,
                    entry_slippage_cost=entry_slippage,
                    exit_slippage_cost=exit_slippage,
                    total_cost=total_cost,
                )
            )

    opportunities.sort(key=lambda item: (-item.edge_after_costs, -item.iv_edge, item.asset, item.symbol))
    if request.max_results is not None:
        opportunities = opportunities[: request.max_results]
    return ScanResult(
        timestamp=_as_utc(universe.valuation_time),
        data_timestamp=min(
            (_as_utc(contract.quote_timestamp) for contract in universe.contracts),
            default=_as_utc(universe.valuation_time),
        ),
        opportunities=tuple(opportunities),
        rejections=tuple(sorted(rejections, key=lambda item: (item.asset, _as_utc(item.expiry_at), item.strike, item.symbol))),
        asset_failures=tuple(sorted(failures, key=lambda item: (item.asset, item.code))),
        issues=tuple(sorted(universe.issues, key=lambda item: (item.asset or "", item.code, item.symbol or ""))),
        evidence_gate_status="open_unvalidated_signals" if request.include_unvalidated else "blocked_unvalidated",
        execution_allowed=False,
    )


def _precheck(
    candidate: OptionContract,
    request: ScanRequest,
    valuation_time: datetime,
) -> RejectedCandidate | None:
    reasons: list[str] = []
    messages: list[str] = []
    strategy = _strategy_for(candidate)
    numeric_fields = (
        candidate.spot_price,
        candidate.mark_iv,
        candidate.bid_price,
        candidate.ask_price,
        candidate.delta,
        candidate.volume_24h,
        candidate.open_interest,
    )
    try:
        finite_market_data = all(math.isfinite(float(value)) for value in numeric_fields)
    except (TypeError, ValueError):
        finite_market_data = False
    if not finite_market_data:
        reasons.append("invalid_market_data")
        messages.append("Market quote contains a non-finite value")
    elif (
        candidate.spot_price <= 0
        or candidate.mark_iv <= 0
        or candidate.bid_price <= 0
        or candidate.ask_price <= 0
        or candidate.ask_price < candidate.bid_price
    ):
        reasons.append("invalid_market_data")
        messages.append("Market quote must have positive prices and a non-inverted spread")
    if strategy not in request.strategies:
        reasons.append("strategy_not_allowed")
        messages.append(f"Strategy {strategy} was not selected")
    dte = _dte(candidate.expiry_at, valuation_time)
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
    mid = (candidate.bid_price + candidate.ask_price) / 2.0
    spread_pct = (candidate.ask_price - candidate.bid_price) / mid
    if request.max_spread_pct is not None and spread_pct > request.max_spread_pct:
        reasons.append("spread_above_maximum")
    if reasons:
        messages.extend(_filter_messages(reasons))
        return _rejection(candidate, tuple(reasons), tuple(messages))
    return None


def _to_observation(contract: OptionContract) -> VolatilityObservation:
    return VolatilityObservation(
        asset=contract.asset,
        expiry=_as_utc(contract.expiry_at),
        strike=contract.strike,
        spot=contract.spot_price,
        iv=contract.mark_iv,
        bid=contract.bid_price,
        ask=contract.ask_price,
        liquidity=max(contract.volume_24h, contract.open_interest),
    )


def _strategy_for(contract: OptionContract) -> Strategy:
    return "long_call" if contract.option_type.strip().lower() in {"call", "c"} else "long_put"


def _rejection(
    contract: OptionContract,
    reasons: tuple[str, ...],
    messages: tuple[str, ...],
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
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


__all__ = [
    "AssetScanFailure",
    "Opportunity",
    "RejectedCandidate",
    "ScanRequest",
    "ScanResult",
    "scan_opportunities",
]
