"""Matching Engine for Paper Trading.

Simulates realistic order execution for Bybit options, adhering to:
1. Live market orderbook spreads (Best Bid / Best Ask).
2. Configurable slippage models.
3. Official Bybit Options fee rules (0.03% notional capped at 12.5% premium).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"


@dataclass
class PaperOrder:
    """An order submitted to the paper broker."""

    symbol: str
    side: str  # "Buy" or "Sell"
    qty: float
    order_type: OrderType | str = OrderType.LIMIT
    price: float | None = None  # limit price
    order_id: str = field(default_factory=lambda: f"po_{uuid.uuid4().hex[:10]}")
    time_in_force: str = "GTC"
    strategy_id: str | None = None
    leg_role: str | None = None


@dataclass
class PaperOrderResult:
    """Result of an order execution attempt."""

    order_id: str
    symbol: str
    side: str
    status: str  # "Filled", "Rejected", "Pending"
    filled_qty: float = 0.0
    filled_price: float = 0.0
    fee: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    message: str = ""

    @property
    def is_filled(self) -> bool:
        return self.status == "Filled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "status": self.status,
            "filled_qty": self.filled_qty,
            "filled_price": round(self.filled_price, 4),
            "fee": round(self.fee, 4),
            "timestamp": self.timestamp,
            "message": self.message,
        }


class MatchingEngine:
    """Simulates fills against live Bybit orderbook quotes."""

    def __init__(
        self,
        default_slippage_pct: float = 0.005,  # 0.5% default slippage
        taker_fee_rate: float = 0.0003,  # Bybit 0.03% notional
        maker_fee_rate: float = 0.0002,  # Bybit 0.02% notional
        fee_cap_pct: float = 0.125,  # Max fee 12.5% of premium
    ) -> None:
        self.default_slippage_pct = default_slippage_pct
        self.taker_fee_rate = taker_fee_rate
        self.maker_fee_rate = maker_fee_rate
        self.fee_cap_pct = fee_cap_pct

    def calculate_fee(
        self,
        qty: float,
        fill_price: float,
        spot: float,
        is_taker: bool = True,
    ) -> float:
        """Calculate Bybit option fee: notional * fee_rate capped at 12.5% premium."""
        fee_rate = self.taker_fee_rate if is_taker else self.maker_fee_rate
        notional_fee = qty * (spot if spot > 0 else fill_price) * fee_rate
        premium_cap = (qty * fill_price) * self.fee_cap_pct
        if premium_cap > 0:
            return min(notional_fee, premium_cap)
        return notional_fee

    def match_order(
        self,
        order: PaperOrder,
        best_bid: float,
        best_ask: float,
        spot: float = 0.0,
        mark_price: float | None = None,
        apply_slippage: bool = True,
    ) -> PaperOrderResult:
        """Attempt to fill an order against provided market prices."""
        order_type_str = (
            order.order_type.value
            if isinstance(order.order_type, OrderType)
            else str(order.order_type)
        )

        # Fallback if book has empty quotes (e.g. illiquid strikes)
        if best_bid <= 0 and best_ask <= 0:
            if mark_price is not None and mark_price > 0:
                best_bid = mark_price * 0.95
                best_ask = mark_price * 1.05
            else:
                return PaperOrderResult(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    status="Rejected",
                    message="No liquidity or market quotes available for contract",
                )

        slippage = self.default_slippage_pct if apply_slippage else 0.0

        if order_type_str == OrderType.MARKET.value:
            # Market order always fills at natural price with slippage
            if order.side == "Buy":
                fill_price = (best_ask if best_ask > 0 else (best_bid * 1.05)) * (
                    1.0 + slippage
                )
            else:  # Sell
                fill_price = max(
                    0.01,
                    (best_bid if best_bid > 0 else (best_ask * 0.95))
                    * (1.0 - slippage),
                )

            fee = self.calculate_fee(
                qty=order.qty,
                fill_price=fill_price,
                spot=spot,
                is_taker=True,
            )
            return PaperOrderResult(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                status="Filled",
                filled_qty=order.qty,
                filled_price=fill_price,
                fee=fee,
                message="Market order filled with slippage",
            )

        elif order_type_str == OrderType.LIMIT.value:
            limit_price = order.price or (
                (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
            )

            if order.side == "Buy":
                # Buy limit fills if limit_price >= best_ask (market crossed)
                # or if placing at mid/bid we simulate realistic passive fill
                if best_ask > 0 and limit_price >= best_ask:
                    fill_price = best_ask
                    is_taker = True
                else:
                    # Passive limit fill at limit price
                    fill_price = limit_price
                    is_taker = False

                fee = self.calculate_fee(
                    qty=order.qty,
                    fill_price=fill_price,
                    spot=spot,
                    is_taker=is_taker,
                )
                return PaperOrderResult(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    status="Filled",
                    filled_qty=order.qty,
                    filled_price=fill_price,
                    fee=fee,
                    message="Limit Buy filled",
                )
            else:  # Sell
                if best_bid > 0 and limit_price <= best_bid:
                    fill_price = best_bid
                    is_taker = True
                else:
                    fill_price = limit_price
                    is_taker = False

                fee = self.calculate_fee(
                    qty=order.qty,
                    fill_price=fill_price,
                    spot=spot,
                    is_taker=is_taker,
                )
                return PaperOrderResult(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    status="Filled",
                    filled_qty=order.qty,
                    filled_price=fill_price,
                    fee=fee,
                    message="Limit Sell filled",
                )

        return PaperOrderResult(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            status="Rejected",
            message=f"Unsupported order type: {order.order_type}",
        )

