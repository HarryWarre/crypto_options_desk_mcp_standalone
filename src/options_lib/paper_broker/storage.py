"""SQLite Persistence for Paper Trading.

Saves and restores virtual account balances, active positions, trade logs,
and equity snapshots over time.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .account import PaperAccount, PaperPosition, PaperTrade

if TYPE_CHECKING:
    from .margin_calculator import MarginSummary


class PaperStorage:
    """Manages SQLite storage for paper trading sessions."""

    def __init__(self, db_path: str | Path = "portfolio_data/paper_trading.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    account_id TEXT PRIMARY KEY,
                    initial_capital REAL NOT NULL,
                    cash_balance REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_spot REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    current_mark_price REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    strategy_id TEXT,
                    leg_role TEXT,
                    PRIMARY KEY (account_id, symbol)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    strategy_id TEXT,
                    leg_role TEXT,
                    realized_pnl REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    equity REAL NOT NULL,
                    cash_balance REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    margin_used REAL NOT NULL,
                    margin_utilization_pct REAL NOT NULL
                )
                """
            )

    def save_account(
        self,
        account: PaperAccount,
        margin_summary: MarginSummary | None = None,
    ) -> None:
        """Atomically persist account balances, positions, trades, and optional snapshot."""
        now = datetime.now(UTC).isoformat()
        with self._get_conn() as conn:
            # 1. Upsert account
            conn.execute(
                """
                INSERT INTO paper_accounts (account_id, initial_capital, cash_balance, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    cash_balance=excluded.cash_balance,
                    updated_at=excluded.updated_at
                """,
                (
                    account.account_id,
                    account.initial_capital,
                    account.cash_balance,
                    now,
                ),
            )

            # 2. Sync positions (clear old ones for this account, insert current)
            conn.execute(
                "DELETE FROM paper_positions WHERE account_id = ?",
                (account.account_id,),
            )
            for pos in account.positions.values():
                conn.execute(
                    """
                    INSERT INTO paper_positions (
                        account_id, symbol, side, qty, entry_price, entry_spot,
                        entry_time, current_mark_price, unrealized_pnl, realized_pnl,
                        strategy_id, leg_role
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.account_id,
                        pos.symbol,
                        pos.side,
                        pos.qty,
                        pos.entry_price,
                        pos.entry_spot,
                        pos.entry_time,
                        pos.current_mark_price,
                        pos.unrealized_pnl,
                        pos.realized_pnl,
                        pos.strategy_id,
                        pos.leg_role,
                    ),
                )

            # 3. Insert any new trades not already saved
            for trade in account.trade_history:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO paper_trades (
                        trade_id, account_id, order_id, symbol, side, qty, price, fee,
                        timestamp, strategy_id, leg_role, realized_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.trade_id,
                        account.account_id,
                        trade.order_id,
                        trade.symbol,
                        trade.side,
                        trade.qty,
                        trade.price,
                        trade.fee,
                        trade.timestamp,
                        trade.strategy_id,
                        trade.leg_role,
                        trade.realized_pnl,
                    ),
                )

            # 4. Record snapshot if margin_summary given
            if margin_summary is not None:
                conn.execute(
                    """
                    INSERT INTO paper_snapshots (
                        account_id, timestamp, equity, cash_balance, unrealized_pnl,
                        margin_used, margin_utilization_pct
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.account_id,
                        now,
                        margin_summary.equity,
                        account.cash_balance,
                        account.total_unrealized_pnl,
                        margin_summary.initial_margin,
                        margin_summary.margin_utilization_pct,
                    ),
                )

    def load_account(
        self,
        account_id: str = "default_paper",
        default_capital: float = 10000.0,
    ) -> PaperAccount:
        """Restore account state from SQLite or return a fresh initialized account."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM paper_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()

            if not row:
                account = PaperAccount(
                    account_id=account_id,
                    initial_capital=default_capital,
                )
                self.save_account(account)
                return account

            account = PaperAccount(
                account_id=row["account_id"],
                initial_capital=row["initial_capital"],
            )
            account.cash_balance = row["cash_balance"]

            # Load positions
            pos_rows = conn.execute(
                "SELECT * FROM paper_positions WHERE account_id = ?",
                (account_id,),
            ).fetchall()
            for pr in pos_rows:
                pos = PaperPosition(
                    symbol=pr["symbol"],
                    side=pr["side"],
                    qty=pr["qty"],
                    entry_price=pr["entry_price"],
                    entry_spot=pr["entry_spot"],
                    entry_time=pr["entry_time"],
                    current_mark_price=pr["current_mark_price"],
                    unrealized_pnl=pr["unrealized_pnl"],
                    realized_pnl=pr["realized_pnl"],
                    strategy_id=pr["strategy_id"],
                    leg_role=pr["leg_role"],
                )
                account.positions[pos.symbol] = pos

            # Load trades
            trade_rows = conn.execute(
                "SELECT * FROM paper_trades WHERE account_id = ? ORDER BY timestamp ASC",
                (account_id,),
            ).fetchall()
            for tr in trade_rows:
                trade = PaperTrade(
                    trade_id=tr["trade_id"],
                    order_id=tr["order_id"],
                    symbol=tr["symbol"],
                    side=tr["side"],
                    qty=tr["qty"],
                    price=tr["price"],
                    fee=tr["fee"],
                    timestamp=tr["timestamp"],
                    strategy_id=tr["strategy_id"],
                    leg_role=tr["leg_role"],
                    realized_pnl=tr["realized_pnl"],
                )
                account.trade_history.append(trade)

            return account

    def get_snapshots(
        self,
        account_id: str = "default_paper",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve recent portfolio equity snapshots for charting."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM paper_snapshots
                WHERE account_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (account_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def record_snapshot(
        self,
        account: PaperAccount,
        margin_summary: MarginSummary,
    ) -> None:
        """Record an instantaneous portfolio snapshot without touching positions table."""
        now = datetime.now(UTC).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO paper_snapshots (
                    account_id, timestamp, equity, cash_balance, unrealized_pnl,
                    margin_used, margin_utilization_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account.account_id,
                    now,
                    margin_summary.equity,
                    account.cash_balance,
                    account.total_unrealized_pnl,
                    margin_summary.initial_margin,
                    margin_summary.margin_utilization_pct,
                ),
            )


