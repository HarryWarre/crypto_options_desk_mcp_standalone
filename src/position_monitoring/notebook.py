"""Trade Notebook persistence for paper trading and position tracking.

Allows saving signals from Scanner or custom combinations from Strategy Builder,
storing entry pricing, target profit/stop loss rules, and tracking trade lifecycle.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class TrackedNotebookPosition:
    """A position tracked in the trade notebook."""

    id: str
    created_at: str
    asset: str
    strategy_type: str
    legs: list[dict[str, Any]]
    entry_spot: float
    target_profit_pct: float = 50.0
    stop_loss_pct: float = 50.0
    status: str = "open"  # "open" or "closed"
    notes: str = ""
    source: str = "manual"  # "scanner", "builder", "manual"
    closed_at: str | None = None
    exit_spot: float | None = None
    exit_pnl: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackedNotebookPosition:
        legs = data.get("legs", [])
        if isinstance(legs, str):
            legs = json.loads(legs)
        metadata = data.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return cls(
            id=str(data["id"]),
            created_at=str(data.get("created_at", datetime.now(UTC).isoformat())),
            asset=str(data.get("asset", "BTC")),
            strategy_type=str(data.get("strategy_type", "custom")),
            legs=legs,
            entry_spot=float(data.get("entry_spot", 0.0)),
            target_profit_pct=float(data.get("target_profit_pct", 50.0)),
            stop_loss_pct=float(data.get("stop_loss_pct", 50.0)),
            status=str(data.get("status", "open")),
            notes=str(data.get("notes", "")),
            source=str(data.get("source", "manual")),
            closed_at=data.get("closed_at"),
            exit_spot=float(data["exit_spot"]) if data.get("exit_spot") is not None else None,
            exit_pnl=float(data["exit_pnl"]) if data.get("exit_pnl") is not None else None,
            metadata=metadata,
        )


class TradeNotebookStore:
    """SQLite-backed trade notebook store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            env_path = os.getenv("TRADE_NOTEBOOK_DB_PATH")
            self.db_path = Path(env_path) if env_path else Path("data/trade_notebook.sqlite3")
        else:
            self.db_path = Path(db_path)

        self._ensure_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_notebook (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    strategy_type TEXT NOT NULL,
                    legs TEXT NOT NULL,
                    entry_spot REAL NOT NULL,
                    target_profit_pct REAL NOT NULL DEFAULT 50.0,
                    stop_loss_pct REAL NOT NULL DEFAULT 50.0,
                    status TEXT NOT NULL DEFAULT 'open',
                    notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    closed_at TEXT,
                    exit_spot REAL,
                    exit_pnl REAL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.commit()

    def save_position(self, position: TrackedNotebookPosition) -> TrackedNotebookPosition:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trade_notebook (
                    id, created_at, asset, strategy_type, legs, entry_spot,
                    target_profit_pct, stop_loss_pct, status, notes, source,
                    closed_at, exit_spot, exit_pnl, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.id,
                    position.created_at,
                    position.asset,
                    position.strategy_type,
                    json.dumps(position.legs),
                    position.entry_spot,
                    position.target_profit_pct,
                    position.stop_loss_pct,
                    position.status,
                    position.notes,
                    position.source,
                    position.closed_at,
                    position.exit_spot,
                    position.exit_pnl,
                    json.dumps(position.metadata),
                ),
            )
            conn.commit()
        return position

    def get_position(self, position_id: str) -> TrackedNotebookPosition | None:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM trade_notebook WHERE id = ?",
                (position_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return TrackedNotebookPosition.from_dict(dict(row))

    def list_positions(
        self,
        status: str | None = None,
        asset: str | None = None,
    ) -> list[TrackedNotebookPosition]:
        query = "SELECT * FROM trade_notebook WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if asset:
            query += " AND asset = ?"
            params.append(asset)
        query += " ORDER BY created_at DESC"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [TrackedNotebookPosition.from_dict(dict(r)) for r in rows]

    def update_position(
        self,
        position_id: str,
        **updates: Any,
    ) -> TrackedNotebookPosition | None:
        pos = self.get_position(position_id)
        if pos is None:
            return None

        for k, v in updates.items():
            if hasattr(pos, k):
                setattr(pos, k, v)

        return self.save_position(pos)

    def close_position(
        self,
        position_id: str,
        exit_spot: float | None = None,
        exit_pnl: float | None = None,
        notes: str | None = None,
    ) -> TrackedNotebookPosition | None:
        pos = self.get_position(position_id)
        if pos is None:
            return None

        pos.status = "closed"
        pos.closed_at = datetime.now(UTC).isoformat()
        if exit_spot is not None:
            pos.exit_spot = exit_spot
        if exit_pnl is not None:
            pos.exit_pnl = exit_pnl
        if notes is not None:
            pos.notes = notes

        return self.save_position(pos)

    def delete_position(self, position_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM trade_notebook WHERE id = ?",
                (position_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
