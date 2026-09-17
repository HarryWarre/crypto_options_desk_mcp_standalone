import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from position_monitoring import (
    BybitPrivateWebSocket,
    ExitPolicy,
    LiveMonitoringSession,
    MonitoringSnapshotReducer,
    PositionSnapshot,
    PositionTracker,
    TrackedPosition,
)

AS_OF = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def baseline() -> PositionSnapshot:
    return PositionSnapshot(
        captured_at=AS_OF,
        source="rest",
        positions=(
            TrackedPosition(
                symbol="BTCUSDT",
                category="linear",
                side="long",
                quantity=1,
                avg_entry_price=100,
                mark_price=105,
                unrealized_pnl=5,
                position_idx=1,
                observed_at=AS_OF,
                source="rest",
            ),
        ),
    )


def test_reducer_updates_position_by_position_index_and_removes_flat_position() -> None:
    reducer = MonitoringSnapshotReducer(baseline(), base_coin="BTC")

    snapshot = reducer.apply(
        {
            "topic": "position.linear",
            "creationTime": 1789646433000,
            "data": [
                {
                    "category": "linear",
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "2",
                    "positionIdx": 1,
                    "entryPrice": "100",
                    "markPrice": "110",
                    "unrealisedPnl": "20",
                }
            ],
        }
    )

    assert snapshot is not None
    assert snapshot.positions[0].quantity == 2
    assert snapshot.positions[0].position_idx == 1
    assert snapshot.positions[0].mark_price == 110

    flat = reducer.apply(
        {
            "topic": "position.linear",
            "creationTime": 1789646434000,
            "data": [{"category": "linear", "symbol": "BTCUSDT", "side": "", "size": "0", "positionIdx": 1}],
        }
    )
    assert flat is not None
    assert flat.positions == ()


def test_reducer_preserves_open_order_and_deduplicates_execution_updates() -> None:
    reducer = MonitoringSnapshotReducer(baseline(), base_coin="BTC")
    reducer.apply(
        {
            "topic": "order.linear",
            "creationTime": 1789646433000,
            "data": [
                {
                    "category": "linear",
                    "orderId": "order-1",
                    "symbol": "BTCUSDT",
                    "side": "Sell",
                    "orderStatus": "New",
                    "orderType": "Limit",
                    "qty": "1",
                    "leavesQty": "1",
                }
            ],
        }
    )
    assert len(reducer.snapshot().open_orders) == 1

    execution = {
        "topic": "execution.linear",
        "creationTime": 1789646434000,
        "data": [
            {
                "category": "linear",
                "orderId": "order-1",
                "execId": "exec-1",
                "symbol": "BTCUSDT",
                "side": "Sell",
                "orderQty": "1",
                "execQty": "1",
                "execPrice": "110",
                "execFee": "0.1",
                "execTime": "1789646434000",
            }
        ],
    }
    reducer.apply(execution)
    reducer.apply(execution)
    second_fill = execution | {
        "data": [execution["data"][0] | {"execId": "exec-2", "execPrice": "111"}]
    }
    reducer.apply(second_fill)
    snapshot = reducer.snapshot()

    assert snapshot.open_orders == ()
    assert len(snapshot.order_history) == 2
    assert snapshot.order_history[0].average_fill_price == 110
    assert snapshot.order_history[1].execution_id == "exec-2"


class SnapshotAdapter:
    async def fetch_snapshot(self, *, base_coin, position_type, as_of):
        return baseline()


class DisconnectingStream:
    async def messages(self, _position_type):
        yield {"type": "stream_status", "status": "disconnected"}


class MemoryHistory:
    def __init__(self):
        self.reports = []

    def append(self, report):
        self.reports.append(report)
        return str(len(self.reports))


@pytest.mark.asyncio
async def test_live_session_marks_disconnect_as_review_and_persists_it() -> None:
    history = MemoryHistory()
    session = LiveMonitoringSession(
        adapter=SnapshotAdapter(),
        tracker=PositionTracker(SnapshotAdapter()),
        stream=DisconnectingStream(),
        history=history,
        base_coin="BTC",
        position_type="linear",
        policies={"BTCUSDT": ExitPolicy(symbol="BTCUSDT")},
    )

    events = [event async for event in session.events()]

    assert events[0]["payload"]["decisions"][0]["action"] == "hold"
    assert events[1]["status"] == "disconnected"
    assert events[2]["payload"]["decisions"][0]["action"] == "review"
    assert "stream_disconnected" in events[2]["payload"]["issues"]
    assert len(history.reports) == 2


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.receive_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        self.receive_count += 1
        if self.receive_count == 1:
            return json.dumps({"success": True, "op": "auth"})
        return json.dumps({"success": True, "op": "subscribe"})

    def __aiter__(self):
        async def messages():
            yield json.dumps({"topic": "position.option", "data": []})

        return messages()


@pytest.mark.asyncio
async def test_private_stream_authenticates_subscribes_and_exposes_bybit_topics() -> None:
    socket = FakeSocket()

    def connect(_url: str, **_kwargs):
        class Context:
            async def __aenter__(self):
                return await socket.__aenter__()

            async def __aexit__(self, *args):
                return await socket.__aexit__(*args)

        return Context()

    stream = BybitPrivateWebSocket(
        "key",
        "secret",
        testnet=True,
        connect=connect,
        heartbeat_seconds=60,
    )
    iterator = stream.messages("option")

    status = await anext(iterator)
    message = await anext(iterator)
    await iterator.aclose()

    auth, subscribe = [json.loads(payload) for payload in socket.sent[:2]]
    expires = auth["args"][1]
    expected = hmac.new(
        b"secret", f"GET/realtime{expires}".encode(), hashlib.sha256
    ).hexdigest()

    assert stream.url == "wss://stream-testnet.bybit.com/v5/private"
    assert auth["op"] == "auth"
    assert auth["args"] == ["key", expires, expected]
    assert subscribe == {
        "op": "subscribe",
        "args": ["position.option", "order.option", "execution.option"],
    }
    assert status["type"] == "stream_status"
    assert message["topic"] == "position.option"
