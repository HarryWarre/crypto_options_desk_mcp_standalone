"""
DESK-003: E2E verification of Live Desk bot widgets and WebSocket stream.

These tests hit the running server at http://localhost:8000 and verify:
1. index.html contains all required bot-panel DOM elements
2. /api/v1/bot/status returns valid schema
3. /api/v1/bot/control (cycle action) executes without error
4. WS /api/v1/bot/stream delivers at least one bot_status message
5. Bot panel CSS classes are present in styles.css
6. live-desk.js contains initBotDesk and WebSocket connection code
"""

import asyncio
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pytest
import websockets

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/api/v1/bot/stream"
PROJECT_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Helper: minimal DOM element finder
# ---------------------------------------------------------------------------

class IDFinder(HTMLParser):
    """Collect all id= attributes found in HTML."""

    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.classes: set[str] = set()

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if "id" in attr_map:
            self.ids.add(attr_map["id"])
        if "class" in attr_map:
            for cls in attr_map["class"].split():
                self.classes.add(cls)


# ---------------------------------------------------------------------------
# Fixture: shared httpx client (sync)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. HTML structure: bot-panel DOM elements
# ---------------------------------------------------------------------------

class TestBotPanelDOM:
    def test_index_html_loads(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_bot_panel_exists(self, client):
        html = client.get("/").text
        finder = IDFinder()
        finder.feed(html)
        assert "bot-panel" in finder.ids, "#bot-panel not found in index.html"

    def test_bot_stat_elements_present(self, client):
        html = client.get("/").text
        finder = IDFinder()
        finder.feed(html)
        # Actual IDs used in index.html
        required_ids = {"bot-stat-equity", "bot-stat-unrealized", "bot-stat-margin", "bot-status-badge"}
        missing = required_ids - finder.ids
        assert not missing, f"Missing stat element IDs: {missing}"

    def test_bot_legs_table_present(self, client):
        html = client.get("/").text
        finder = IDFinder()
        finder.feed(html)
        assert "bot-legs-body" in finder.ids, "#bot-legs-body table not found in HTML"

    def test_bot_control_buttons_present(self, client):
        html = client.get("/").text
        # Actual button text in index.html (Vietnamese, English hint in parens)
        required_texts = ["Bật Bot", "Quét ngay", "Đóng hết", "Reset Ví"]
        for text in required_texts:
            assert text in html, f"Button text '{text}' not found in HTML"


# ---------------------------------------------------------------------------
# 2. Bot status API schema
# ---------------------------------------------------------------------------

class TestBotStatusAPI:
    def test_status_returns_200(self, client):
        r = client.get("/api/v1/bot/status")
        assert r.status_code == 200

    def test_status_schema_top_level_keys(self, client):
        data = client.get("/api/v1/bot/status").json()
        required_keys = {"type", "timestamp", "control", "portfolio", "margin",
                         "active_condor", "open_positions", "recent_trades"}
        missing = required_keys - data.keys()
        assert not missing, f"Missing top-level keys in /api/v1/bot/status: {missing}"

    def test_status_control_block(self, client):
        control = client.get("/api/v1/bot/status").json()["control"]
        assert "is_running" in control
        assert "paper_mode" in control
        assert control["paper_mode"] is True, "Bot must default to paper_mode=True"

    def test_status_portfolio_block(self, client):
        portfolio = client.get("/api/v1/bot/status").json()["portfolio"]
        assert "cash_balance" in portfolio
        assert "equity" in portfolio
        assert portfolio["equity"] >= 0

    def test_status_margin_block(self, client):
        margin = client.get("/api/v1/bot/status").json()["margin"]
        assert "margin_utilization_pct" in margin
        assert 0.0 <= margin["margin_utilization_pct"] <= 100.0 or margin["margin_utilization_pct"] == 0.0

    def test_status_recent_trades_is_list(self, client):
        data = client.get("/api/v1/bot/status").json()
        assert isinstance(data["recent_trades"], list)

    def test_status_open_positions_is_list(self, client):
        data = client.get("/api/v1/bot/status").json()
        assert isinstance(data["open_positions"], list)


# ---------------------------------------------------------------------------
# 3. Bot control API
# ---------------------------------------------------------------------------

class TestBotControlAPI:
    def test_reset_returns_ok(self, client):
        r = client.post("/api/v1/bot/control", json={"action": "reset"})
        assert r.status_code == 200
        body = r.json()
        assert "result" in body
        assert body["result"].get("status") == "reset"

    def test_cycle_returns_ok(self, client):
        r = client.post("/api/v1/bot/control", json={"action": "cycle"})
        assert r.status_code == 200
        body = r.json()
        assert "result" in body
        assert body["result"].get("status") is not None

    def test_start_stop_bot(self, client):
        # Ensure bot is stopped first (may be running from a previous test or session)
        client.post("/api/v1/bot/control", json={"action": "stop"})

        r_start = client.post("/api/v1/bot/control", json={"action": "start"})
        assert r_start.status_code == 200
        start_status = r_start.json().get("result", {}).get("status")
        assert start_status in ("started", "already_running"), (
            f"Unexpected start status: {start_status}"
        )

        r_stop = client.post("/api/v1/bot/control", json={"action": "stop"})
        assert r_stop.status_code == 200
        assert r_stop.json().get("result", {}).get("status") == "stopped"

    def test_invalid_action_returns_422_or_400(self, client):
        r = client.post("/api/v1/bot/control", json={"action": "launch_missiles"})
        assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 4. WebSocket stream
# ---------------------------------------------------------------------------

class TestBotWebSocket:
    def test_ws_delivers_bot_status_message(self):
        """Connect to WS, receive at least one message, verify it is bot_status."""
        async def _run():
            async with websockets.connect(WS_URL, open_timeout=5) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw)
                assert msg.get("type") == "bot_status", (
                    f"Expected type=bot_status, got: {msg.get('type')}"
                )
                assert "control" in msg
                assert "portfolio" in msg
                return msg

        msg = asyncio.run(_run())
        assert msg is not None

    def test_ws_message_control_has_is_running(self):
        async def _run():
            async with websockets.connect(WS_URL, open_timeout=5) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                return json.loads(raw)

        msg = asyncio.run(_run())
        assert "is_running" in msg["control"]

    def test_ws_message_portfolio_has_equity(self):
        async def _run():
            async with websockets.connect(WS_URL, open_timeout=5) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                return json.loads(raw)

        msg = asyncio.run(_run())
        assert "equity" in msg["portfolio"]


# ---------------------------------------------------------------------------
# 5. Static assets: CSS and JS correctness
# ---------------------------------------------------------------------------

class TestStaticAssets:
    def test_styles_css_has_bot_panel_class(self, client):
        css = client.get("/static/styles.css").text
        assert ".bot-panel" in css, ".bot-panel class missing from styles.css"

    def test_styles_css_has_bot_stat_grid(self, client):
        css = client.get("/static/styles.css").text
        assert ".bot-stat-grid" in css

    def test_styles_css_has_tp_meter(self, client):
        css = client.get("/static/styles.css").text
        assert ".tp-meter" in css or "tp-meter" in css

    def test_styles_css_has_bot_legs_table(self, client):
        css = client.get("/static/styles.css").text
        assert ".bot-legs-table" in css

    def test_live_desk_js_has_init_bot_desk(self, client):
        js = client.get("/static/live-desk.js").text
        assert "initBotDesk" in js, "initBotDesk function missing from live-desk.js"

    def test_live_desk_js_has_websocket_connection(self, client):
        js = client.get("/static/live-desk.js").text
        assert "bot/stream" in js, "WS /api/v1/bot/stream reference missing from live-desk.js"

    def test_live_desk_js_has_bot_control_fetch(self, client):
        js = client.get("/static/live-desk.js").text
        assert "bot/control" in js, "POST /api/v1/bot/control reference missing from live-desk.js"


# ---------------------------------------------------------------------------
# 6. Mobile viewport simulation (check no media-query breakpoints missing)
# ---------------------------------------------------------------------------

class TestMobileResponsiveness:
    def test_css_has_media_query_for_small_screens(self, client):
        css = client.get("/static/styles.css").text
        # Should have at least one mobile breakpoint (max-width <= 560px)
        matches = re.findall(r"@media[^{]+max-width\s*:\s*(\d+)px", css)
        small = [int(w) for w in matches if int(w) <= 560]
        assert small, "No mobile @media max-width <= 560px found in styles.css"

    def test_bot_panel_html_has_responsive_grid(self, client):
        html = client.get("/").text
        finder = IDFinder()
        finder.feed(html)
        # bot-stat-grid should exist as a class somewhere
        assert "bot-stat-grid" in finder.classes, "bot-stat-grid class not found in HTML"
