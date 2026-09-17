"""Read-only market state used by the live options desk.

The opportunity scanner answers a narrower question: which candidates pass the
selected filters?  The live desk also needs to describe the market that was
actually observed when that answer is empty.  This module keeps that market
state at a separate, small seam so the scanner's ranking contract does not
need to grow UI-specific fields.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bybit_api.options_market_data import NormalizedOptionUniverse, OptionContract


@dataclass(frozen=True)
class LiveDeskAssetState:
    """The raw, per-asset market state available to one live snapshot."""

    asset: str
    spot: float | None
    contract_count: int
    valid_quote_count: int

    def __post_init__(self) -> None:
        normalized_asset = self.asset.strip().upper()
        if not normalized_asset:
            raise ValueError("asset cannot be empty")
        object.__setattr__(self, "asset", normalized_asset)
        if self.spot is not None and (
            isinstance(self.spot, bool)
            or not math.isfinite(float(self.spot))
            or self.spot <= 0
        ):
            raise ValueError("spot must be a positive finite number or None")
        for name, value in (
            ("contract_count", self.contract_count),
            ("valid_quote_count", self.valid_quote_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.valid_quote_count > self.contract_count:
            raise ValueError("valid_quote_count cannot exceed contract_count")


@dataclass(frozen=True)
class LiveDeskSnapshot:
    """A source-stamped, read-only market snapshot for the live desk.

    ``selected_assets`` preserves the user's requested universe, including an
    asset that produced no normalized contracts.  ``observed_assets`` contains
    the subset for which the market adapter observed an asset or contract.  A
    scanner can therefore return zero opportunities without erasing the
    underlying spot and quote coverage that explains the empty state.
    """

    selected_assets: tuple[str, ...]
    observed_assets: tuple[LiveDeskAssetState, ...]
    timestamp: datetime
    data_timestamp: datetime
    source: str
    rejection_reasons: dict[str, int]
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        selected = _normalize_assets(self.selected_assets)
        observed = tuple(self.observed_assets)
        observed_names = [state.asset for state in observed]
        if len(observed_names) != len(set(observed_names)):
            raise ValueError("observed_assets must contain each asset once")
        if any(asset not in selected for asset in observed_names):
            raise ValueError("observed_assets must be selected assets")
        if not self.source.strip():
            raise ValueError("source cannot be empty")
        if self.execution_allowed:
            raise ValueError("live desk snapshots are read-only")
        object.__setattr__(self, "selected_assets", selected)
        object.__setattr__(self, "observed_assets", observed)
        object.__setattr__(self, "rejection_reasons", _normalize_reason_counts(self.rejection_reasons))

    @classmethod
    def from_universe(
        cls,
        universe: NormalizedOptionUniverse,
        *,
        selected_assets: Sequence[str] = (),
        rejection_reasons: Iterable[str] | Mapping[str, int] = (),
        timestamp: datetime | None = None,
        data_timestamp: datetime | None = None,
    ) -> LiveDeskSnapshot:
        """Build a snapshot from normalized market data without ranking it."""

        if not isinstance(universe, NormalizedOptionUniverse):
            raise TypeError("universe must be a NormalizedOptionUniverse")

        selected = _selected_assets(universe, selected_assets)
        contracts_by_asset = universe.contracts_by_asset
        catalog_by_asset = {
            asset.base_coin.strip().upper(): asset for asset in universe.assets
        }
        observed = []
        for asset in selected:
            contracts = contracts_by_asset.get(asset, ())
            catalog_asset = catalog_by_asset.get(asset)
            # An asset in the selected catalog is still observed when all of
            # its tickers were excluded.  An unknown requested asset remains
            # selected but is not falsely reported as observed.
            if catalog_asset is None and not contracts:
                continue
            observed.append(
                LiveDeskAssetState(
                    asset=asset,
                    spot=_spot_for(contracts),
                    contract_count=(
                        catalog_asset.contract_count
                        if catalog_asset is not None
                        else len(contracts)
                    ),
                    valid_quote_count=sum(_has_valid_quote(contract) for contract in contracts),
                )
            )

        observed_timestamps = [
            contract.quote_timestamp
            for asset in observed
            for contract in contracts_by_asset.get(asset.asset, ())
        ]
        resolved_timestamp = timestamp or universe.valuation_time
        resolved_data_timestamp = data_timestamp or min(
            observed_timestamps,
            default=resolved_timestamp,
        )
        return cls(
            selected_assets=selected,
            observed_assets=tuple(observed),
            timestamp=resolved_timestamp,
            data_timestamp=resolved_data_timestamp,
            source=universe.source,
            rejection_reasons=(
                _normalize_reason_counts(rejection_reasons)
                if isinstance(rejection_reasons, Mapping)
                else _count_reasons(rejection_reasons)
            ),
        )

    @classmethod
    def from_scan(
        cls,
        universe: NormalizedOptionUniverse,
        scan_result: Any,
        *,
        selected_assets: Sequence[str] = (),
    ) -> LiveDeskSnapshot:
        """Combine raw market state with rejection metadata from one scan.

        The scanner result is read only for its timestamps and rejection
        reasons.  Opportunities are deliberately not consulted for market
        state, so an empty ranking still produces a useful desk snapshot.
        """

        rejections = getattr(scan_result, "rejections", ())
        reasons = (
            reason
            for rejection in rejections
            for reason in getattr(rejection, "reasons", ())
        )
        return cls.from_universe(
            universe,
            selected_assets=selected_assets,
            rejection_reasons=reasons,
            timestamp=getattr(scan_result, "timestamp", None),
            data_timestamp=getattr(scan_result, "data_timestamp", None),
        )


def build_live_desk_snapshot(
    universe: NormalizedOptionUniverse,
    scan_result: Any,
    *,
    selected_assets: Sequence[str] = (),
) -> LiveDeskSnapshot:
    """Public construction seam for the live desk adapter."""

    return LiveDeskSnapshot.from_scan(
        universe,
        scan_result,
        selected_assets=selected_assets,
    )


def _selected_assets(
    universe: NormalizedOptionUniverse,
    requested_assets: Sequence[str],
) -> tuple[str, ...]:
    requested = _normalize_assets(requested_assets)
    if requested:
        return requested
    discovered = {asset.base_coin.strip().upper() for asset in universe.assets}
    discovered.update(contract.asset.strip().upper() for contract in universe.contracts)
    return tuple(sorted(discovered))


def _normalize_assets(assets: Iterable[str]) -> tuple[str, ...]:
    normalized = []
    for asset in assets:
        value = str(asset).strip().upper()
        if not value:
            raise ValueError("asset names cannot be empty")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _spot_for(contracts: Iterable[OptionContract]) -> float | None:
    candidates = [
        contract
        for contract in contracts
        if _positive_finite(contract.spot_price)
    ]
    if not candidates:
        return None
    return float(
        max(
            candidates,
            key=lambda contract: (_as_utc(contract.quote_timestamp), contract.symbol),
        ).spot_price
    )


def _has_valid_quote(contract: OptionContract) -> bool:
    bid = contract.bid_price
    ask = contract.ask_price
    return (
        _positive_finite(bid)
        and _positive_finite(ask)
        and float(ask) >= float(bid)
    )


def _positive_finite(value: float | None) -> bool:
    return value is not None and not isinstance(value, bool) and math.isfinite(float(value)) and value > 0


def _count_reasons(reasons: Iterable[str]) -> dict[str, int]:
    counts = Counter(str(reason).strip() for reason in reasons if str(reason).strip())
    return dict(sorted(counts.items()))


def _normalize_reason_counts(counts: Mapping[str, int]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for reason, count in counts.items():
        name = str(reason).strip()
        if not name:
            raise ValueError("rejection reason cannot be empty")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("rejection reason counts must be non-negative integers")
        if count:
            normalized[name] = normalized.get(name, 0) + count
    return dict(sorted(normalized.items()))


def _as_utc(value: datetime) -> datetime:
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC)


__all__ = ["LiveDeskAssetState", "LiveDeskSnapshot", "build_live_desk_snapshot"]
