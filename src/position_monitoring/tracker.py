"""Position snapshot tracking and exchange adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .engine import ExitDecisionEngine
from .models import ExitDecision, ExitPolicy, PositionSnapshot, TrackedOrder, TrackedPosition


class PositionSnapshotAdapter(Protocol):
    """Read-only seam for an exchange or test snapshot source."""

    async def fetch_snapshot(
        self,
        *,
        base_coin: str,
        position_type: str,
        as_of: datetime,
    ) -> PositionSnapshot: ...


@dataclass(frozen=True)
class MonitoringReport:
    """Snapshot plus one decision for every open position."""

    snapshot: PositionSnapshot
    decisions: tuple[ExitDecision, ...]

    @property
    def summary(self) -> dict[str, int]:
        counts = {"close": 0, "hold": 0, "review": 0}
        for decision in self.decisions:
            counts[decision.action.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.snapshot.captured_at.isoformat(),
            "source": self.snapshot.source,
            "reconciliation_status": self.snapshot.reconciliation_status,
            "issues": list(self.snapshot.issues),
            "positions": [position.to_dict() for position in self.snapshot.positions],
            "open_orders": [order.to_dict() for order in self.snapshot.open_orders],
            "order_history": [order.to_dict() for order in self.snapshot.order_history],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "summary": self.summary,
        }


class PositionTracker:
    """Coordinates one read-only snapshot with deterministic exit decisions."""

    def __init__(
        self,
        adapter: PositionSnapshotAdapter,
        decision_engine: ExitDecisionEngine | None = None,
    ) -> None:
        self.adapter = adapter
        self.decision_engine = decision_engine or ExitDecisionEngine()

    async def monitor(
        self,
        *,
        base_coin: str = "BTC",
        position_type: str = "all",
        policies: Mapping[str, ExitPolicy] | None = None,
        as_of: datetime | None = None,
    ) -> MonitoringReport:
        captured_at = as_of or datetime.now(tz=UTC)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        else:
            captured_at = captured_at.astimezone(UTC)

        snapshot = await self.adapter.fetch_snapshot(
            base_coin=base_coin.strip().upper(),
            position_type=position_type.strip().lower(),
            as_of=captured_at,
        )
        return self.evaluate_snapshot(snapshot, policies)

    def evaluate_snapshot(
        self,
        snapshot: PositionSnapshot,
        policies: Mapping[str, ExitPolicy] | None = None,
    ) -> MonitoringReport:
        """Evaluate a known snapshot without fetching it again.

        This is the seam used by the live stream reducer after each delta.
        Keeping it separate prevents a WebSocket event from triggering a REST
        request for every UI update.
        """

        observation_warnings = tuple(snapshot.issues)
        if snapshot.reconciliation_status != "complete":
            observation_warnings += (f"snapshot_{snapshot.reconciliation_status}",)

        policy_map = policies or {}
        decisions = tuple(
            self.decision_engine.decide(
                position,
                policy_map.get(position.symbol),
                as_of=snapshot.captured_at,
                observation_warnings=observation_warnings,
            )
            for position in snapshot.positions
        )
        return MonitoringReport(snapshot=snapshot, decisions=decisions)


class BybitPositionSnapshotAdapter:
    """Read-only adapter over the existing :class:`BybitClient` methods."""

    _CATEGORIES = ("option", "linear", "inverse")

    def __init__(
        self,
        client: Any,
        *,
        option_coins: Sequence[str] = ("BTC", "ETH", "SOL"),
        order_history_hours: float = 24,
        order_history_limit: int = 50,
        source: str = "bybit-rest",
    ) -> None:
        if order_history_hours <= 0:
            raise ValueError("order_history_hours must be greater than zero")
        if order_history_limit < 1 or order_history_limit > 50:
            raise ValueError("order_history_limit must be between 1 and 50")
        self.client = client
        self.option_coins = tuple(dict.fromkeys(coin.strip().upper() for coin in option_coins))
        self.order_history_hours = float(order_history_hours)
        self.order_history_limit = order_history_limit
        self.source = source

    async def fetch_snapshot(
        self,
        *,
        base_coin: str,
        position_type: str,
        as_of: datetime,
    ) -> PositionSnapshot:
        categories = self._resolve_categories(position_type)
        requested_coin = base_coin.strip().upper()
        if requested_coin != "ALL" and not requested_coin:
            raise ValueError("base_coin cannot be empty")

        positions: list[TrackedPosition] = []
        open_orders: list[TrackedOrder] = []
        order_history: list[TrackedOrder] = []
        issues: list[str] = []
        history_start = as_of - timedelta(hours=self.order_history_hours)

        for category in categories:
            if category == "option":
                coins = self.option_coins if requested_coin == "ALL" else (requested_coin,)
            else:
                coins = ("ALL",) if requested_coin == "ALL" else (requested_coin,)

            for coin in coins:
                try:
                    position_kwargs = self._position_kwargs(category, coin)
                    raw_positions = await self.client.get_positions(**position_kwargs)
                    for raw_position in raw_positions:
                        if requested_coin != "ALL" and not raw_position.symbol.upper().startswith(
                            requested_coin
                        ):
                            continue
                        try:
                            positions.append(
                                TrackedPosition.from_exchange(
                                    raw_position,
                                    observed_at=as_of,
                                    source=self.source,
                                )
                            )
                        except (TypeError, ValueError, AttributeError) as exc:
                            issues.append(f"invalid_position:{category}:{exc}")

                    order_kwargs = self._order_kwargs(category, coin)
                    raw_open_orders = await self.client.get_open_orders(**order_kwargs)
                    for raw_order in raw_open_orders:
                        try:
                            order = TrackedOrder.from_exchange(raw_order, category=category)
                            if requested_coin == "ALL" or order.symbol.startswith(requested_coin):
                                open_orders.append(order)
                        except (TypeError, ValueError, AttributeError) as exc:
                            issues.append(f"invalid_open_order:{category}:{exc}")

                    raw_history = await self.client.get_order_history(
                        **order_kwargs,
                        start_time=history_start,
                        end_time=as_of,
                        limit=self.order_history_limit,
                    )
                    for raw_order in raw_history:
                        try:
                            order = TrackedOrder.from_exchange(raw_order, category=category)
                            if requested_coin == "ALL" or order.symbol.startswith(requested_coin):
                                order_history.append(order)
                        except (TypeError, ValueError, AttributeError) as exc:
                            issues.append(f"invalid_order_history:{category}:{exc}")
                except Exception as exc:  # noqa: BLE001 - isolate one remote category failure
                    issues.append(f"fetch_failed:{category}:{coin}:{exc}")

        deduped_positions = self._dedupe_positions(positions, issues)
        return PositionSnapshot(
            captured_at=as_of,
            source=self.source,
            positions=tuple(deduped_positions),
            open_orders=tuple(open_orders),
            order_history=tuple(order_history),
            reconciliation_status="complete" if not issues else "partial",
            issues=tuple(issues),
        )

    @classmethod
    def _resolve_categories(cls, position_type: str) -> tuple[str, ...]:
        if position_type == "all":
            return cls._CATEGORIES
        if position_type not in cls._CATEGORIES:
            raise ValueError(f"unsupported position_type: {position_type}")
        return (position_type,)

    @staticmethod
    def _position_kwargs(category: str, coin: str) -> dict[str, str]:
        if category == "option":
            return {"category": category, "base_coin": coin}
        if category == "linear":
            return {"category": category, "settle_coin": "USDT"}
        return {"category": category, "settle_coin": "BTC" if coin == "ALL" else coin}

    @staticmethod
    def _order_kwargs(category: str, coin: str) -> dict[str, str]:
        if category == "option":
            return {"category": category, "base_coin": coin}
        return {
            "category": category,
            "settle_coin": "USDT" if category == "linear" else "BTC" if coin == "ALL" else coin,
        }

    @staticmethod
    def _dedupe_positions(
        positions: list[TrackedPosition], issues: list[str]
    ) -> list[TrackedPosition]:
        by_key: dict[tuple[str, str, int | None, str], TrackedPosition] = {}
        for position in positions:
            key = (position.category, position.symbol, position.position_idx, position.side.value)
            if key in by_key:
                issues.append(f"duplicate_position:{position.category}:{position.symbol}:{position.position_idx}")
                continue
            by_key[key] = position
        return list(by_key.values())
