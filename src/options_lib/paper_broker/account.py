"""Virtual Paper Account and Position Tracking.

Tracks cash balance, open positions, realized and unrealized PnL,
and trade history for simulated options trading.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class PaperPosition:
    """An open options position in the paper account."""

    symbol: str
    side: str  # "Buy" or "Sell"
    qty: float
    entry_price: float  # premium per contract
    entry_spot: float = 0.0
    entry_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    current_mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    strategy_id: str | None = None
    leg_role: str | None = None  # e.g. "short_call", "long_call_wing", etc.

    def update_mark(self, mark_price: float) -> float:
        """Update current mark price and recompute unrealized PnL."""
        self.current_mark_price = mark_price
        if self.side == "Buy":
            self.unrealized_pnl = (mark_price - self.entry_price) * self.qty
        else:  # "Sell"
            self.unrealized_pnl = (self.entry_price - mark_price) * self.qty
        return self.unrealized_pnl

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "entry_spot": self.entry_spot,
            "entry_time": self.entry_time,
            "current_mark_price": self.current_mark_price,
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "strategy_id": self.strategy_id,
            "leg_role": self.leg_role,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperPosition:
        return cls(
            symbol=data["symbol"],
            side=data["side"],
            qty=float(data["qty"]),
            entry_price=float(data["entry_price"]),
            entry_spot=float(data.get("entry_spot", 0.0)),
            entry_time=data.get("entry_time", datetime.now(UTC).isoformat()),
            current_mark_price=float(data.get("current_mark_price", 0.0)),
            unrealized_pnl=float(data.get("unrealized_pnl", 0.0)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
            strategy_id=data.get("strategy_id"),
            leg_role=data.get("leg_role"),
        )


@dataclass
class PaperTrade:
    """Execution record for a paper trade."""

    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    order_id: str = ""
    symbol: str = ""
    side: str = "Buy"  # "Buy" or "Sell"
    qty: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    strategy_id: str | None = None
    leg_role: str | None = None
    realized_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "price": self.price,
            "fee": self.fee,
            "timestamp": self.timestamp,
            "strategy_id": self.strategy_id,
            "leg_role": self.leg_role,
            "realized_pnl": round(self.realized_pnl, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperTrade:
        return cls(
            trade_id=data["trade_id"],
            order_id=data.get("order_id", ""),
            symbol=data["symbol"],
            side=data["side"],
            qty=float(data["qty"]),
            price=float(data["price"]),
            fee=float(data.get("fee", 0.0)),
            timestamp=data.get("timestamp", datetime.now(UTC).isoformat()),
            strategy_id=data.get("strategy_id"),
            leg_role=data.get("leg_role"),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
        )


class PaperAccount:
    """Simulated trading account maintaining portfolio balances and positions."""

    def __init__(
        self,
        account_id: str = "default_paper",
        initial_capital: float = 10000.0,
    ) -> None:
        self.account_id = account_id
        self.initial_capital = float(initial_capital)
        self.cash_balance = float(initial_capital)
        self.positions: dict[str, PaperPosition] = {}
        self.trade_history: list[PaperTrade] = []

    @property
    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized PnL across all open positions."""
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    @property
    def equity(self) -> float:
        """Account total equity = Cash + Unrealized PnL."""
        return self.cash_balance + self.total_unrealized_pnl

    def apply_fill(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fee: float,
        spot: float = 0.0,
        strategy_id: str | None = None,
        leg_role: str | None = None,
        order_id: str = "",
    ) -> PaperTrade:
        """Apply a filled order to the account.

        Handles:
        1. Opening new positions.
        2. Increasing existing positions of the same side.
        3. Closing / reducing existing positions of the opposite side.
        """
        existing = self.positions.get(symbol)
        trade = PaperTrade(
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            timestamp=datetime.now(UTC).isoformat(),
            strategy_id=strategy_id,
            leg_role=leg_role,
        )

        if existing is None:
            # New position
            if side == "Buy":
                self.cash_balance -= (qty * price) + fee
            else:  # "Sell"
                self.cash_balance += (qty * price) - fee

            self.positions[symbol] = PaperPosition(
                symbol=symbol,
                side=side,
                qty=qty,
                entry_price=price,
                entry_spot=spot,
                entry_time=trade.timestamp,
                current_mark_price=price,
                unrealized_pnl=0.0,
                strategy_id=strategy_id,
                leg_role=leg_role,
            )
        elif existing.side == side:
            # Increasing existing position in same direction
            total_qty = existing.qty + qty
            weighted_price = (
                (existing.entry_price * existing.qty) + (price * qty)
            ) / total_qty
            existing.qty = total_qty
            existing.entry_price = weighted_price

            if side == "Buy":
                self.cash_balance -= (qty * price) + fee
            else:
                self.cash_balance += (qty * price) - fee

            existing.update_mark(price)
        else:
            # Opposite side: Reducing or closing position
            closed_qty = min(existing.qty, qty)
            # Calculate realized PnL on closed quantity
            if existing.side == "Buy":  # was Long, now Selling to close
                realized = (price - existing.entry_price) * closed_qty
                self.cash_balance += (closed_qty * price) - fee
            else:  # was Short, now Buying to close
                realized = (existing.entry_price - price) * closed_qty
                self.cash_balance -= (closed_qty * price) + fee

            trade.realized_pnl = realized
            existing.realized_pnl += realized

            remaining_qty = existing.qty - closed_qty
            if remaining_qty <= 1e-9:
                del self.positions[symbol]
            else:
                existing.qty = remaining_qty
                existing.update_mark(existing.current_mark_price)

            # If order quantity exceeded existing position, open the excess in new direction
            excess_qty = qty - closed_qty
            if excess_qty > 1e-9:
                if side == "Buy":
                    self.cash_balance -= (excess_qty * price)
                else:
                    self.cash_balance += (excess_qty * price)

                self.positions[symbol] = PaperPosition(
                    symbol=symbol,
                    side=side,
                    qty=excess_qty,
                    entry_price=price,
                    entry_spot=spot,
                    entry_time=trade.timestamp,
                    current_mark_price=price,
                    unrealized_pnl=0.0,
                    strategy_id=strategy_id,
                    leg_role=leg_role,
                )

        self.trade_history.append(trade)
        return trade

    def mark_to_market(self, quotes_by_symbol: dict[str, float]) -> float:
        """Update mark prices for all open positions given live quotes.

        Returns total unrealized PnL.
        """
        for sym, pos in self.positions.items():
            if sym in quotes_by_symbol:
                pos.update_mark(quotes_by_symbol[sym])
        return self.total_unrealized_pnl

    def to_dict(self) -> dict[str, Any]:
        """Serialize account state."""
        return {
            "account_id": self.account_id,
            "initial_capital": round(self.initial_capital, 2),
            "cash_balance": round(self.cash_balance, 4),
            "equity": round(self.equity, 4),
            "unrealized_pnl": round(self.total_unrealized_pnl, 4),
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "trade_count": len(self.trade_history),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperAccount:
        """Restore account state."""
        acc = cls(
            account_id=data.get("account_id", "default_paper"),
            initial_capital=float(data.get("initial_capital", 10000.0)),
        )
        acc.cash_balance = float(data.get("cash_balance", acc.initial_capital))
        positions_data = data.get("positions", {})
        for sym, pdict in positions_data.items():
            acc.positions[sym] = PaperPosition.from_dict(pdict)
        return acc

