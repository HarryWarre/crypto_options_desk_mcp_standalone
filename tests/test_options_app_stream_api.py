from fastapi.testclient import TestClient

from options_app.api import PositionMonitoringRequest, create_app


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
