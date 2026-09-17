from datetime import UTC, datetime

from fastapi.testclient import TestClient

from bybit_api.options_market_data import NormalizedOptionUniverse
from options_app.api import PositionMonitoringRequest, create_app
from options_lib.opportunity_scanner import ScanResult


class FakeMonitoringSession:
    async def events(self):
        yield {
            "type": "snapshot",
            "payload": {
                "source": "bybit-websocket",
                "reconciliation_status": "complete",
                "positions": [],
                "decisions": [],
            },
            "execution_allowed": False,
        }


def test_monitoring_websocket_accepts_request_and_sends_sanitized_events() -> None:
    calls: list[PositionMonitoringRequest] = []

    def factory(request: PositionMonitoringRequest) -> FakeMonitoringSession:
        calls.append(request)
        return FakeMonitoringSession()

    with TestClient(create_app(monitoring_stream_factory=factory)) as client, client.websocket_connect(
        "/api/v1/positions/stream"
    ) as websocket:
        websocket.send_json(
            {
                "base_coin": "btc",
                "position_type": "option",
                "policies": [],
                "persist": False,
            }
        )
        assert websocket.receive_json()["status"] == "starting"
        event = websocket.receive_json()

    assert calls[0].base_coin == "BTC"
    assert calls[0].position_type == "option"
    assert event == {
        "type": "snapshot",
        "payload": {
            "source": "bybit-websocket",
            "reconciliation_status": "complete",
            "positions": [],
            "decisions": [],
        },
        "execution_allowed": False,
    }


class FakeScannerAdapter:
    def __init__(self) -> None:
        self.load_calls = 0

    async def load_universe(self, assets=None, *, valuation_time=None):
        self.load_calls += 1
        now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        return NormalizedOptionUniverse(
            assets=(),
            contracts=(),
            issues=(),
            valuation_time=now,
            source="fake-live-stream",
        )


def fake_scan(_universe, _request) -> ScanResult:
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    return ScanResult(
        timestamp=now,
        data_timestamp=now,
        opportunities=(),
        rejections=(),
        asset_failures=(),
        issues=(),
    )


def test_opportunity_websocket_streams_repeated_scan_contract() -> None:
    adapter = FakeScannerAdapter()
    with TestClient(
        create_app(
            adapter=adapter,
            scanner=fake_scan,
            live_scan_interval_seconds=0,
        )
    ) as client, client.websocket_connect("/api/v1/opportunities/stream") as websocket:
        websocket.send_json(
            {
                "assets": ["BTC"],
                "strategies": ["long_call"],
                "market_view": "custom",
                "time_horizon": "7_30",
                "max_loss": 100,
            }
        )

        assert websocket.receive_json()["status"] == "starting"
        event_types = []
        snapshots = 0
        while True:
            event = websocket.receive_json()
            event_types.append(event["type"])
            if event["type"] == "snapshot":
                snapshots += 1
                assert event["payload"]["valuation_mode"] == "executable"
                assert event["execution_allowed"] is False
                if snapshots == 2:
                    break
        assert "log" in event_types
    assert adapter.load_calls >= 2
