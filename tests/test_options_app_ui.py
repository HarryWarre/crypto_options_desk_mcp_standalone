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
    assert '<script src="/static/live-desk.js?v=20260918-1" defer></script>' in response.text
    assert '<script src="/static/app.js?v=20260918-1" defer></script>' in response.text
    assert '<link rel="stylesheet" href="/static/styles.css?v=20260918-1">' in response.text
    assert 'id="service-status"' in response.text
    assert 'id="live-desk-title"' in response.text
    assert 'id="live-toggle"' in response.text
    assert 'id="live-connection"' in response.text
    assert 'id="live-stat-opportunities"' in response.text
    assert 'id="market-strip"' in response.text
    assert 'id="live-opportunity-body"' in response.text
    assert 'id="signal-chart"' in response.text
    assert 'id="live-feed"' in response.text
    assert 'class="app-shell"' in response.text
    assert 'aria-label="Điều hướng workspace"' in response.text
    assert 'data-workspace-link href="#scanner"' in response.text
    assert 'data-workspace-link href="#backtest"' in response.text
    assert 'data-workspace-link href="#monitoring"' in response.text
    assert 'data-workspace-view="scanner"' in response.text
    assert 'data-workspace-view="backtest"' in response.text
    assert 'data-workspace-view="monitoring"' in response.text
    assert 'id="position-monitoring-view"' in response.text
    assert 'id="monitoring-state"' in response.text
    assert 'id="monitoring-decisions-body"' in response.text
    assert 'aria-disabled="true"' in response.text
    assert 'id="scan-terminal"' in response.text
    assert 'id="clear-terminal"' in response.text
    assert 'id="historical-context"' in response.text
    assert "Biến động lịch sử 30 ngày" not in response.text
    assert "không tải lịch sử mark-price" not in response.text
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
    assert "Đường payoff tại đáo hạn" in response.text
    assert "Giá cơ sở tại đáo hạn" in response.text
    assert "Ước tính payoff dựa trên các điểm do API trả về" not in response.text
    assert 'name="min_expected_value"' in response.text
    assert "EV ước tính không âm" in response.text
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
    assert 'name="valuation_mode" value="synthetic"' in response.text
    assert "Synthetic — spread giả định" in response.text
    assert 'name="assumed_spread_bps"' in response.text
    assert "Synthetic dùng spread giả định" in response.text
    assert "Khi nào nên chọn" in response.text


@pytest.mark.asyncio
async def test_static_assets_are_served_from_same_origin() -> None:
    app = create_app()

    javascript = await request(app, "GET", "/static/app.js")
    live_javascript = await request(app, "GET", "/static/live-desk.js")
    stylesheet = await request(app, "GET", "/static/styles.css")

    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert live_javascript.status_code == 200
    assert live_javascript.headers["content-type"].startswith("text/javascript")
    assert '"/api/v1/assets"' in javascript.text
    assert "syncWorkspaceFromHash" in javascript.text
    assert 'window.addEventListener("hashchange"' in javascript.text
    assert "/api/v1/opportunities/scan/stream" in javascript.text
    assert "FlowSurfaceLiveDesk" in javascript.text
    assert "createController" in javascript.text
    assert "/api/v1/opportunities/stream" in live_javascript.text
    assert "connectLiveFeed" in live_javascript.text
    assert "renderLiveSnapshot" in live_javascript.text
    assert "live_desk" in live_javascript.text
    assert "observed_assets" in live_javascript.text
    assert "contract_count" in live_javascript.text
    assert "rejection_reasons" in live_javascript.text
    assert "legs" in javascript.text
    for field in ("symbol", "option_type", "strike", "expiry_at", "position"):
        assert field in javascript.text
    assert "payoff_curve" in javascript.text
    assert "underlying_price" in javascript.text
    assert "Payoff từ API" in javascript.text
    assert "Xem payoff" in javascript.text
    assert "estimated_ev" in javascript.text
    assert "expected_value" in javascript.text
    assert "win_probability" in javascript.text
    assert "risk_reward_ratio" in javascript.text
    assert "methodology_note" in javascript.text
    assert "breakevens" in javascript.text
    assert 'P&L tại đáo hạn ${number(point.pnl, 2)}' in javascript.text
    assert 'node.setAttribute("aria-label"' in javascript.text
    assert '"/api/v1/scenarios"' not in javascript.text
    assert "max_loss" in javascript.text
    assert "max_profit" in javascript.text
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
    assert "anchor/quality" not in javascript.text
    assert "không tải lịch sử mark-price" not in javascript.text
    assert "opportunityLegs" in javascript.text
    assert "leg-summary" in javascript.text
    assert "textContent" in javascript.text
    assert "innerHTML" not in javascript.text
    assert "innerHTML" not in live_javascript.text
    assert "warningText" not in javascript.text
    assert "appendTerminal" in javascript.text
    assert "streamJson" in javascript.text
    assert "valuation_mode" in javascript.text
    assert "Theoretical mode" in javascript.text
    assert "Synthetic mode" in javascript.text
    assert "assumed_spread_bps" in javascript.text
    assert "Xem payoff mô hình" in javascript.text
    assert "EV mô hình" in javascript.text

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert "@media" in stylesheet.text
    assert ".detail-panel" in stylesheet.text
    assert ".detail-metrics" in stylesheet.text
    assert ".historical-context" in stylesheet.text
    assert ".chart-assumptions" in stylesheet.text
    assert ".valuation-mode-card" in stylesheet.text
    assert ".valuation-mode-notice" in stylesheet.text
    assert ".live-desk" in stylesheet.text
    assert ".desk-stat-grid" in stylesheet.text
    assert ".market-strip" in stylesheet.text
    assert ".live-opportunity-table" in stylesheet.text
    assert ".signal-chart" in stylesheet.text
    assert ".live-feed" in stylesheet.text


def test_static_directory_contains_only_the_expected_ui_files() -> None:
    assert {path.name for path in STATIC_DIR.iterdir()} == {"index.html", "app.js", "live-desk.js", "styles.css"}
