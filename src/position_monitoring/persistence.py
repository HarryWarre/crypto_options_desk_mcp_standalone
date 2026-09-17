"""Append-only local history for monitoring snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tracker import MonitoringReport


class SnapshotHistoryError(RuntimeError):
    """Raised when a monitoring history file cannot be read or written."""


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def snapshot_record(report: MonitoringReport, *, snapshot_id: str | None = None) -> dict[str, Any]:
    """Create a JSON-safe immutable record from a monitoring report."""
    record = report.to_dict()
    record["schema_version"] = 1
    record["snapshot_id"] = snapshot_id or snapshot_id_for(report)
    return record


def snapshot_id_for(report: MonitoringReport) -> str:
    canonical = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


class JsonlSnapshotHistory:
    """Durable append-only store; each line is a complete monitoring record."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, report: MonitoringReport) -> str:
        record = snapshot_record(report)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise SnapshotHistoryError(f"failed to append snapshot history: {exc}") from exc
        return str(record["snapshot_id"])

    def load(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if not self.path.exists():
            return []

        records: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise SnapshotHistoryError(
                            f"invalid snapshot history JSON at line {line_number}"
                        ) from exc
                    if not isinstance(record, dict):
                        raise SnapshotHistoryError(
                            f"snapshot history line {line_number} is not an object"
                        )
                    records.append(record)
        except OSError as exc:
            raise SnapshotHistoryError(f"failed to read snapshot history: {exc}") from exc
        return records[-limit:]


class SQLiteSnapshotHistory:
    """Append-only SQLite store for complete monitoring snapshot documents.

    The store intentionally keeps each snapshot as one immutable JSON document
    behind a small history interface. This preserves the domain shape while
    giving deployments transactions, uniqueness, indexing, and durable local
    storage without requiring an ORM.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monitoring_snapshots (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL UNIQUE,
                    captured_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    reconciliation_status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_monitoring_snapshots_captured_at "
                "ON monitoring_snapshots(captured_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monitoring_events (
                    event_key TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    category TEXT,
                    symbol TEXT,
                    creation_time TEXT,
                    received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise SnapshotHistoryError(f"failed to open SQLite history: {exc}") from exc

    def append(self, report: MonitoringReport) -> str:
        record = snapshot_record(report)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO monitoring_snapshots
                        (snapshot_id, captured_at, source, reconciliation_status, record_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record["snapshot_id"],
                        record["captured_at"],
                        record["source"],
                        record["reconciliation_status"],
                        json.dumps(record, sort_keys=True, separators=(",", ":")),
                    ),
                )
        except (OSError, sqlite3.Error) as exc:
            raise SnapshotHistoryError(f"failed to append SQLite history: {exc}") from exc
        return str(record["snapshot_id"])

    def load(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if not self.path.exists():
            return []

        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT record_json FROM monitoring_snapshots "
                    "ORDER BY sequence DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise SnapshotHistoryError(f"failed to read SQLite history: {exc}") from exc

        records: list[dict[str, Any]] = []
        for row in reversed(rows):
            try:
                record = json.loads(row["record_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise SnapshotHistoryError("invalid snapshot JSON in SQLite history") from exc
            if not isinstance(record, dict):
                raise SnapshotHistoryError("snapshot JSON in SQLite history is not an object")
            records.append(record)
        return records

    def append_event(self, message: Mapping[str, Any]) -> int:
        """Persist one raw private-stream message, returning inserted row count."""

        topic = str(message.get("topic") or "unknown")
        creation_time = message.get("creationTime")
        data = message.get("data") or []
        if isinstance(data, Mapping):
            data = [data]
        if not data:
            data = [{}]
        inserted = 0
        try:
            with self._connect() as connection:
                for item in data:
                    item_json = json.dumps(item, sort_keys=True, separators=(",", ":"))
                    fingerprint = hashlib.sha256(item_json.encode("utf-8")).hexdigest()[:16]
                    event_identity = (
                        item.get("execId")
                        or item.get("orderId")
                        or f"{item.get('symbol', '')}:{item.get('positionIdx', '')}:{fingerprint}"
                    )
                    event_key = f"{topic}:{message.get('id', '')}:{creation_time}:{event_identity}"
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO monitoring_events
                            (event_key, topic, category, symbol, creation_time, received_at, payload_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_key,
                            topic,
                            item.get("category") or topic.split(".")[-1],
                            item.get("symbol"),
                            str(creation_time) if creation_time is not None else None,
                            datetime.now(tz=UTC).isoformat(),
                            json.dumps(message, sort_keys=True, separators=(",", ":")),
                        ),
                    )
                    inserted += cursor.rowcount
        except (OSError, sqlite3.Error) as exc:
            raise SnapshotHistoryError(f"failed to append SQLite event: {exc}") from exc
        return inserted

    def event_count(self) -> int:
        """Return the number of unique raw stream messages stored."""

        if not self.path.exists():
            return 0
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT COUNT(*) AS count FROM monitoring_events").fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise SnapshotHistoryError(f"failed to count SQLite events: {exc}") from exc
        return int(row["count"])


def compare_snapshot_records(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare two serialized reports without inventing missing observations."""
    previous_positions = {
        str(item.get("symbol")): item
        for item in previous.get("positions", [])
        if item.get("symbol")
    }
    current_positions = {
        str(item.get("symbol")): item for item in current.get("positions", []) if item.get("symbol")
    }
    previous_decisions = {
        str(item.get("symbol")): item
        for item in previous.get("decisions", [])
        if item.get("symbol")
    }
    current_decisions = {
        str(item.get("symbol")): item for item in current.get("decisions", []) if item.get("symbol")
    }

    changes = []
    for symbol in sorted(previous_positions.keys() & current_positions.keys()):
        before = previous_positions[symbol]
        after = current_positions[symbol]
        changes.append(
            {
                "symbol": symbol,
                "quantity_delta": _number(after.get("quantity")) - _number(before.get("quantity")),
                "mark_price_delta": _number(after.get("mark_price"))
                - _number(before.get("mark_price")),
                "unrealized_pnl_delta": _number(after.get("unrealized_pnl"))
                - _number(before.get("unrealized_pnl")),
                "decision_before": previous_decisions.get(symbol, {}).get("action"),
                "decision_after": current_decisions.get(symbol, {}).get("action"),
            }
        )

    return {
        "previous_snapshot_id": previous.get("snapshot_id"),
        "current_snapshot_id": current.get("snapshot_id"),
        "added_positions": sorted(current_positions.keys() - previous_positions.keys()),
        "removed_positions": sorted(previous_positions.keys() - current_positions.keys()),
        "position_changes": changes,
        "open_order_count_delta": len(current.get("open_orders", []))
        - len(previous.get("open_orders", [])),
        "order_history_count_delta": len(current.get("order_history", []))
        - len(previous.get("order_history", [])),
    }
