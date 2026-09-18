"""Unit tests for Trade Notebook store."""

import tempfile
from pathlib import Path

import pytest

from position_monitoring.notebook import TrackedNotebookPosition, TradeNotebookStore


def test_notebook_crud_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "notebook_test.sqlite3"
        store = TradeNotebookStore(db_path=db_path)

        # 1. Create
        pos = TrackedNotebookPosition(
            id="test-pos-1",
            created_at="2025-01-01T00:00:00Z",
            asset="BTC",
            strategy_type="bull_call_vertical",
            legs=[
                {"option_type": "call", "strike": 60000.0, "position": 1, "mid_price": 2000.0},
                {"option_type": "call", "strike": 65000.0, "position": -1, "mid_price": 800.0},
            ],
            entry_spot=60000.0,
            target_profit_pct=50.0,
            stop_loss_pct=50.0,
            status="open",
            notes="Scanner signal alpha",
            source="scanner",
        )
        saved = store.save_position(pos)
        assert saved.id == "test-pos-1"

        # 2. Read
        fetched = store.get_position("test-pos-1")
        assert fetched is not None
        assert fetched.asset == "BTC"
        assert fetched.strategy_type == "bull_call_vertical"
        assert len(fetched.legs) == 2
        assert fetched.legs[0]["strike"] == 60000.0

        # 3. List
        positions = store.list_positions(status="open")
        assert len(positions) == 1
        assert positions[0].id == "test-pos-1"

        # 4. Update
        updated = store.update_position("test-pos-1", notes="Updated thesis note")
        assert updated is not None
        assert updated.notes == "Updated thesis note"

        # 5. Close
        closed = store.close_position("test-pos-1", exit_spot=63000.0, exit_pnl=850.0, notes="Took profit at target")
        assert closed is not None
        assert closed.status == "closed"
        assert closed.exit_spot == 63000.0
        assert closed.exit_pnl == 850.0
        assert closed.closed_at is not None

        # Verify list filters
        open_list = store.list_positions(status="open")
        assert len(open_list) == 0
        closed_list = store.list_positions(status="closed")
        assert len(closed_list) == 1

        # 6. Delete
        deleted = store.delete_position("test-pos-1")
        assert deleted is True
        assert store.get_position("test-pos-1") is None
