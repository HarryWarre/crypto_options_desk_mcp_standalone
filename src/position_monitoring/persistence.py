"""Append-only local history for monitoring snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
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
