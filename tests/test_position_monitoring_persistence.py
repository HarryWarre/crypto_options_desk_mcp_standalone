from datetime import UTC, datetime

import pytest

from position_monitoring import (
    DecisionAction,
    ExitDecisionEngine,
    ExitPolicy,
    JsonlSnapshotHistory,
    MonitoringReport,
    PositionSnapshot,
    SnapshotHistoryError,
    TrackedPosition,
    compare_snapshot_records,
    snapshot_id_for,
)

AS_OF = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def report(*, mark_price: float, pnl: float) -> MonitoringReport:
    position = TrackedPosition(
        symbol="BTCUSDT",
        category="linear",
        side="long",
        quantity=2,
        avg_entry_price=100,
        mark_price=mark_price,
        unrealized_pnl=pnl,
        observed_at=AS_OF,
        source="fixture",
    )
    decision = ExitDecisionEngine().decide(
        position,
        ExitPolicy(symbol="BTCUSDT", stop_loss_price=90),
        as_of=AS_OF,
    )
    return MonitoringReport(
        snapshot=PositionSnapshot(
            captured_at=AS_OF,
            source="fixture",
            positions=(position,),
        ),
        decisions=(decision,),
    )


def test_jsonl_history_is_append_only_and_json_safe(tmp_path) -> None:
    store = JsonlSnapshotHistory(tmp_path / "snapshots.jsonl")
    first = report(mark_price=105, pnl=10)
    second = report(mark_price=95, pnl=-5)

    first_id = store.append(first)
    second_id = store.append(second)
    records = store.load(limit=10)

    assert first_id == snapshot_id_for(first)
    assert second_id == snapshot_id_for(second)
    assert first_id != second_id
    assert [record["snapshot_id"] for record in records] == [first_id, second_id]
    assert records[1]["positions"][0]["observed_at"] == AS_OF.isoformat()
    assert records[1]["decisions"][0]["action"] == DecisionAction.HOLD.value


def test_snapshot_diff_reports_pnl_mark_and_decision_change(tmp_path) -> None:
    store = JsonlSnapshotHistory(tmp_path / "snapshots.jsonl")
    before = report(mark_price=105, pnl=10)
    after = report(mark_price=85, pnl=-20)
    before_id = store.append(before)
    after_id = store.append(after)
    records = store.load(limit=10)

    diff = compare_snapshot_records(records[0], records[1])

    assert diff["previous_snapshot_id"] == before_id
    assert diff["current_snapshot_id"] == after_id
    assert diff["position_changes"] == [
        {
            "symbol": "BTCUSDT",
            "quantity_delta": 0.0,
            "mark_price_delta": -20.0,
            "unrealized_pnl_delta": -30.0,
            "decision_before": "hold",
            "decision_after": "close",
        }
    ]


def test_missing_history_is_empty_and_bad_json_is_an_error(tmp_path) -> None:
    path = tmp_path / "snapshots.jsonl"
    store = JsonlSnapshotHistory(path)
    assert store.load() == []

    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(SnapshotHistoryError, match="line 1"):
        store.load()


def test_history_limit_is_bounded() -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        JsonlSnapshotHistory("/tmp/unused.jsonl").load(limit=0)
