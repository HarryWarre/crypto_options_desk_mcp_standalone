from datetime import UTC, datetime

import pytest

from bybit_api.models import Position
from position_monitoring import (
    BybitPositionSnapshotAdapter,
    DecisionAction,
    ExitPolicy,
    PositionSnapshot,
    PositionTracker,
    TrackedPosition,
)

AS_OF = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def exchange_position(symbol: str, category: str, side: str = "Buy") -> Position:
    return Position(
        symbol=symbol,
        side=side,
        size=2,
        avg_price=100,
        mark_price=105,
        unrealised_pnl=10,
        realised_pnl=0,
        category=category,
        exchange="bybit",
        liquidation_price=80 if category == "linear" else None,
        leverage=2 if category == "linear" else None,
        position_value=210,
    )


class FakeBybitClient:
    def __init__(self, *, failed_categories: set[str] | None = None) -> None:
        self.failed_categories = failed_categories or set()
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    async def get_positions(self, category: str, **kwargs):
        self.calls.append(
            ("positions", category, kwargs.get("base_coin"), kwargs.get("settle_coin"))
        )
        if category in self.failed_categories:
            raise RuntimeError(f"{category} unavailable")
        if category == "option":
            coin = kwargs["base_coin"]
            return [exchange_position(f"{coin}-25SEP26-100000-C", category)]
        if category == "linear":
            return [exchange_position("ETHUSDT", category)]
        return [exchange_position("BTCUSD0926", category, side="Sell")]

    async def get_open_orders(self, category: str, **kwargs):
        self.calls.append(
            ("open_orders", category, kwargs.get("base_coin"), kwargs.get("settle_coin"))
        )
        return [
            {
                "orderId": f"open-{category}",
                "orderLinkId": f"manual-{category}",
                "symbol": "BTCUSDT" if category != "option" else "BTC-25SEP26-100000-C",
                "side": "Sell",
                "orderStatus": "New",
                "orderType": "Limit",
                "qty": "2",
                "leavesQty": "2",
                "cumExecQty": "0",
                "price": "110",
                "reduceOnly": "true",
                "updatedTime": "1789646400000",
            }
        ]

    async def get_order_history(self, category: str, **kwargs):
        self.calls.append(
            ("order_history", category, kwargs.get("base_coin"), kwargs.get("settle_coin"))
        )
        return [
            {
                "orderId": f"filled-{category}",
                "symbol": "BTCUSDT" if category != "option" else "BTC-25SEP26-100000-C",
                "side": "Buy",
                "orderStatus": "Filled",
                "orderType": "Market",
                "qty": "2",
                "leavesQty": "0",
                "cumExecQty": "2",
                "avgPrice": "100",
                "cumExecFee": "0.2",
            }
        ]


@pytest.mark.asyncio
async def test_bybit_adapter_collects_positions_open_orders_and_history() -> None:
    client = FakeBybitClient()
    adapter = BybitPositionSnapshotAdapter(client, option_coins=("BTC", "ETH"))

    snapshot = await adapter.fetch_snapshot(
        base_coin="all",
        position_type="all",
        as_of=AS_OF,
    )

    assert snapshot.reconciliation_status == "complete"
    assert {position.symbol for position in snapshot.positions} == {
        "BTC-25SEP26-100000-C",
        "ETH-25SEP26-100000-C",
        "ETHUSDT",
        "BTCUSD0926",
    }
    assert len(snapshot.open_orders) == 4
    assert len(snapshot.order_history) == 4
    assert snapshot.open_orders[0].client_order_id == "manual-option"
    assert snapshot.open_orders[0].reduce_only is True
    assert snapshot.order_history[0].cumulative_filled_quantity == 2
    assert snapshot.order_history[0].executed_fee == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_adapter_supports_category_and_asset_filter() -> None:
    client = FakeBybitClient()
    adapter = BybitPositionSnapshotAdapter(client)

    snapshot = await adapter.fetch_snapshot(
        base_coin="btc",
        position_type="option",
        as_of=AS_OF,
    )

    assert [position.symbol for position in snapshot.positions] == ["BTC-25SEP26-100000-C"]
    assert all(order.category == "option" for order in snapshot.open_orders)
    assert {call[1] for call in client.calls} == {"option"}


@pytest.mark.asyncio
async def test_partial_category_failure_is_visible_and_blocks_clean_hold() -> None:
    client = FakeBybitClient(failed_categories={"inverse"})
    adapter = BybitPositionSnapshotAdapter(client)
    snapshot = await adapter.fetch_snapshot(
        base_coin="all",
        position_type="all",
        as_of=AS_OF,
    )

    assert snapshot.reconciliation_status == "partial"
    assert any(issue.startswith("fetch_failed:inverse") for issue in snapshot.issues)

    class StaticAdapter:
        async def fetch_snapshot(self, **kwargs):
            return snapshot

    report = await PositionTracker(StaticAdapter()).monitor(
        base_coin="all",
        policies={
            "BTC-25SEP26-100000-C": ExitPolicy(
                symbol="BTC-25SEP26-100000-C",
                stop_loss_price=80,
                take_profit_price=130,
            )
        },
        as_of=AS_OF,
    )

    assert report.decisions
    assert all(decision.action is DecisionAction.REVIEW for decision in report.decisions)
    assert "snapshot_partial" in report.decisions[0].reasons


@pytest.mark.asyncio
async def test_tracker_produces_manual_close_decision_without_side_effects() -> None:
    position = TrackedPosition(
        symbol="BTCUSDT",
        category="linear",
        side="long",
        quantity=1,
        avg_entry_price=100,
        mark_price=80,
        unrealized_pnl=-20,
        observed_at=AS_OF,
        source="fixture",
    )
    snapshot = PositionSnapshot(captured_at=AS_OF, source="fixture", positions=(position,))

    class StaticAdapter:
        async def fetch_snapshot(self, **kwargs):
            return snapshot

    report = await PositionTracker(StaticAdapter()).monitor(
        policies={
            "BTCUSDT": ExitPolicy(symbol="BTCUSDT", stop_loss_price=90),
        },
        as_of=AS_OF,
    )

    decision = report.decisions[0]
    assert decision.action is DecisionAction.CLOSE
    assert decision.manual_close_instruction["side"] == "sell"
