"""SQLite historical equity timeseries storage for 1D/1W/1M portfolio charting."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


class EquityHistoryStore:
    """Stores and queries portfolio equity snapshots for charting."""

    def __init__(self, db_path: str = "portfolio_data/paper_trading.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deribit_equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    equity_usd REAL NOT NULL,
                    balance_crypto REAL NOT NULL,
                    margin_used REAL NOT NULL,
                    margin_utilization_pct REAL NOT NULL,
                    net_delta REAL NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_equity_hist_ts
                ON deribit_equity_history(timestamp);
                """
            )
            conn.commit()

    def record_snapshot(
        self,
        currency: str,
        equity_usd: float,
        balance_crypto: float = 0.0,
        margin_used: float = 0.0,
        margin_utilization_pct: float = 0.0,
        net_delta: float = 0.0,
        timestamp: str | None = None,
    ) -> None:
        """Insert a new equity snapshot."""
        ts = timestamp or datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO deribit_equity_history (
                    timestamp, currency, equity_usd, balance_crypto,
                    margin_used, margin_utilization_pct, net_delta
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    ts,
                    currency.upper(),
                    float(equity_usd),
                    float(balance_crypto),
                    float(margin_used),
                    float(margin_utilization_pct),
                    float(net_delta),
                ),
            )
            conn.commit()

    def get_history(
        self,
        timeframe: Literal["1d", "1w", "1m"] = "1d",
        currency: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve equity history for charting filtered by 1D, 1W, or 1M."""
        now = datetime.now(UTC)
        tf = timeframe.lower()
        if tf == "1w":
            since_dt = now - timedelta(days=7)
        elif tf == "1m":
            since_dt = now - timedelta(days=30)
        else:  # Default 1d
            since_dt = now - timedelta(days=1)

        since_iso = since_dt.isoformat()

        query = "SELECT * FROM deribit_equity_history WHERE timestamp >= ?"
        params: list[Any] = [since_iso]

        if currency:
            query += " AND currency = ?"
            params.append(currency.upper())

        query += " ORDER BY timestamp ASC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "timestamp": r["timestamp"],
                    "currency": r["currency"],
                    "equity_usd": round(r["equity_usd"], 2),
                    "balance_crypto": round(r["balance_crypto"], 4),
                    "margin_used": round(r["margin_used"], 2),
                    "margin_utilization_pct": round(r["margin_utilization_pct"], 2),
                    "net_delta": round(r["net_delta"], 4),
                }
                for r in rows
            ]
