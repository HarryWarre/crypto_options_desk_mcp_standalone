"""Typed provenance metadata for strategy-head decisions.

This module is deliberately independent from the current signal, scanner, and
strategy-head contract modules.  A later integration can attach
:class:`SignalProvenance` to any signal-shaped mapping without changing those
existing contracts.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Final

PROVENANCE_KEY: Final = "head_provenance"
SIGNAL_PROVENANCE_KEY: Final = PROVENANCE_KEY
SIGNAL_DISCLAIMER: Final = (
    "This is a research signal for manual review; it is not an executed order "
    "and does not guarantee profit."
)


class DecisionSource(str, Enum):
    """The source that selected the strategy families."""

    MANUAL = "manual"
    LIGHTGBM = "lightgbm"
    FALLBACK = "fallback"


class DecisionAction(str, Enum):
    """Whether the head selected strategies or declined to produce a signal."""

    SELECT_STRATEGIES = "select_strategies"
    NO_TRADE = "no_trade"


# Kept as a readable compatibility alias for callers that call the field a
# decision type rather than an action.  The values intentionally match the
# strategy-head contract.
DecisionType = DecisionAction


def _finite(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _positive_rank(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("as_of must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


def _normalize_strategy(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("strategy family names must be strings")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("strategy family names cannot be empty")
    return normalized


def _normalize_strategies(values: Sequence[str] | str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    normalized: list[str] = []
    for value in values:
        strategy = _normalize_strategy(value)
        if strategy not in normalized:
            normalized.append(strategy)
    return tuple(normalized)


def _normalize_reasons(values: Sequence[str] | str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("reason codes must be strings")
        reason = value.strip()
        if not reason:
            raise ValueError("reason codes cannot be empty")
        if reason not in normalized:
            normalized.append(reason)
    if not normalized:
        raise ValueError("at least one reason code is required")
    return tuple(normalized)


def _enum_value(value: Enum | str, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


@dataclass(frozen=True, slots=True)
class StrategyRanking:
    """One strategy family's position in a head ranking.

    ``ranking_score`` is only a relative model score used to order strategy
    families.  It is intentionally not a probability of profit, win rate,
    expected return, or fair-value edge.  Manual and fallback rankings use
    ``None`` because they have no model score.
    """

    strategy_family: str
    rank: int
    ranking_score: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_family", _normalize_strategy(self.strategy_family))
        rank = _positive_rank(self.rank, "rank")
        if rank is None:
            raise ValueError("rank is required")
        object.__setattr__(self, "rank", rank)
        object.__setattr__(self, "ranking_score", _finite(self.ranking_score, "ranking_score"))

    @property
    def strategy(self) -> str:
        """Compatibility alias for callers using the shorter field name."""

        return self.strategy_family

    @property
    def score(self) -> float | None:
        """Compatibility alias for callers using the shorter field name."""

        return self.ranking_score

    def to_dict(self) -> dict[str, object]:
        """Return only JSON-native values."""

        return {
            "strategy_family": self.strategy_family,
            "rank": self.rank,
            "ranking_score": self.ranking_score,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StrategyRanking:
        if not isinstance(value, Mapping):
            raise TypeError("strategy ranking must be an object")
        return cls(
            strategy_family=value.get("strategy_family", value.get("strategy", "")),
            rank=value.get("rank"),
            ranking_score=value.get("ranking_score", value.get("score")),
        )


@dataclass(frozen=True, slots=True)
class SignalProvenance:
    """Auditable origin metadata for one research signal.

    ``selected_strategy_families`` contains strategy families for the
    deterministic scanner to search.  It does not identify an executed order.
    ``ranked_strategies`` is optional because manual and fallback decisions may
    have no model score.  A ``NO_TRADE`` action must have no selected families,
    but it may retain the model ranking that led to that decision.
    """

    source: DecisionSource | str
    action: DecisionAction | str
    selected_strategy_families: tuple[str, ...]
    as_of: datetime
    reason_codes: tuple[str, ...]
    ranked_strategies: tuple[StrategyRanking, ...] = ()
    model_version: str | None = None

    def __post_init__(self) -> None:
        source = _enum_value(self.source, DecisionSource, "source")
        action = _enum_value(self.action, DecisionAction, "action")
        strategies = _normalize_strategies(self.selected_strategy_families)
        reasons = _normalize_reasons(self.reason_codes)
        as_of = _as_utc(self.as_of)

        model_version = self.model_version
        if model_version is not None:
            if not isinstance(model_version, str):
                raise TypeError("model_version must be a string")
            model_version = model_version.strip()
            if not model_version:
                raise ValueError("model_version cannot be empty")

        rankings: list[StrategyRanking] = []
        for ranking in self.ranked_strategies:
            if not isinstance(ranking, StrategyRanking):
                raise TypeError("ranked_strategies must contain StrategyRanking values")
            rankings.append(ranking)

        if action is DecisionAction.SELECT_STRATEGIES and not strategies:
            raise ValueError("selected_strategy_families is required for a strategy decision")
        if action is DecisionAction.NO_TRADE and strategies:
            raise ValueError("NO_TRADE cannot contain selected strategy families")
        if source is DecisionSource.LIGHTGBM and model_version is None:
            raise ValueError("lightgbm decisions require model_version")

        object.__setattr__(self, "source", source)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "selected_strategy_families", strategies)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "ranked_strategies", tuple(rankings))
        object.__setattr__(self, "model_version", model_version)

    @property
    def decision(self) -> DecisionAction:
        """Compatibility alias for callers that call the action a decision."""

        return self.action

    @property
    def selected_strategies(self) -> tuple[str, ...]:
        """Compatibility alias for the strategy-head contract's family field."""

        return self.selected_strategy_families

    @property
    def is_no_trade(self) -> bool:
        return self.action is DecisionAction.NO_TRADE

    @classmethod
    def manual(
        cls,
        *,
        selected_strategies: Sequence[str] | str = (),
        selected_strategy_families: Sequence[str] | str | None = None,
        as_of: datetime,
        reason_codes: Sequence[str] | str | None = None,
    ) -> SignalProvenance:
        selected = (
            selected_strategies
            if selected_strategy_families is None
            else selected_strategy_families
        )
        normalized = _normalize_strategies(selected)
        reasons = reason_codes or ("manual_selection" if normalized else "manual_no_trade",)
        return cls(
            source=DecisionSource.MANUAL,
            action=(
                DecisionAction.SELECT_STRATEGIES
                if normalized
                else DecisionAction.NO_TRADE
            ),
            selected_strategy_families=normalized,
            as_of=as_of,
            reason_codes=_normalize_reasons(reasons),
        )

    @classmethod
    def lightgbm(
        cls,
        *,
        selected_strategies: Sequence[str] | str = (),
        selected_strategy_families: Sequence[str] | str | None = None,
        as_of: datetime,
        model_version: str,
        ranked_strategies: Sequence[StrategyRanking] = (),
        reason_codes: Sequence[str] | str | None = None,
    ) -> SignalProvenance:
        selected = (
            selected_strategies
            if selected_strategy_families is None
            else selected_strategy_families
        )
        normalized = _normalize_strategies(selected)
        reasons = reason_codes or (
            "lightgbm_selection" if normalized else "lightgbm_no_trade",
        )
        return cls(
            source=DecisionSource.LIGHTGBM,
            action=(
                DecisionAction.SELECT_STRATEGIES
                if normalized
                else DecisionAction.NO_TRADE
            ),
            selected_strategy_families=normalized,
            as_of=as_of,
            reason_codes=_normalize_reasons(reasons),
            ranked_strategies=tuple(ranked_strategies),
            model_version=model_version,
        )

    @classmethod
    def fallback(
        cls,
        *,
        selected_strategies: Sequence[str] | str = (),
        selected_strategy_families: Sequence[str] | str | None = None,
        as_of: datetime,
        reason_codes: Sequence[str] | str | None = None,
    ) -> SignalProvenance:
        selected = (
            selected_strategies
            if selected_strategy_families is None
            else selected_strategy_families
        )
        normalized = _normalize_strategies(selected)
        reasons = reason_codes or (
            "fallback_selection" if normalized else "no_fallback_strategies",
        )
        return cls(
            source=DecisionSource.FALLBACK,
            action=(
                DecisionAction.SELECT_STRATEGIES
                if normalized
                else DecisionAction.NO_TRADE
            ),
            selected_strategy_families=normalized,
            as_of=as_of,
            reason_codes=_normalize_reasons(reasons),
        )

    @classmethod
    def no_trade(
        cls,
        *,
        as_of: datetime,
        reason_codes: Sequence[str] | str = ("no_trade",),
        source: DecisionSource | str = DecisionSource.FALLBACK,
        model_version: str | None = None,
        ranked_strategies: Sequence[StrategyRanking] = (),
    ) -> SignalProvenance:
        return cls(
            source=source,
            action=DecisionAction.NO_TRADE,
            selected_strategy_families=(),
            as_of=as_of,
            reason_codes=_normalize_reasons(reason_codes),
            ranked_strategies=tuple(ranked_strategies),
            model_version=model_version,
        )

    @classmethod
    def from_head_decision(cls, decision: Any) -> SignalProvenance:
        """Create provenance from a strategy-head decision without importing it.

        The adapter uses the decision contract's attribute names at runtime,
        while keeping this package importable on its own.  It is intentionally
        duck-typed so the integration branch can choose the dependency seam.
        """

        model_metadata = decision.model_metadata
        model_version = getattr(model_metadata, "model_version", None)
        ranked = tuple(
            ranking
            if isinstance(ranking, StrategyRanking)
            else StrategyRanking(
                strategy_family=ranking.strategy_family,
                rank=ranking.rank,
                ranking_score=ranking.ranking_score,
            )
            for ranking in getattr(decision, "ranked_strategies", ())
        )
        return cls(
            source=decision.source,
            action=decision.action,
            selected_strategy_families=tuple(decision.selected_strategy_families),
            as_of=decision.market_context.observed_at,
            reason_codes=tuple(decision.reason_codes),
            ranked_strategies=ranked,
            model_version=model_version,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe metadata object with explicit signal semantics."""

        return {
            "source": self.source.value,
            "action": self.action.value,
            "selected_strategy_families": list(self.selected_strategy_families),
            "ranked_strategies": [ranking.to_dict() for ranking in self.ranked_strategies],
            "model_version": self.model_version,
            "as_of": self.as_of.isoformat().replace("+00:00", "Z"),
            "reason_codes": list(self.reason_codes),
            "execution_status": "not_executed",
            "profit_guarantee": False,
            "disclaimer": SIGNAL_DISCLAIMER,
        }

    def to_json(self) -> str:
        """Serialize metadata with strict JSON settings."""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SignalProvenance:
        """Rebuild metadata from its JSON-safe representation."""

        if not isinstance(value, Mapping):
            raise TypeError("signal provenance must be an object")

        raw_as_of = value.get("as_of", value.get("as_of_timestamp"))
        if not isinstance(raw_as_of, str):
            raise TypeError("as_of must be an ISO timestamp string")
        try:
            as_of = datetime.fromisoformat(raw_as_of)
        except ValueError as exc:
            raise ValueError("as_of must be a valid ISO timestamp") from exc

        raw_ranked = value.get("ranked_strategies", value.get("strategy_rankings", ()))
        if raw_ranked is None:
            raw_ranked = ()
        if not isinstance(raw_ranked, Sequence) or isinstance(raw_ranked, (str, bytes)):
            raise TypeError("ranked_strategies must be an array")

        raw_selected = value.get(
            "selected_strategy_families",
            value.get("selected_strategies", ()),
        )
        if not isinstance(raw_selected, Sequence) or isinstance(raw_selected, (str, bytes)):
            raise TypeError("selected_strategy_families must be an array")
        raw_reasons = value.get("reason_codes", ())
        if not isinstance(raw_reasons, Sequence) or isinstance(raw_reasons, (str, bytes)):
            raise TypeError("reason_codes must be an array")

        return cls(
            source=value.get("source", value.get("decision_source", "fallback")),
            action=value.get("action", value.get("decision", "no_trade")),
            selected_strategy_families=tuple(raw_selected),
            as_of=as_of,
            reason_codes=tuple(raw_reasons),
            ranked_strategies=tuple(StrategyRanking.from_dict(item) for item in raw_ranked),
            model_version=value.get("model_version"),
        )

    @classmethod
    def from_json(cls, value: str) -> SignalProvenance:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise TypeError("signal provenance JSON must contain an object")
        return cls.from_dict(parsed)


def get_signal_provenance(signal: Mapping[str, object] | None) -> SignalProvenance | None:
    """Read provenance when present, returning ``None`` for legacy signals."""

    if signal is None:
        return None
    raw = signal.get(PROVENANCE_KEY)
    if raw is None:
        return None
    if isinstance(raw, SignalProvenance):
        return raw
    if not isinstance(raw, Mapping):
        raise TypeError(f"{PROVENANCE_KEY} must be an object")
    return SignalProvenance.from_dict(raw)


def attach_provenance(
    signal: Mapping[str, object], provenance: SignalProvenance
) -> dict[str, object]:
    """Return a copied signal mapping with provenance attached.

    The input is never mutated, which lets a future signal integration add
    provenance without changing legacy callers or their original payload.
    """

    if not isinstance(provenance, SignalProvenance):
        raise TypeError("provenance must be SignalProvenance")
    result = dict(signal)
    result[PROVENANCE_KEY] = provenance.to_dict()
    return result
