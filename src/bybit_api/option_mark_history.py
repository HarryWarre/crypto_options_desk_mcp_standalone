"""Historical option mark-price candles from Bybit.

Bybit exposes historical mark-price OHLC candles per option symbol.  The
endpoint is useful for replaying historical mark prices, but it does not
contain historical bid/ask, implied volatility, Greeks, open interest, or
volume.  This module deliberately keeps that limitation visible in the type
and does not turn mark candles into executable historical quotes.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .utils import datetime_to_ms

PublicRequest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

_MARK_PRICE_ENDPOINT = "/v5/market/mark-price-kline"
_VALID_INTERVALS = {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"}
_INTERVAL_DELTAS = {
    "1": timedelta(minutes=1),
    "3": timedelta(minutes=3),
    "5": timedelta(minutes=5),
    "15": timedelta(minutes=15),
    "30": timedelta(minutes=30),
    "60": timedelta(hours=1),
    "120": timedelta(hours=2),
    "240": timedelta(hours=4),
    "360": timedelta(hours=6),
    "720": timedelta(hours=12),
    "D": timedelta(days=1),
    "W": timedelta(days=7),
    "M": timedelta(days=31),
}


class OptionMarkHistoryError(ValueError):
    """Raised for invalid mark-price history requests or responses."""


@dataclass(frozen=True)
class OptionMarkPriceBar:
    """One historical Bybit option mark-price candle."""

    symbol: str
    interval: str
    start_time: datetime
    open: float
    high: float
    low: float
    close: float
    source: str = "bybit-mark-price-kline"

    def __post_init__(self) -> None:
        if not self.symbol or not isinstance(self.symbol, str):
            raise OptionMarkHistoryError("symbol must be a non-empty string")
        if self.interval not in _VALID_INTERVALS:
            raise OptionMarkHistoryError(f"unsupported mark-price interval: {self.interval}")
        if self.start_time.tzinfo is None:
            raise OptionMarkHistoryError("start_time must be timezone-aware")
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
            raise OptionMarkHistoryError("mark-price OHLC values must be finite and positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise OptionMarkHistoryError("mark-price OHLC values are internally inconsistent")


async def fetch_option_mark_price_history(
    request: PublicRequest,
    *,
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    interval: str = "60",
    limit: int = 500,
    max_window: timedelta = timedelta(days=30),
) -> list[OptionMarkPriceBar]:
    """Fetch and normalize historical mark-price candles for one option.

    The API returns newest-first rows and caps option responses at 500 rows.
    Requests are paged backwards within bounded windows so a long range does
    not silently lose older candles.
    """

    _validate_request(symbol, start_time, end_time, interval, limit, max_window)
    start = _aware_utc(start_time)
    end = _aware_utc(end_time)
    interval_delta = _INTERVAL_DELTAS[interval]
    bars: dict[datetime, OptionMarkPriceBar] = {}
    window_end = end

    while window_end > start:
        window_start = max(start, window_end - max_window)
        page_end = window_end
        while page_end > window_start:
            params = {
                "category": "option",
                "symbol": symbol,
                "interval": interval,
                "start": datetime_to_ms(window_start),
                "end": datetime_to_ms(page_end),
                "limit": limit,
            }
            response = await request(_MARK_PRICE_ENDPOINT, params)
            rows = _extract_rows(response)
            page_bars = [_parse_row(row, symbol, interval) for row in rows]
            page_bars = [bar for bar in page_bars if start <= bar.start_time <= end]
            for bar in page_bars:
                bars[bar.start_time] = bar
            if not page_bars or len(rows) < limit:
                break
            oldest = min(bar.start_time for bar in page_bars)
            next_end = oldest - interval_delta
            if next_end >= page_end:
                raise OptionMarkHistoryError("mark-price pagination did not move backwards")
            page_end = next_end
        if window_start <= start:
            break
        window_end = window_start - interval_delta

    return [bars[key] for key in sorted(bars)]


def _validate_request(
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    interval: str,
    limit: int,
    max_window: timedelta,
) -> None:
    if not symbol or not isinstance(symbol, str):
        raise OptionMarkHistoryError("symbol must be a non-empty string")
    if interval not in _VALID_INTERVALS:
        raise OptionMarkHistoryError(f"unsupported mark-price interval: {interval}")
    if not 1 <= limit <= 500:
        raise OptionMarkHistoryError("option mark-price limit must be between 1 and 500")
    if max_window <= timedelta(0):
        raise OptionMarkHistoryError("max_window must be positive")
    start = _aware_utc(start_time)
    end = _aware_utc(end_time)
    if start >= end:
        raise OptionMarkHistoryError("start_time must be before end_time")


def _extract_rows(response: Any) -> list[Any]:
    if not isinstance(response, dict):
        raise OptionMarkHistoryError("Bybit mark-price response is not an object")
    if response.get("retCode", 0) != 0:
        raise OptionMarkHistoryError(
            f"Bybit API error {response.get('retCode')}: {response.get('retMsg', '')}"
        )
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("list"), list):
        raise OptionMarkHistoryError("Bybit mark-price response is missing result.list")
    return result["list"]


def _parse_row(row: Any, symbol: str, interval: str) -> OptionMarkPriceBar:
    if not isinstance(row, (list, tuple)) or len(row) < 5:
        raise OptionMarkHistoryError("malformed mark-price candle")
    try:
        timestamp = datetime.fromtimestamp(float(row[0]) / 1000.0, tz=UTC)
        values = tuple(float(value) for value in row[1:5])
    except (TypeError, ValueError, OSError) as exc:
        raise OptionMarkHistoryError("malformed mark-price candle values") from exc
    return OptionMarkPriceBar(
        symbol=symbol,
        interval=interval,
        start_time=timestamp,
        open=values[0],
        high=values[1],
        low=values[2],
        close=values[3],
    )


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OptionMarkHistoryError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "OptionMarkHistoryError",
    "OptionMarkPriceBar",
    "fetch_option_mark_price_history",
]
