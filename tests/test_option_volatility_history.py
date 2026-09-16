from datetime import UTC, datetime, timedelta

import pytest

from bybit_api.option_volatility_history import (
    BybitHistoricalVolatilityContextLoader,
)
from bybit_api.public import BybitPublicClient

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_loader_requests_period_30_and_normalizes_latest_point() -> None:
    calls = []

    async def fetch(asset, *, start_time, end_time, period):
        calls.append((asset, start_time, end_time, period))
        return [
            {
                "time": int((NOW - timedelta(hours=2)).timestamp() * 1000),
                "value": "0.51",
                "period": 30,
            },
            {
                "time": NOW - timedelta(minutes=30),
                "value": 0.62,
                "period": "30",
            },
            {"time": NOW + timedelta(minutes=1), "value": 99, "period": 30},
        ]

    loader = BybitHistoricalVolatilityContextLoader(fetch, now_fn=lambda: NOW)
    result = await loader.load(("btc",), as_of=NOW)

    context = result.for_asset("BTC")
    assert context is not None
    assert context.available is True
    assert context.status == "available"
    assert context.historical_volatility == pytest.approx(0.62)
    assert context.as_of == NOW - timedelta(minutes=30)
    assert context.period_days == 30
    assert calls == [("BTC", NOW - timedelta(days=30), NOW, 30)]


@pytest.mark.asyncio
async def test_loader_treats_naive_clock_and_as_of_as_utc() -> None:
    naive_now = NOW.replace(tzinfo=None)
    calls = []

    async def fetch(asset, *, start_time, end_time, period):
        calls.append((asset, start_time, end_time, period))
        return [{"time": naive_now - timedelta(minutes=5), "value": 0.5, "period": period}]

    loader = BybitHistoricalVolatilityContextLoader(
        fetch,
        now_fn=lambda: naive_now,
    )
    result = await loader.load(("btc",), as_of=naive_now)

    context = result.for_asset("BTC")
    assert context is not None
    assert context.requested_at == NOW
    assert context.retrieved_at == NOW
    assert context.as_of == NOW - timedelta(minutes=5)
    assert calls == [("BTC", NOW - timedelta(days=30), NOW, 30)]


@pytest.mark.asyncio
async def test_loader_deduplicates_assets_and_caches_for_one_hour() -> None:
    clock = [NOW]
    calls = []

    async def fetch(asset, *, start_time, end_time, period):
        calls.append(asset)
        return [{"time": end_time - timedelta(minutes=5), "value": 0.5, "period": period}]

    loader = BybitHistoricalVolatilityContextLoader(fetch, now_fn=lambda: clock[0])

    first = await loader.load(("eth", "BTC", "btc"))
    clock[0] += timedelta(minutes=59)
    second = await loader.load(("BTC", "ETH"))
    clock[0] += timedelta(minutes=2)
    await loader.load(("BTC",))

    assert [item.asset for item in first.contexts] == ["BTC", "ETH"]
    assert [item.asset for item in second.contexts] == ["BTC", "ETH"]
    assert all(item.requested_at == NOW + timedelta(minutes=59) for item in second.contexts)
    assert all(item.retrieved_at == NOW for item in second.contexts)
    assert calls == ["BTC", "ETH", "BTC"]


@pytest.mark.asyncio
async def test_cached_context_recomputes_freshness_for_new_valuation_time() -> None:
    clock = [NOW]
    calls = []

    async def fetch(asset, *, start_time, end_time, period):
        calls.append(asset)
        return [{"time": NOW - timedelta(minutes=30), "value": 0.5, "period": period}]

    loader = BybitHistoricalVolatilityContextLoader(
        fetch,
        now_fn=lambda: clock[0],
        cache_ttl=timedelta(hours=4),
        stale_after=timedelta(hours=1),
    )

    await loader.load(("BTC",))
    clock[0] += timedelta(hours=2)
    result = await loader.load(("BTC",))

    context = result.for_asset("BTC")
    assert context is not None
    assert context.status == "stale"
    assert context.requested_at == clock[0]
    assert context.retrieved_at == NOW
    assert calls == ["BTC"]


@pytest.mark.asyncio
async def test_fixed_as_of_does_not_reuse_cached_observation_from_the_future() -> None:
    calls = []

    async def fetch(asset, *, start_time, end_time, period):
        calls.append((asset, end_time))
        return [
            {"time": end_time - timedelta(minutes=5), "value": 0.3, "period": period},
            {"time": end_time + timedelta(minutes=5), "value": 0.9, "period": period},
        ]

    loader = BybitHistoricalVolatilityContextLoader(fetch, now_fn=lambda: NOW)
    await loader.load(("BTC",))

    fixed_as_of = NOW - timedelta(hours=1)
    result = await loader.load(("BTC",), as_of=fixed_as_of)

    context = result.for_asset("BTC")
    assert context is not None
    assert context.historical_volatility == pytest.approx(0.3)
    assert context.as_of == fixed_as_of - timedelta(minutes=5)
    assert context.as_of <= fixed_as_of
    assert calls == [("BTC", NOW), ("BTC", fixed_as_of)]


@pytest.mark.asyncio
async def test_loader_exposes_stale_missing_and_fetch_error_statuses() -> None:
    async def fetch(asset, *, start_time, end_time, period):
        if asset == "BTC":
            return [{"time": NOW - timedelta(hours=3), "value": "0.48", "period": 30}]
        if asset == "ETH":
            return [
                {"time": "invalid", "value": "nan", "period": 30},
                {"time": NOW, "value": "0.5", "period": 7},
            ]
        raise RuntimeError("temporary upstream failure")

    loader = BybitHistoricalVolatilityContextLoader(fetch, now_fn=lambda: NOW)
    result = await loader.load(("BTC", "ETH", "SOL"))

    btc = result.for_asset("BTC")
    eth = result.for_asset("ETH")
    sol = result.for_asset("SOL")
    assert btc is not None and btc.available is True and btc.status == "stale"
    assert eth is not None and eth.available is False and eth.status == "unavailable"
    assert eth.as_of is None and eth.historical_volatility is None
    assert sol is not None and sol.available is False and sol.status == "fetch_error"
    assert "temporary upstream failure" in (sol.message or "")


@pytest.mark.asyncio
async def test_public_client_uses_hourly_cache_freshness_for_historical_volatility(
    monkeypatch,
) -> None:
    client = BybitPublicClient(use_cache=True)
    captured = {}

    async def fake_get_with_cache(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(client, "_get_with_cache", fake_get_with_cache)
    await client.get_historical_volatility(
        "BTC",
        start_time=NOW - timedelta(days=30),
        end_time=NOW,
        period=30,
    )

    assert captured["cache_key"] == "BTC_30d_volatility"
    assert captured["freshness_seconds"] == 3600


@pytest.mark.asyncio
async def test_public_historical_volatility_chunk_uses_option_period_30(
    monkeypatch,
) -> None:
    client = BybitPublicClient(use_cache=False)
    captured = {}

    async def fake_request(endpoint, params):
        captured.update(endpoint=endpoint, params=params)
        return {
            "result": {
                "list": [
                    {
                        "time": int((NOW - timedelta(hours=1)).timestamp() * 1000),
                        "value": "0.45",
                    }
                ]
            }
        }

    monkeypatch.setattr(client, "_make_request", fake_request)
    result = await client._fetch_volatility_chunk(
        "BTC", 30, NOW - timedelta(hours=2), NOW
    )

    assert captured["endpoint"] == "/v5/market/historical-volatility"
    assert captured["params"]["category"] == "option"
    assert captured["params"]["baseCoin"] == "BTC"
    assert captured["params"]["period"] == 30
    assert result[0]["time"] == NOW - timedelta(hours=1)
    assert result[0]["value"] == 0.45
    assert result[0]["period"] == 30


@pytest.mark.asyncio
async def test_public_cached_historical_volatility_is_utc_aware(monkeypatch) -> None:
    client = BybitPublicClient(use_cache=True)

    async def fake_get_with_cache(**kwargs):
        return [
            {
                "time": NOW.replace(tzinfo=None),
                "value": 0.45,
                "period": 30,
            }
        ]

    monkeypatch.setattr(client, "_get_with_cache", fake_get_with_cache)
    result = await client.get_historical_volatility(
        "BTC",
        start_time=NOW - timedelta(days=30),
        end_time=NOW,
        period=30,
    )

    assert result[0]["time"].tzinfo == UTC
