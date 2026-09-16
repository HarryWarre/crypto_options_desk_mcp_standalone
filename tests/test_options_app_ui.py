from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from options_app.api import create_app

STATIC_DIR = Path(__file__).parents[1] / "src" / "options_app" / "static"


async def request(app, method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_root_serves_the_read_only_scanner_ui() -> None:
    response = await request(create_app(), "GET", "/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<title>Crypto Options Scanner</title>' in response.text
    assert '<script src="/static/app.js?v=20260917-1" defer></script>' in response.text
    assert '<link rel="stylesheet" href="/static/styles.css?v=20260917-1">' in response.text
    assert 'id="service-status"' in response.text
    assert 'id="scan-terminal"' in response.text
    assert 'id="clear-terminal"' in response.text
    assert 'id="historical-context"' in response.text
    assert "Biến động lịch sử 30 ngày" in response.text
    assert "không tải lịch sử mark-price" in response.text
    assert "Không đặt lệnh" not in response.text
    assert "Chưa kiểm định" not in response.text
    assert "include_unvalidated" not in response.text
    assert 'id="opportunity-detail"' in response.text
    assert 'id="pnl-chart"' in response.text
    assert 'id="pnl-chart-legend"' in response.text
    assert 'id="pnl-chart-assumptions"' in response.text
    assert 'id="scenario-results-body"' in response.text
    assert 'class="strategy-grid"' in response.text
    assert 'name="strategies" value="call_vertical"' in response.text
    assert 'name="strategies" value="put_vertical"' in response.text
    for strategy in (
        "long_call",
        "long_put",
        "iron_condor",
        "iron_butterfly",
        "long_straddle",
        "long_strangle",
        "protective_put",
        "covered_call",
        "calendar_spread",
        "butterfly",
        "broken_wing_butterfly",
    ):
        assert f'name="strategies" value="{strategy}"' in response.text
    assert 'type="radio" name="quick_strategy"' not in response.text
    assert 'name="quick_target_edge_pct"' not in response.text
    assert "có thể chọn nhiều chiến lược" in response.text
    assert 'name="risk_free_rate_pct"' in response.text
    assert 'name="valuation_mode" value="executable" checked' in response.text
    assert 'name="valuation_mode" value="theoretical"' in response.text
    assert "Theoretical — bỏ qua bid/ask" in response.text
    assert "không tính edge sau phí/lỗ tối đa để giao dịch" in response.text
    assert "Khi nào nên chọn" in response.text


@pytest.mark.asyncio
async def test_static_assets_are_served_from_same_origin() -> None:
    app = create_app()

    javascript = await request(app, "GET", "/static/app.js")
    stylesheet = await request(app, "GET", "/static/styles.css")

    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert '"/api/v1/assets"' in javascript.text
    assert '"/api/v1/scenarios"' in javascript.text
    assert "/api/v1/opportunities/scan/stream" in javascript.text
    assert "strategy_type" in javascript.text
    assert "legs" in javascript.text
    for field in ("symbol", "option_type", "strike", "expiry", "valuation_time", "spot", "iv", "risk_free_rate", "bid", "ask", "position"):
        assert field in javascript.text
    assert "underlying_move_pct" in javascript.text
    assert "iv_move" in javascript.text
    assert "elapsed_days" in javascript.text
    assert "exit_price_source" in javascript.text
    assert "fee_per_contract" in javascript.text
    assert "slippage_bps" in javascript.text
    assert "contract_multiplier" in javascript.text
    assert "Xem P&L" in javascript.text
    assert "max_loss" in javascript.text
    assert "max_profit" in javascript.text
    assert "greeks" in javascript.text
    assert "greeks.rho" in javascript.text
    for strategy in (
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
    ):
        assert strategy in javascript.text
    assert "strategyLabel" in javascript.text
    assert "historical_volatility_contexts" in javascript.text
    assert "anchor/quality" in javascript.text
    assert "không tải lịch sử mark-price" in javascript.text
    assert "scenarioStrategyType" in javascript.text
    assert "opportunityLegs" in javascript.text
    assert "leg-summary" in javascript.text
    assert "textContent" in javascript.text
    assert "innerHTML" not in javascript.text
    assert "warningText" not in javascript.text
    assert "appendTerminal" in javascript.text
    assert "streamJson" in javascript.text
    assert "valuation_mode" in javascript.text
    assert "Theoretical mode" in javascript.text
    assert "Thiếu bid/ask" in javascript.text
    assert "P&L cần bid/ask" in javascript.text

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert "@media" in stylesheet.text
    assert ".detail-panel" in stylesheet.text
    assert ".detail-metrics" in stylesheet.text
    assert ".historical-context" in stylesheet.text
    assert ".valuation-mode-card" in stylesheet.text
    assert ".valuation-mode-notice" in stylesheet.text


def test_static_directory_contains_only_the_expected_ui_files() -> None:
    assert {path.name for path in STATIC_DIR.iterdir()} == {"index.html", "app.js", "styles.css"}
