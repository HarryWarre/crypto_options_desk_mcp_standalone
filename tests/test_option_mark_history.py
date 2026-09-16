from datetime import UTC, datetime, timedelta

import pytest

from bybit_api.option_mark_history import (
    OptionMarkHistoryError,
    fetch_option_mark_price_history,
)

SYMBOL = "BTC-30DEC26-100000-C"
START = datetime(2026, 9, 15, tzinfo=UTC)


@pytest.mark.asyncio
async def test_fetches_reverse_ordered_option_mark_candles() -> None:
    calls = []

    async def request(endpoint, params):
        calls.append((endpoint, params))
        return {
            "retCode": 0,
            "result": {
                "list": [
                    [
                        str(int((START + timedelta(hours=1)).timestamp() * 1000)),
                        "12",
                        "14",
                        "11",
                        "13",
                    ],
                    [str(int(START.timestamp() * 1000)), "10", "12", "9", "11"],
                    [str(int(START.timestamp() * 1000)), "10", "12", "9", "11"],
                ]
            },
        }

    bars = await fetch_option_mark_price_history(
        request,
        symbol=SYMBOL,
        start_time=START,
        end_time=START + timedelta(hours=2),
    )

    assert [bar.close for bar in bars] == [11.0, 13.0]
    assert calls == [
        (
            "/v5/market/mark-price-kline",
            {
                "category": "option",
                "symbol": SYMBOL,
                "interval": "60",
                "start": int(START.timestamp() * 1000),
                "end": int((START + timedelta(hours=2)).timestamp() * 1000),
                "limit": 500,
            },
        )
    ]


@pytest.mark.asyncio
async def test_deduplicates_mark_candles_across_pages() -> None:
    async def request(endpoint, params):
        if params["end"] > int((START + timedelta(hours=1)).timestamp() * 1000):
            rows = [
                [str(int((START + timedelta(hours=1)).timestamp() * 1000)), "12", "14", "11", "13"],
                [str(int(START.timestamp() * 1000)), "10", "12", "9", "11"],
            ]
        else:
            rows = [[str(int(START.timestamp() * 1000)), "10", "12", "9", "11"]]
        return {"retCode": 0, "result": {"list": rows}}

    bars = await fetch_option_mark_price_history(
        request,
        symbol=SYMBOL,
        start_time=START,
        end_time=START + timedelta(hours=2),
        limit=2,
        max_window=timedelta(days=1),
    )

    assert len(bars) == 2
    assert [bar.start_time for bar in bars] == [START, START + timedelta(hours=1)]


@pytest.mark.asyncio
async def test_rejects_invalid_request() -> None:
    async def request(endpoint, params):
        raise AssertionError("request should not be called")

    with pytest.raises(OptionMarkHistoryError, match="timezone-aware"):
        await fetch_option_mark_price_history(
            request,
            symbol=SYMBOL,
            start_time=START.replace(tzinfo=None),
            end_time=START + timedelta(hours=1),
        )
