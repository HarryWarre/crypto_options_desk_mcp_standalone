"""Authenticated Bybit private-stream monitoring with REST reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import websockets

from .models import PositionSide, PositionSnapshot, TrackedOrder, TrackedPosition
from .persistence import SnapshotHistoryError
from .tracker import MonitoringReport, PositionSnapshotAdapter, PositionTracker

logger = logging.getLogger(__name__)


class BybitPrivateStreamError(RuntimeError):
    """Raised when Bybit rejects private-stream authentication or subscription."""


def _number(value: Any, default: float | None = 0.0) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timestamp(value: Any, fallback: datetime) -> datetime:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _topic_category(topic: str) -> str | None:
    parts = topic.split(".")
    return parts[1] if len(parts) > 1 else None


def _matches_base_coin(symbol: str, base_coin: str) -> bool:
    normalized = base_coin.strip().upper()
    if normalized == "ALL":
        return True
    symbol = symbol.upper()
    return symbol.startswith((f"{normalized}-", normalized))


def _position_from_event(
    raw: Mapping[str, Any],
    *,
    category: str,
    observed_at: datetime,
) -> TrackedPosition:
    return TrackedPosition(
        symbol=str(raw.get("symbol") or ""),
        category=category,
        side=PositionSide.from_exchange(str(raw.get("side") or "")),
        quantity=_number(raw.get("size")),
        avg_entry_price=_number(raw.get("entryPrice", raw.get("avgPrice"))),
        mark_price=_number(raw.get("markPrice")),
        unrealized_pnl=_number(raw.get("unrealisedPnl", raw.get("unrealizedPnl"))),
        realized_pnl=_number(raw.get("cumRealisedPnl", raw.get("cumRealizedPnl"))),
        position_value=_number(raw.get("positionValue"), default=None),
        liquidation_price=_number(raw.get("liqPrice"), default=None),
        leverage=_number(raw.get("leverage"), default=None),
        position_idx=(int(raw["positionIdx"]) if raw.get("positionIdx") not in (None, "") else None),
        observed_at=observed_at,
        source="bybit-websocket",
    )


class MonitoringSnapshotReducer:
    """Apply Bybit position/order/execution deltas to a reconciled snapshot."""

    _TERMINAL_ORDER_STATUSES = frozenset(
        {
            "filled",
            "cancelled",
            "canceled",
            "partiallyfilledcanceled",
            "rejected",
            "deactivated",
            "triggered",
        }
    )

    def __init__(
        self,
        snapshot: PositionSnapshot,
        *,
        base_coin: str = "ALL",
        max_order_history: int = 100,
    ) -> None:
        if max_order_history < 1:
            raise ValueError("max_order_history must be positive")
        self.base_coin = base_coin.strip().upper()
        self.max_order_history = max_order_history
        self._captured_at = snapshot.captured_at
        self._positions = {
            self._position_key(position): position
            for position in snapshot.positions
            if _matches_base_coin(position.symbol, self.base_coin)
        }
        self._open_orders = {
            self._order_key(order): order
            for order in snapshot.open_orders
            if _matches_base_coin(order.symbol, self.base_coin)
        }
        self._order_history = list(snapshot.order_history[-max_order_history:])
        self._history_keys = {self._history_key(order) for order in self._order_history}
        self._execution_ids = {
            order.execution_id for order in self._order_history if order.execution_id
        }
        self._issues = list(snapshot.issues)

    @staticmethod
    def _position_key(position: TrackedPosition) -> tuple[str, str, int | None, str]:
        return (position.category, position.symbol, position.position_idx, position.side.value)

    @staticmethod
    def _order_key(order: TrackedOrder) -> tuple[str, str]:
        return (order.category, order.order_id)

    @staticmethod
    def _history_key(order: TrackedOrder) -> tuple[str, str, str, str | None]:
        if order.execution_id:
            return ("execution", order.category, order.order_id, order.execution_id)
        return (
            "order",
            order.category,
            order.order_id,
            order.updated_at.isoformat() if order.updated_at else None,
        )

    def apply(self, message: Mapping[str, Any]) -> PositionSnapshot | None:
        topic = str(message.get("topic") or "")
        if topic not in {"position", "order", "execution"} and not topic.startswith(
            ("position.", "order.", "execution.")
        ):
            return None
        event_time = _timestamp(message.get("creationTime"), self._captured_at)
        self._captured_at = max(self._captured_at, event_time)
        category = _topic_category(topic)
        data = message.get("data") or []
        if isinstance(data, Mapping):
            data = [data]

        if topic.startswith("position"):
            for raw in data:
                self._apply_position(raw, category, event_time)
        elif topic.startswith("order"):
            for raw in data:
                self._apply_order(raw, category, event_time)
        elif topic.startswith("execution"):
            for raw in data:
                self._apply_execution(raw, category, event_time)
        return self.snapshot()

    def _apply_position(
        self, raw: Mapping[str, Any], category: str | None, event_time: datetime
    ) -> None:
        symbol = str(raw.get("symbol") or "").strip().upper()
        category = str(raw.get("category") or category or "").strip().lower()
        if not symbol or not category or not _matches_base_coin(symbol, self.base_coin):
            return
        try:
            position_idx = (
                int(raw["positionIdx"]) if raw.get("positionIdx") not in (None, "") else None
            )
        except (TypeError, ValueError) as exc:
            self._issues.append(f"invalid_stream_position:{category}:{symbol}:{exc}")
            return
        side = str(raw.get("side") or "").strip().lower()
        size = _number(raw.get("size"))
        if not side or size <= 0:
            for key in list(self._positions):
                if key[0] == category and key[1] == symbol and (
                    position_idx is None or key[2] == position_idx
                ):
                    self._positions.pop(key, None)
            return
        try:
            position = _position_from_event(raw, category=category, observed_at=event_time)
        except (TypeError, ValueError, AttributeError) as exc:
            self._issues.append(f"invalid_stream_position:{category}:{symbol}:{exc}")
            return
        for key in list(self._positions):
            if key[:3] == (category, symbol, position_idx) and key[3] != position.side.value:
                self._positions.pop(key, None)
        self._positions[self._position_key(position)] = position

    def _apply_order(
        self, raw: Mapping[str, Any], category: str | None, event_time: datetime
    ) -> None:
        category = str(raw.get("category") or category or "").strip().lower()
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not category or not symbol or not _matches_base_coin(symbol, self.base_coin):
            return
        try:
            order = TrackedOrder.from_exchange(raw, category=category)
        except (TypeError, ValueError, AttributeError) as exc:
            self._issues.append(f"invalid_stream_order:{category}:{symbol}:{exc}")
            return
        order_key = self._order_key(order)
        status = order.status.strip().lower().replace(" ", "")
        if status in self._TERMINAL_ORDER_STATUSES:
            self._open_orders.pop(order_key, None)
            self._remember_history(order)
        else:
            self._open_orders[order_key] = order

    def _apply_execution(
        self, raw: Mapping[str, Any], category: str | None, event_time: datetime
    ) -> None:
        category = str(raw.get("category") or category or "").strip().lower()
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not category or not symbol or not _matches_base_coin(symbol, self.base_coin):
            return
        exec_id = str(raw.get("execId") or "").strip()
        if exec_id:
            if exec_id in self._execution_ids:
                return
            self._execution_ids.add(exec_id)
        execution = dict(raw)
        execution.setdefault("orderStatus", "Filled")
        execution.setdefault("orderType", execution.get("orderType") or "Market")
        execution.setdefault("qty", execution.get("orderQty") or execution.get("execQty"))
        execution.setdefault("leavesQty", execution.get("leavesQty") or "0")
        execution.setdefault("cumExecQty", execution.get("cumExecQty") or execution.get("execQty"))
        execution.setdefault("avgPrice", execution.get("avgPrice") or execution.get("execPrice"))
        execution.setdefault("cumExecFee", execution.get("cumExecFee") or execution.get("execFee"))
        execution.setdefault("updatedTime", execution.get("updatedTime") or execution.get("execTime"))
        try:
            order = TrackedOrder.from_exchange(execution, category=category)
        except (TypeError, ValueError, AttributeError) as exc:
            self._issues.append(f"invalid_stream_execution:{category}:{symbol}:{exc}")
            return
        self._open_orders.pop(self._order_key(order), None)
        self._remember_history(order)

    def _remember_history(self, order: TrackedOrder) -> None:
        key = self._history_key(order)
        if key in self._history_keys:
            return
        self._history_keys.add(key)
        self._order_history.append(order)
        if len(self._order_history) > self.max_order_history:
            removed = self._order_history.pop(0)
            self._history_keys.discard(self._history_key(removed))

    def snapshot(self) -> PositionSnapshot:
        return PositionSnapshot(
            captured_at=self._captured_at,
            source="bybit-websocket",
            positions=tuple(self._positions.values()),
            open_orders=tuple(self._open_orders.values()),
            order_history=tuple(self._order_history),
            reconciliation_status="complete" if not self._issues else "partial",
            issues=tuple(self._issues),
        )

    def mark_partial(self, issue: str) -> PositionSnapshot:
        """Mark the current projection unsafe to treat as a clean HOLD."""

        if issue not in self._issues:
            self._issues.append(issue)
        return self.snapshot()


class BybitPrivateWebSocket:
    """Authenticated, reconnecting transport for Bybit private account topics."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        testnet: bool = False,
        connect: Callable[..., Any] | None = None,
        heartbeat_seconds: float = 20,
        reconnect_delay: float = 1,
        max_reconnects: int | None = None,
    ) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Bybit private stream requires API credentials")
        if heartbeat_seconds <= 0 or reconnect_delay < 0:
            raise ValueError("heartbeat_seconds must be positive and reconnect_delay cannot be negative")
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.connect = connect or websockets.connect
        self.heartbeat_seconds = heartbeat_seconds
        self.reconnect_delay = reconnect_delay
        self.max_reconnects = max_reconnects

    @property
    def url(self) -> str:
        host = "stream-testnet.bybit.com" if self.testnet else "stream.bybit.com"
        return f"wss://{host}/v5/private"

    @classmethod
    def from_client(cls, client: Any, **kwargs: Any) -> BybitPrivateWebSocket:
        private = getattr(client, "private", None)
        credentials = getattr(private, "credentials", None)
        if credentials is None:
            raise ValueError("Private operations require API credentials")
        return cls(
            credentials.api_key,
            credentials.api_secret,
            testnet=bool(credentials.testnet),
            **kwargs,
        )

    @staticmethod
    def topics(position_type: str) -> tuple[str, ...]:
        normalized = position_type.strip().lower()
        if normalized == "all":
            suffix = ""
        elif normalized in {"option", "linear", "inverse"}:
            suffix = f".{normalized}"
        else:
            raise ValueError(f"unsupported position_type: {position_type}")
        return tuple(f"{topic}{suffix}" for topic in ("position", "order", "execution"))

    def _signature(self, expires: int) -> str:
        payload = f"GET/realtime{expires}".encode()
        return hmac.new(self.api_secret.encode(), payload, hashlib.sha256).hexdigest()

    async def _authenticate(self, websocket: Any) -> None:
        expires = int((time.time() + 5) * 1000)
        await websocket.send(
            json.dumps({"op": "auth", "args": [self.api_key, expires, self._signature(expires)]})
        )
        response = json.loads(await websocket.recv())
        if response.get("success") is not True:
            raise BybitPrivateStreamError(response.get("ret_msg") or "Bybit private stream authentication failed")

    async def _subscribe(self, websocket: Any, topics: tuple[str, ...]) -> None:
        await websocket.send(json.dumps({"op": "subscribe", "args": list(topics)}))
        response = json.loads(await websocket.recv())
        if response.get("op") != "subscribe" or response.get("success") is not True:
            raise BybitPrivateStreamError(
                response.get("ret_msg") or "Bybit private stream subscription failed"
            )

    async def _heartbeat(self, websocket: Any) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await websocket.send(json.dumps({"op": "ping"}))

    async def messages(self, position_type: str = "all") -> AsyncIterator[dict[str, Any]]:
        topics = self.topics(position_type)
        reconnects = 0
        connected_once = False
        while True:
            try:
                async with self.connect(
                    self.url,
                    ping_interval=None,
                    close_timeout=5,
                ) as websocket:
                    await self._authenticate(websocket)
                    await self._subscribe(websocket, topics)
                    reconnects = 0
                    yield {
                        "type": "stream_status",
                        "status": "connected",
                        "reconnected": connected_once,
                        "topics": list(topics),
                    }
                    connected_once = True
                    heartbeat = asyncio.create_task(self._heartbeat(websocket))
                    try:
                        async for raw in websocket:
                            message = json.loads(raw)
                            if message.get("topic") in topics:
                                yield message
                    finally:
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except BybitPrivateStreamError:
                raise
            except Exception as exc:
                reconnects += 1
                logger.warning("Bybit private stream disconnected: %s", exc)
                if self.max_reconnects is not None and reconnects > self.max_reconnects:
                    raise BybitPrivateStreamError(
                        f"Bybit private stream reconnect limit reached: {exc}"
                    ) from exc
                yield {
                    "type": "stream_status",
                    "status": "disconnected",
                    "reconnected": False,
                    "error": str(exc),
                }
                await asyncio.sleep(self.reconnect_delay)


class LiveMonitoringSession:
    """Join REST bootstrap, private deltas, deterministic decisions, and storage."""

    def __init__(
        self,
        *,
        adapter: PositionSnapshotAdapter,
        tracker: PositionTracker,
        stream: BybitPrivateWebSocket,
        history: Any,
        base_coin: str,
        position_type: str,
        policies: Mapping[str, Any] | None = None,
        persist: bool = True,
    ) -> None:
        self.adapter = adapter
        self.tracker = tracker
        self.stream = stream
        self.history = history
        self.base_coin = base_coin.strip().upper()
        self.position_type = position_type.strip().lower()
        self.policies = policies or {}
        self.persist = persist

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        snapshot = await self.adapter.fetch_snapshot(
            base_coin=self.base_coin,
            position_type=self.position_type,
            as_of=datetime.now(tz=UTC),
        )
        reducer = MonitoringSnapshotReducer(snapshot, base_coin=self.base_coin)
        yield await self._report_event(self.tracker.evaluate_snapshot(snapshot, self.policies))

        async for event in self.stream.messages(self.position_type):
            if event.get("type") == "stream_status":
                if event.get("status") == "disconnected":
                    yield event | {"execution_allowed": False}
                    yield await self._report_event(
                        self.tracker.evaluate_snapshot(
                            reducer.mark_partial("stream_disconnected"), self.policies
                        )
                    )
                    continue
                if event.get("status") == "connected" and event.get("reconnected"):
                    snapshot = await self.adapter.fetch_snapshot(
                        base_coin=self.base_coin,
                        position_type=self.position_type,
                        as_of=datetime.now(tz=UTC),
                    )
                    reducer = MonitoringSnapshotReducer(snapshot, base_coin=self.base_coin)
                    yield {
                        "type": "stream_status",
                        "status": "reconciled",
                        "execution_allowed": False,
                    }
                    yield await self._report_event(self.tracker.evaluate_snapshot(snapshot, self.policies))
                else:
                    yield event | {"execution_allowed": False}
                continue
            append_event = getattr(self.history, "append_event", None)
            if self.persist and append_event is not None:
                try:
                    append_event(event)
                except SnapshotHistoryError:
                    logger.exception("Failed to persist raw Bybit stream event")
            updated = reducer.apply(event)
            if updated is not None:
                yield await self._report_event(self.tracker.evaluate_snapshot(updated, self.policies))

    async def _report_event(self, report: MonitoringReport) -> dict[str, Any]:
        persistence: dict[str, Any] = {"enabled": bool(self.persist), "status": "disabled"}
        if self.persist:
            try:
                persistence = {
                    "enabled": True,
                    "status": "saved",
                    "snapshot_id": self.history.append(report),
                }
            except SnapshotHistoryError as exc:
                persistence = {"enabled": True, "status": "failed", "error": str(exc)}
        return {
            "type": "snapshot",
            "payload": report.to_dict(),
            "persistence": persistence,
            "execution_allowed": False,
            "requires_human_confirmation": True,
        }
