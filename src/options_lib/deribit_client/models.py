"""Data models for Deribit API v2 interactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class DeribitOrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"
    STOP_LIMIT = "stop_limit"
    STOP_MARKET = "stop_market"


class DeribitOrderState(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNTRIGGERED = "untriggered"


@dataclass
class DeribitInstrument:
    """Represents a tradeable contract on Deribit."""

    instrument_name: str
    kind: str  # "option" or "future"
    base_currency: str  # "BTC", "ETH", "SOL"
    quote_currency: str  # "USD" or "USDC"
    strike: float
    option_type: str  # "call" or "put"
    expiration_timestamp: int
    tick_size: float
    min_trade_amount: float
    contract_size: float = 1.0
    is_active: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeribitInstrument:
        return cls(
            instrument_name=data.get("instrument_name", ""),
            kind=data.get("kind", ""),
            base_currency=data.get("base_currency", ""),
            quote_currency=data.get("quote_currency", ""),
            strike=float(data.get("strike", 0.0)),
            option_type=data.get("option_type", "").lower(),
            expiration_timestamp=int(data.get("expiration_timestamp", 0)),
            tick_size=float(data.get("tick_size", 0.0005)),
            min_trade_amount=float(data.get("min_trade_amount", 0.1)),
            contract_size=float(data.get("contract_size", 1.0)),
            is_active=bool(data.get("is_active", True)),
        )


@dataclass
class DeribitOrder:
    """An order placed on Deribit."""

    order_id: str
    instrument_name: str
    direction: str  # "buy" or "sell"
    order_type: str
    order_state: str
    amount: float
    filled_amount: float
    price: float | None = None
    average_price: float = 0.0
    fee: float = 0.0
    label: str = ""
    creation_timestamp: int = 0
    last_update_timestamp: int = 0

    @property
    def is_filled(self) -> bool:
        return self.order_state == DeribitOrderState.FILLED.value

    @property
    def is_open(self) -> bool:
        return self.order_state == DeribitOrderState.OPEN.value

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeribitOrder:
        return cls(
            order_id=str(data.get("order_id", "")),
            instrument_name=data.get("instrument_name", ""),
            direction=data.get("direction", "").lower(),
            order_type=data.get("order_type", ""),
            order_state=data.get("order_state", ""),
            amount=float(data.get("amount", 0.0)),
            filled_amount=float(data.get("filled_amount", 0.0)),
            price=float(data["price"]) if data.get("price") is not None else None,
            average_price=float(data.get("average_price", 0.0)),
            fee=float(data.get("fee", 0.0)),
            label=str(data.get("label", "")),
            creation_timestamp=int(data.get("creation_timestamp", 0)),
            last_update_timestamp=int(data.get("last_update_timestamp", 0)),
        )


@dataclass
class DeribitPosition:
    """An open options or futures position on Deribit."""

    instrument_name: str
    kind: str
    direction: str  # "buy" or "sell"
    size: float
    average_price: float
    mark_price: float
    floating_profit_loss: float
    realized_profit_loss: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    initial_margin: float = 0.0
    maintenance_margin: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeribitPosition:
        size = float(data.get("size", 0.0))
        direction = "buy" if size >= 0 else "sell"
        return cls(
            instrument_name=data.get("instrument_name", ""),
            kind=data.get("kind", "option"),
            direction=direction,
            size=abs(size),
            average_price=float(data.get("average_price", 0.0)),
            mark_price=float(data.get("mark_price", 0.0)),
            floating_profit_loss=float(data.get("floating_profit_loss", 0.0)),
            realized_profit_loss=float(data.get("realized_profit_loss", 0.0)),
            delta=float(data.get("delta", 0.0)),
            gamma=float(data.get("gamma", 0.0)),
            vega=float(data.get("vega", 0.0)),
            theta=float(data.get("theta", 0.0)),
            initial_margin=float(data.get("initial_margin", 0.0)),
            maintenance_margin=float(data.get("maintenance_margin", 0.0)),
        )


@dataclass
class DeribitAccountSummary:
    """Portfolio equity and margin summary from Deribit."""

    currency: str
    equity: float
    balance: float
    margin_balance: float
    initial_margin: float
    maintenance_margin: float
    portfolio_margining_enabled: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def margin_utilization_pct(self) -> float:
        if self.equity <= 0:
            return 0.0
        return (self.initial_margin / self.equity) * 100.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeribitAccountSummary:
        return cls(
            currency=data.get("currency", "BTC"),
            equity=float(data.get("equity", 0.0)),
            balance=float(data.get("balance", 0.0)),
            margin_balance=float(data.get("margin_balance", 0.0)),
            initial_margin=float(data.get("initial_margin", 0.0)),
            maintenance_margin=float(data.get("maintenance_margin", 0.0)),
            portfolio_margining_enabled=bool(data.get("portfolio_margining_enabled", False)),
        )

