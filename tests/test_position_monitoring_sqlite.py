from datetime import UTC, datetime

from position_monitoring import (
    DecisionAction,
    DecisionSeverity,
    ExitDecision,
    MonitoringReport,
    PositionSnapshot,
    RiskAssessment,
    SQLiteSnapshotHistory,
    TrackedPosition,
)


def report(*, mark_price: float, action: DecisionAction = DecisionAction.HOLD) -> MonitoringReport:
    captured_at = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    position = TrackedPosition(
        symbol="BTCUSDT",
        category="linear",
        side="long",
        quantity=1,
        avg_entry_price=100,
        mark_price=mark_price,
        unrealized_pnl=mark_price - 100,
        observed_at=captured_at,
        source="fixture",
    )
    decision = ExitDecision(
        symbol="BTCUSDT",
        action=action,
        severity=DecisionSeverity.INFO,
        reasons=("test",),
        assessment=RiskAssessment(
            symbol="BTCUSDT",
            unrealized_pnl=position.unrealized_pnl,
            loss_pct=None,
            liquidation_distance_pct=None,
            holding_hours=None,
        ),
    )
    return MonitoringReport(
        snapshot=PositionSnapshot(
            captured_at=captured_at,
            source="fixture",
            positions=(position,),
        ),
        decisions=(decision,),
    )


def test_sqlite_history_persists_complete_records_and_deduplicates(tmp_path) -> None:
    history = SQLiteSnapshotHistory(tmp_path / "monitoring.sqlite3")

    snapshot_id = history.append(report(mark_price=105))
    assert history.append(report(mark_price=105)) == snapshot_id
    history.append(report(mark_price=110, action=DecisionAction.REVIEW))

    records = history.load(limit=10)
    assert len(records) == 2
    assert records[0]["positions"][0]["mark_price"] == 105
    assert records[1]["decisions"][0]["action"] == "review"
    assert records[0]["snapshot_id"] == snapshot_id


def test_sqlite_history_validates_limit(tmp_path) -> None:
    history = SQLiteSnapshotHistory(tmp_path / "monitoring.sqlite3")

    try:
        history.load(limit=0)
    except ValueError as exc:
        assert "between 1 and 1000" in str(exc)
    else:
        raise AssertionError("invalid history limit should fail")


def test_sqlite_history_deduplicates_raw_stream_events(tmp_path) -> None:
    history = SQLiteSnapshotHistory(tmp_path / "monitoring.sqlite3")
    event = {
        "id": "message-1",
        "topic": "execution.linear",
        "creationTime": 1789646434000,
        "data": [{"category": "linear", "symbol": "BTCUSDT", "execId": "exec-1"}],
    }

    assert history.append_event(event) == 1
    assert history.append_event(event) == 0
    assert history.event_count() == 1
