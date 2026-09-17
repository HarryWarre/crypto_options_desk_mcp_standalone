"""Exchange-agnostic contracts for position monitoring.

The module deliberately models observations and decisions, not order placement.
The closing instruction returned by this domain is an auditable suggestion for a
human to review and execute manually.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from math import isfinite
from typing import Any


class PositionSide(str, Enum):
    """Direction of an open position."""

    LONG = "long"
    SHORT = "short"

    @classmethod
    def from_exchange(cls, value: str) -> PositionSide:
        normalized = str(value or "").strip().lower()
        if normalized in {"buy", "long", "1"}:
            return cls.LONG
        if normalized in {"sell", "short", "-1"}:
            return cls.SHORT
        raise ValueError(f"unsupported position side: {value!r}")


class DecisionAction(str, Enum):
    """Action suggested by the exit decision engine."""

    CLOSE = "close"
    HOLD = "hold"
    REVIEW = "review"


class DecisionSeverity(str, Enum):
    """Urgency of a decision that still requires human review."""

    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThesisStatus(str, Enum):
    """Manual assessment of whether the original trade thesis still holds."""

    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


def _finite(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a finite number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _positive(value: float | None, field_name: str) -> float | None:
    result = _finite(value, field_name)
    if result is not None and result <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return result


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ExitPolicy:
    """Pre-declared conditions used to decide whether one position should exit.

    Percentages are decimal fractions (``0.20`` means 20%). ``risk_budget`` is
    the capital amount against which ``max_loss_pct`` is measured; it is not
    inferred from mark price or leverage.
    """

    symbol: str
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    max_loss_amount: float | None = None
    max_loss_pct: float | None = None
    risk_budget: float | None = None
    max_holding_hours: float | None = None
    min_liquidation_distance_pct: float | None = None
    thesis_status: ThesisStatus = ThesisStatus.UNKNOWN
    opened_at: datetime | None = None
    policy_id: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol cannot be empty")
        object.__setattr__(self, "symbol", symbol)

        for name in (
            "stop_loss_price",
            "take_profit_price",
            "max_loss_amount",
            "risk_budget",
        ):
            value = _positive(getattr(self, name), name)
            object.__setattr__(self, name, value)

        for name in ("max_loss_pct", "min_liquidation_distance_pct"):
            value = _positive(getattr(self, name), name)
            if value is not None and value > 1:
                raise ValueError(f"{name} must be a decimal fraction between 0 and 1")
            object.__setattr__(self, name, value)

        holding = _positive(self.max_holding_hours, "max_holding_hours")
        object.__setattr__(self, "max_holding_hours", holding)
        object.__setattr__(self, "opened_at", _utc(self.opened_at))
        if isinstance(self.thesis_status, str):
            object.__setattr__(self, "thesis_status", ThesisStatus(self.thesis_status.lower()))
        if self.max_loss_pct is not None and self.risk_budget is None:
            raise ValueError("risk_budget is required when max_loss_pct is set")


@dataclass(frozen=True)
class TrackedPosition:
    """Normalized position observation fetched after manual execution."""

    symbol: str
    category: str
    side: PositionSide
    quantity: float
    avg_entry_price: float
    mark_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0
    position_value: float | None = None
    liquidation_price: float | None = None
    leverage: float | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    source: str = "unknown"

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        for name in (
            "avg_entry_price",
            "mark_price",
            "unrealized_pnl",
            "realized_pnl",
            "position_value",
            "liquidation_price",
            "leverage",
        ):
            value = _finite(getattr(self, name), name)
            object.__setattr__(self, name, value)
        if self.avg_entry_price < 0 or self.mark_price < 0:
            raise ValueError("prices cannot be negative")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "category", self.category.strip().lower())
        object.__setattr__(self, "observed_at", _utc(self.observed_at) or datetime.now(tz=UTC))
        if isinstance(self.side, str):
            object.__setattr__(self, "side", PositionSide(self.side.lower()))

    @classmethod
    def from_exchange(cls, position: Any, *, observed_at: datetime, source: str) -> TrackedPosition:
        """Convert the existing generic exchange model without coupling callers to it."""

        return cls(
            symbol=position.symbol,
            category=position.category,
            side=PositionSide.from_exchange(position.side),
            quantity=float(position.size),
            avg_entry_price=float(position.avg_price),
            mark_price=float(position.mark_price),
            unrealized_pnl=float(position.unrealised_pnl),
            realized_pnl=float(position.realised_pnl or 0.0),
            position_value=position.position_value,
            liquidation_price=position.liquidation_price,
            leverage=position.leverage,
            observed_at=observed_at,
            source=source,
        )


@dataclass(frozen=True)
class TrackedOrder:
    """Normalized read-only view of an exchange order."""

    order_id: str
    symbol: str
    category: str
    side: str
    status: str
    order_type: str
    quantity: float | None = None
    leaves_quantity: float | None = None
    average_fill_price: float | None = None
    price: float | None = None
    trigger_price: float | None = None
    reduce_only: bool = False
    close_on_trigger: bool = False
    updated_at: datetime | None = None

    @classmethod
    def from_exchange(cls, raw: Mapping[str, Any], *, category: str) -> TrackedOrder:
        def number(*keys: str) -> float | None:
            for key in keys:
                if raw.get(key) not in (None, ""):
                    return _finite(raw.get(key), key)
            return None

        def timestamp(*keys: str) -> datetime | None:
            for key in keys:
                value = raw.get(key)
                if value in (None, ""):
                    continue
                try:
                    numeric = float(value)
                    return datetime.fromtimestamp(numeric / 1000, tz=UTC)
                except (TypeError, ValueError, OverflowError):
                    continue
            return None

        order_id = str(raw.get("orderId") or raw.get("order_id") or "").strip()
        if not order_id:
            raise ValueError("exchange order is missing orderId")
        return cls(
            order_id=order_id,
            symbol=str(raw.get("symbol") or "").strip().upper(),
            category=category.strip().lower(),
            side=str(raw.get("side") or "").strip().lower(),
            status=str(raw.get("orderStatus") or raw.get("status") or "").strip(),
            order_type=str(raw.get("orderType") or raw.get("order_type") or "").strip(),
            quantity=number("qty", "quantity"),
            leaves_quantity=number("leavesQty", "leaves_quantity"),
            average_fill_price=number("avgPrice", "average_fill_price"),
            price=number("price"),
            trigger_price=number("triggerPrice", "trigger_price"),
            reduce_only=bool(raw.get("reduceOnly", raw.get("reduce_only", False))),
            close_on_trigger=bool(raw.get("closeOnTrigger", raw.get("close_on_trigger", False))),
            updated_at=timestamp("updatedTime", "updateTime", "updated_at"),
        )


@dataclass(frozen=True)
class PositionSnapshot:
    """Point-in-time exchange observation used by risk and exit decisions."""

    captured_at: datetime
    source: str
    positions: tuple[TrackedPosition, ...] = ()
    open_orders: tuple[TrackedOrder, ...] = ()
    reconciliation_status: str = "complete"
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_at", _utc(self.captured_at) or datetime.now(tz=UTC))


@dataclass(frozen=True)
class RiskRuleResult:
    """Result of one deterministic risk rule."""

    rule: str
    triggered: bool
    severity: DecisionSeverity
    detail: str
    value: float | None = None
    threshold: float | None = None


@dataclass(frozen=True)
class RiskAssessment:
    """Calculated risk facts and rule outcomes for one position."""

    symbol: str
    unrealized_pnl: float
    loss_pct: float | None
    liquidation_distance_pct: float | None
    holding_hours: float | None
    rules: tuple[RiskRuleResult, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def triggered_rules(self) -> tuple[RiskRuleResult, ...]:
        return tuple(rule for rule in self.rules if rule.triggered)


@dataclass(frozen=True)
class ExitDecision:
    """Human-reviewable exit decision; never an exchange command."""

    symbol: str
    action: DecisionAction
    severity: DecisionSeverity
    reasons: tuple[str, ...]
    assessment: RiskAssessment
    manual_close_instruction: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["severity"] = self.severity.value
        payload["assessment"]["rules"] = [
            {
                **asdict(rule),
                "severity": rule.severity.value,
            }
            for rule in self.assessment.rules
        ]
        return payload
