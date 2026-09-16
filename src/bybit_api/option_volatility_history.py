"""Load, normalize, and cache Bybit 30-day historical volatility context."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from options_lib.historical_volatility import (
    HistoricalVolatilityContext,
    HistoricalVolatilityContexts,
)

from .utils import now_utc

HistoricalVolatilityFetcher = Callable[..., Awaitable[Sequence[Mapping[str, Any]]]]


@dataclass(frozen=True)
class _CacheEntry:
    context: HistoricalVolatilityContext
    expires_at: datetime


class BybitHistoricalVolatilityContextLoader:
    """Load the latest asset-level 30-day anchor behind a small typed seam.

    ``fetch`` is normally ``BybitClient.get_historical_volatility`` (or the
    equivalent public-client method).  The one-hour in-memory TTL avoids a
    history request for every live valuation while keeping the loader easy to
    replace with a fake in tests.
    """

    PERIOD_DAYS = 30
    SOURCE = "/v5/market/historical-volatility"

    def __init__(
        self,
        fetch: HistoricalVolatilityFetcher,
        *,
        now_fn: Callable[[], datetime] = now_utc,
        cache_ttl: timedelta = timedelta(hours=1),
        stale_after: timedelta = timedelta(hours=2),
        lookback: timedelta = timedelta(days=30),
    ) -> None:
        if cache_ttl <= timedelta(0):
            raise ValueError("historical volatility cache_ttl must be positive")
        if stale_after <= timedelta(0):
            raise ValueError("historical volatility stale_after must be positive")
        if lookback <= timedelta(0):
            raise ValueError("historical volatility lookback must be positive")
        self._fetch = fetch
        self._now_fn = now_fn
        self._cache_ttl = cache_ttl
        self._stale_after = stale_after
        self._lookback = lookback
        self._cache: dict[str, _CacheEntry] = {}

    async def load(
        self,
        assets: Sequence[str],
        *,
        as_of: datetime | None = None,
    ) -> HistoricalVolatilityContexts:
        """Return one normalized context for each requested asset."""

        retrieved_at = _aware_utc(self._now_fn())
        requested_at = _aware_utc(as_of) if as_of is not None else retrieved_at
        normalized_assets = tuple(
            sorted({str(asset).strip().upper() for asset in assets if str(asset).strip()})
        )
        contexts = await asyncio.gather(
            *(
                self._load_asset(
                    asset,
                    requested_at=requested_at,
                    retrieved_at=retrieved_at,
                )
                for asset in normalized_assets
            )
        )
        return HistoricalVolatilityContexts(tuple(contexts))

    async def _load_asset(
        self,
        asset: str,
        *,
        requested_at: datetime,
        retrieved_at: datetime,
    ) -> HistoricalVolatilityContext:
        cached = self._cache.get(asset)
        if cached is not None and retrieved_at < cached.expires_at:
            context = cached.context
            if context.as_of is None or context.as_of <= requested_at:
                return self._context_for_request(context, requested_at)

        try:
            records = await self._fetch(
                asset,
                start_time=requested_at - self._lookback,
                end_time=requested_at,
                period=self.PERIOD_DAYS,
            )
            context = self._normalize(
                asset,
                records,
                requested_at=requested_at,
                retrieved_at=retrieved_at,
            )
        except Exception as exc:  # noqa: BLE001 - optional context exposes failures as data
            context = HistoricalVolatilityContext(
                asset=asset,
                period_days=self.PERIOD_DAYS,
                available=False,
                status="fetch_error",
                historical_volatility=None,
                as_of=None,
                requested_at=requested_at,
                retrieved_at=retrieved_at,
                message=f"Bybit historical volatility fetch failed: {exc}",
            )
        self._cache[asset] = _CacheEntry(
            context=context,
            expires_at=retrieved_at + self._cache_ttl,
        )
        return context

    def _context_for_request(
        self,
        context: HistoricalVolatilityContext,
        requested_at: datetime,
    ) -> HistoricalVolatilityContext:
        """Recompute request-relative freshness without refetching cached data."""

        if not context.available or context.as_of is None:
            return replace(context, requested_at=requested_at)

        is_stale = requested_at - context.as_of >= self._stale_after
        return replace(
            context,
            status="stale" if is_stale else "available",
            requested_at=requested_at,
            message=(
                f"latest 30-day historical volatility is older than {self._stale_after}"
                if is_stale
                else None
            ),
        )

    def _normalize(
        self,
        asset: str,
        records: Sequence[Mapping[str, Any]],
        *,
        requested_at: datetime,
        retrieved_at: datetime,
    ) -> HistoricalVolatilityContext:
        valid: list[tuple[datetime, float]] = []
        invalid_count = 0
        for record in records:
            try:
                if not isinstance(record, Mapping):
                    raise TypeError("record must be a mapping")
                period = record.get("period", self.PERIOD_DAYS)
                if int(period) != self.PERIOD_DAYS:
                    raise ValueError("unexpected historical volatility period")
                timestamp = _coerce_timestamp(record.get("time"))
                value = float(record.get("value"))
                if timestamp > requested_at:
                    raise ValueError("historical volatility point is in the future")
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("historical volatility value must be positive")
            except (TypeError, ValueError, OverflowError, OSError):
                invalid_count += 1
                continue
            valid.append((timestamp, value))

        if not valid:
            suffix = f"; ignored {invalid_count} invalid record(s)" if invalid_count else ""
            return HistoricalVolatilityContext(
                asset=asset,
                period_days=self.PERIOD_DAYS,
                available=False,
                status="unavailable",
                historical_volatility=None,
                as_of=None,
                requested_at=requested_at,
                retrieved_at=retrieved_at,
                message=f"Bybit returned no valid 30-day historical volatility{suffix}",
            )

        as_of, value = max(valid, key=lambda item: item[0])
        stale = requested_at - as_of >= self._stale_after
        return HistoricalVolatilityContext(
            asset=asset,
            period_days=self.PERIOD_DAYS,
            available=True,
            status="stale" if stale else "available",
            historical_volatility=value,
            as_of=as_of,
            requested_at=requested_at,
            retrieved_at=retrieved_at,
            source=self.SOURCE,
            message=(
                f"latest 30-day historical volatility is older than {self._stale_after}"
                if stale
                else None
            ),
        )


def _coerce_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _aware_utc(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("historical volatility time is empty")
        try:
            value = float(stripped)
        except ValueError:
            return _aware_utc(datetime.fromisoformat(stripped))
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("historical volatility time must be finite")
        seconds = numeric / 1000.0 if abs(numeric) >= 100_000_000_000 else numeric
        return datetime.fromtimestamp(seconds, tz=UTC)
    raise TypeError("historical volatility time is missing or invalid")


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("historical volatility timestamps must be datetime values")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "BybitHistoricalVolatilityContextLoader",
    "HistoricalVolatilityFetcher",
]
