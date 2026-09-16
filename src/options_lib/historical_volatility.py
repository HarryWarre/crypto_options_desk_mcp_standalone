"""Asset-level historical-volatility quality context for option scans.

This module deliberately models historical volatility as context, not as a
pricing input.  Current option tickers and the current fitted volatility
surface remain the source of fair IV used by the valuation model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

HistoricalVolatilityStatus = Literal[
    "available",
    "stale",
    "unavailable",
    "fetch_error",
    "not_loaded",
]


@dataclass(frozen=True)
class HistoricalVolatilityContext:
    """One normalized Bybit historical-volatility anchor for an asset."""

    asset: str
    period_days: int
    available: bool
    status: HistoricalVolatilityStatus
    historical_volatility: float | None
    as_of: datetime | None
    requested_at: datetime
    retrieved_at: datetime
    source: str = "/v5/market/historical-volatility"
    message: str | None = None

    def __post_init__(self) -> None:
        asset = str(self.asset).strip().upper()
        if not asset:
            raise ValueError("historical volatility asset is required")
        if self.period_days != 30:
            raise ValueError("historical volatility context must use period_days=30")
        requested_at = _aware_utc("requested_at", self.requested_at)
        retrieved_at = _aware_utc("retrieved_at", self.retrieved_at)
        as_of = _aware_utc("as_of", self.as_of) if self.as_of is not None else None
        if as_of is not None and as_of > requested_at:
            raise ValueError("historical volatility as_of cannot be after requested_at")
        if self.available:
            if self.status not in {"available", "stale"}:
                raise ValueError("available historical volatility has an invalid status")
            if self.historical_volatility is None or as_of is None:
                raise ValueError("available historical volatility requires value and as_of")
            value = float(self.historical_volatility)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("historical volatility must be finite and positive")
        else:
            if self.status in {"available", "stale"}:
                raise ValueError("unavailable historical volatility has an invalid status")
            if self.historical_volatility is not None or as_of is not None:
                raise ValueError("unavailable historical volatility cannot carry value or as_of")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "retrieved_at", retrieved_at)
        object.__setattr__(self, "as_of", as_of)

    @classmethod
    def not_loaded(
        cls,
        asset: str,
        *,
        requested_at: datetime,
    ) -> HistoricalVolatilityContext:
        """Create explicit metadata for a scan whose history was not loaded."""

        timestamp = _aware_utc("requested_at", requested_at)
        return cls(
            asset=asset,
            period_days=30,
            available=False,
            status="not_loaded",
            historical_volatility=None,
            as_of=None,
            requested_at=timestamp,
            retrieved_at=timestamp,
            message="30-day historical volatility was not loaded for this scan",
        )


@dataclass(frozen=True)
class HistoricalVolatilityContexts:
    """Deterministic collection returned by the history loading seam."""

    contexts: tuple[HistoricalVolatilityContext, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.contexts, key=lambda item: item.asset))
        assets = [item.asset for item in ordered]
        if len(assets) != len(set(assets)):
            raise ValueError("historical volatility contexts must be unique by asset")
        object.__setattr__(self, "contexts", ordered)

    def for_asset(self, asset: str) -> HistoricalVolatilityContext | None:
        normalized = str(asset).strip().upper()
        return next((item for item in self.contexts if item.asset == normalized), None)

    def cover(
        self,
        assets: tuple[str, ...],
        *,
        requested_at: datetime,
    ) -> tuple[HistoricalVolatilityContext, ...]:
        """Return one explicit context for every selected scan asset."""

        covered = []
        for asset in sorted({str(item).strip().upper() for item in assets if str(item).strip()}):
            covered.append(
                self.for_asset(asset)
                or HistoricalVolatilityContext.not_loaded(
                    asset,
                    requested_at=requested_at,
                )
            )
        return tuple(covered)


def _aware_utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"historical volatility {name} must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "HistoricalVolatilityContext",
    "HistoricalVolatilityContexts",
    "HistoricalVolatilityStatus",
]
