from datetime import UTC, datetime

import httpx
import pytest

from options_app.api import create_app


async def request(app, method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_backtest_endpoint_returns_trade_level_report() -> None:
    calls = []

    def runner(payload):
        calls.append(payload)
        return {
            "status": "completed",
            "engine": "snapshot_replay",
            "trades": [{"exit_reason": "profit_target", "net_pnl": 125.0}],
        }

    response = await request(
        create_app(backtest_runner=runner),
        "POST",
        "/api/v1/backtests",
        json={
            "assets": ["btc"],
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-02-01T00:00:00Z",
            "filters": {"strategies": ["long_call"]},
            "exit_policy": {"type": "profit_target", "profit_target_pct": 0.5},
        },
    )

    assert response.status_code == 200
    assert response.json()["trades"][0]["exit_reason"] == "profit_target"
    assert calls[0].assets == ["BTC"]
    assert calls[0].exit_policy.type == "profit_target"


@pytest.mark.asyncio
async def test_backtest_endpoint_reports_unconfigured_archive() -> None:
    response = await request(
        create_app(),
        "POST",
        "/api/v1/backtests",
        json={
            "assets": ["BTC"],
            "start_time": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            "end_time": datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "backtest_data_unavailable"


@pytest.mark.asyncio
async def test_backtest_endpoint_rejects_naive_timestamps() -> None:
    response = await request(
        create_app(backtest_runner=lambda _payload: {}),
        "POST",
        "/api/v1/backtests",
        json={
            "assets": ["BTC"],
            "start_time": "2026-01-01T00:00:00",
            "end_time": "2026-02-01T00:00:00Z",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
