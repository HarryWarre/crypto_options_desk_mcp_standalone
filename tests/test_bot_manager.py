"""Unit tests for BotManager service and WebSocket stream integration."""

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from options_app.api import create_app
from options_app.bot_manager import BotManager, get_bot_manager


@pytest.mark.asyncio
async def test_bot_manager_lifecycle():
    bm = BotManager(asset="BTC", paper_mode=True, initial_capital=10000.0, interval_seconds=2)
    assert not bm.is_running
    status = bm.get_status()
    assert status["type"] == "bot_status"
    assert status["control"]["asset"] == "BTC"
    assert status["portfolio"]["equity"] >= 10000.0

    # Start bot
    start_res = await bm.start(interval=10)
    assert start_res["status"] == "started"
    assert bm.is_running

    # Stop bot
    stop_res = await bm.stop()
    assert stop_res["status"] == "stopped"
    assert not bm.is_running

    # Reset account
    reset_res = await bm.reset_account(capital=15000.0)
    assert reset_res["status"] == "reset"
    assert bm.bot.paper_account.cash_balance == 15000.0


@pytest.mark.asyncio
async def test_bot_control_api():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Get status
        res = await client.get("/api/v1/bot/status")
        assert res.status_code == 200
        data = res.json()
        assert "portfolio" in data
        assert "control" in data

        # 2. Control start
        res_start = await client.post("/api/v1/bot/control", json={"action": "start", "interval_seconds": 60})
        assert res_start.status_code == 200
        assert res_start.json()["result"]["status"] in ("started", "already_running")

        # 3. Control stop
        res_stop = await client.post("/api/v1/bot/control", json={"action": "stop"})
        assert res_stop.status_code == 200
        assert res_stop.json()["result"]["status"] == "stopped"

        # 4. Control reset
        res_reset = await client.post("/api/v1/bot/control", json={"action": "reset", "capital": 12000.0})
        assert res_reset.status_code == 200
        assert res_reset.json()["result"]["capital"] == 12000.0


def test_bot_websocket_stream():
    from starlette.testclient import TestClient

    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/bot/stream") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "bot_status"
            assert "portfolio" in msg
            assert "control" in msg
            ws.send_text("ping")
            pong = ws.receive_text()
            assert pong == "pong"

