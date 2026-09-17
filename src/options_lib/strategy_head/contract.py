"""Typed contract for selecting option strategy families.

The strategy head is a decision seam above the deterministic opportunity
scanner.  It selects strategy families, while the scanner still selects the
actual contracts, prices the complete legs, and applies its risk and cost
filters.

This module deliberately has no machine-learning dependency.  A later model
adapter can produce :class:`StrategyHeadPrediction`, and callers can pass it
through :func:`resolve_strategy_head_decision` to get the same safe result
shape in manual and automatic modes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeAlias

StrategyFamily: TypeAlias = str


class SelectionMode(str, Enum):
    """How strategy families are selected for a scan."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"


class DecisionAction(str, Enum):
    """The action the strategy head wants the scanner to take."""

    SELECT_STRATEGIES = "select_strategies"
    NO_TRADE = "no_trade"


class DecisionSource(str, Enum):
    """The origin of a final strategy-head decision."""

    MANUAL = "manual"
    LIGHTGBM = "lightgbm"
    FALLBACK = "fallback"


class ReasonCode(str, Enum):
    """Stable reason codes used by the built-in decision paths."""

    MANUAL_SELECTION = "manual_selection"
    MANUAL_NO_TRADE = "manual_no_trade"
    LIGHTGBM_SELECTION = "lightgbm_selection"
    LIGHTGBM_NO_TRADE = "lightgbm_no_trade"
    FALLBACK_USED = "fallback_used"
    FALLBACK_SELECTION = "fallback_selection"
    HEAD_UNAVAILABLE = "head_unavailable"
    INVALID_MODEL_METADATA = "invalid_model_metadata"
    NO_FALLBACK_STRATEGIES = "no_fallback_strategies"


@dataclass(frozen=True)
class MarketContext:
    """The point-in-time market information given to a strategy head.

    ``features`` contains numeric inputs prepared by the caller.  The
    contract does not prescribe feature names, but it requires finite values
    so a model adapter cannot accidentally consume ``NaN`` or infinity.
    Feature values are inputs, not outcomes or probabilities.
    """

    observed_at: datetime
    assets: tuple[str, ...] = ()
    features: Mapping[str, float] = field(default_factory=dict)
    snapshot_id: str | None = None
    source: str = "unknown"

    def __post_init__(self) -> None:
        _require_timezone_aware("observed_at", self.observed_at)

        assets = _normalise_names(self.assets, field_name="assets", uppercase=True)
        object.__setattr__(self, "assets", assets)

        features: dict[str, float] = {}
        for name, value in self.features.items():
            feature_name = str(name).strip()
            if not feature_name:
                raise ValueError("feature names must not be empty")
            features[feature_name] = _finite_number(f"feature {feature_name!r}", value)
        object.__setattr__(self, "features", MappingProxyType(features))

        _require_text("source", self.source)
        if self.snapshot_id is not None:
            _require_text("snapshot_id", self.snapshot_id)


@dataclass(frozen=True)
class ModelMetadata:
    """Identity and provenance for the model that produced a decision.

    ``evaluation_metrics`` are model-evaluation measurements such as ranking
    metrics.  They are not interpreted as win probabilities by this contract.
    """

    model_name: str
    model_version: str
    feature_set: str
    framework: str = "lightgbm"
    training_data_version: str | None = None
    trained_at: datetime | None = None
    artifact_id: str | None = None
    evaluation_metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("model_name", self.model_name),
            ("model_version", self.model_version),
            ("feature_set", self.feature_set),
            ("framework", self.framework),
        ):
            _require_text(name, value)

        for name, value in (
            ("training_data_version", self.training_data_version),
            ("artifact_id", self.artifact_id),
        ):
            if value is not None:
                _require_text(name, value)

        if self.trained_at is not None:
            _require_timezone_aware("trained_at", self.trained_at)

        metrics: dict[str, float] = {}
        for name, value in self.evaluation_metrics.items():
            metric_name = str(name).strip()
            if not metric_name:
                raise ValueError("evaluation metric names must not be empty")
            metrics[metric_name] = _finite_number(f"evaluation metric {metric_name!r}", value)
        object.__setattr__(self, "evaluation_metrics", MappingProxyType(metrics))


@dataclass(frozen=True)
class StrategyRanking:
    """One strategy's position in the head ranking.

    ``ranking_score`` is only a relative score used to order strategy
    families.  It is intentionally unbounded and must never be described as
    a probability of profit, win rate, expected return, or fair-value edge.
    Manual rankings use ``None`` because they have no model score.
    """

    strategy_family: StrategyFamily
    rank: int
    ranking_score: float | None = None

    def __post_init__(self) -> None:
        strategy_family = _normalise_strategy_name(self.strategy_family)
        object.__setattr__(self, "strategy_family", strategy_family)

        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        if self.ranking_score is not None:
            _finite_number("ranking_score", self.ranking_score)


@dataclass(frozen=True)
class StrategyHeadPrediction:
    """A model adapter's proposed selection before source and fallback rules.

    A prediction may rank strategies while selecting none.  That is the
    explicit ``NO_TRADE`` outcome and is different from a failed model, which
    is handled by :func:`resolve_strategy_head_decision`.
    """

    action: DecisionAction
    ranked_strategies: tuple[StrategyRanking, ...] = ()
    selected_strategy_families: tuple[StrategyFamily, ...] = ()
    reason_codes: tuple[str, ...] = ()
    model_metadata: ModelMetadata | None = None

    def __post_init__(self) -> None:
        action = _coerce_enum(DecisionAction, self.action, "action")
        object.__setattr__(self, "action", action)
        rankings = _validate_rankings(self.ranked_strategies)
        selected = _normalise_names(
            self.selected_strategy_families,
            field_name="selected_strategy_families",
        )
        _validate_selection(action, rankings, selected)
        object.__setattr__(self, "ranked_strategies", rankings)
        object.__setattr__(self, "selected_strategy_families", selected)
        object.__setattr__(
            self,
            "reason_codes",
            _normalise_reason_codes(self.reason_codes),
        )


@dataclass(frozen=True)
class StrategyHeadDecision:
    """Final, auditable selection passed to the deterministic strategy scan."""

    market_context: MarketContext
    mode: SelectionMode
    action: DecisionAction
    source: DecisionSource
    ranked_strategies: tuple[StrategyRanking, ...] = ()
    selected_strategy_families: tuple[StrategyFamily, ...] = ()
    reason_codes: tuple[str, ...] = ()
    model_metadata: ModelMetadata | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.market_context, MarketContext):
            raise TypeError("market_context must be a MarketContext")
        mode = _coerce_enum(SelectionMode, self.mode, "mode")
        action = _coerce_enum(DecisionAction, self.action, "action")
        source = _coerce_enum(DecisionSource, self.source, "source")
        rankings = _validate_rankings(self.ranked_strategies)
        selected = _normalise_names(
            self.selected_strategy_families,
            field_name="selected_strategy_families",
        )

        _validate_selection(action, rankings, selected)
        if mode is SelectionMode.MANUAL and source is not DecisionSource.MANUAL:
            raise ValueError("manual mode can only produce a manual decision")
        if mode is SelectionMode.AUTOMATIC and source is DecisionSource.MANUAL:
            raise ValueError("automatic mode cannot produce a manual decision")
        if source is DecisionSource.LIGHTGBM and self.model_metadata is None:
            raise ValueError("lightgbm decisions require model_metadata")
        if (
            source is DecisionSource.LIGHTGBM
            and self.model_metadata is not None
            and not _is_lightgbm(self.model_metadata)
        ):
            raise ValueError("lightgbm decisions require LightGBM model_metadata")
        if source is not DecisionSource.LIGHTGBM and self.model_metadata is not None:
            raise ValueError("model_metadata is only present for lightgbm decisions")

        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "ranked_strategies", rankings)
        object.__setattr__(self, "selected_strategy_families", selected)
        object.__setattr__(
            self,
            "reason_codes",
            _normalise_reason_codes(self.reason_codes),
        )


def resolve_strategy_head_decision(
    market_context: MarketContext,
    *,
    mode: SelectionMode | str,
    manual_strategies: Iterable[StrategyFamily] = (),
    automatic_prediction: StrategyHeadPrediction | None = None,
    fallback_strategies: Iterable[StrategyFamily] = (),
) -> StrategyHeadDecision:
    """Resolve manual, LightGBM, and fallback paths into one safe decision.

    The rules are deliberately deterministic:

    * ``manual`` mode always uses ``manual_strategies`` and ignores any model
      prediction. An empty list becomes manual ``NO_TRADE``.
    * ``automatic`` mode accepts a prediction only when it has LightGBM model
      metadata. A valid prediction can select strategies or explicitly return
      ``NO_TRADE``.
    * A missing or unusable automatic prediction uses
      ``fallback_strategies``. If that list is empty, the safe result is
      fallback ``NO_TRADE``.

    This function only decides which strategy families the scanner may search.
    It does not choose contracts, place orders, or alter pricing.
    """

    resolved_mode = _coerce_enum(SelectionMode, mode, "mode")
    if not isinstance(market_context, MarketContext):
        raise TypeError("market_context must be a MarketContext")

    manual = _normalise_names(manual_strategies, field_name="manual_strategies")
    fallback = _normalise_names(fallback_strategies, field_name="fallback_strategies")

    if resolved_mode is SelectionMode.MANUAL:
        return _manual_decision(market_context, manual)

    if automatic_prediction is not None:
        if automatic_prediction.model_metadata is not None and _is_lightgbm(
            automatic_prediction.model_metadata
        ):
            return StrategyHeadDecision(
                market_context=market_context,
                mode=resolved_mode,
                action=automatic_prediction.action,
                source=DecisionSource.LIGHTGBM,
                ranked_strategies=automatic_prediction.ranked_strategies,
                selected_strategy_families=automatic_prediction.selected_strategy_families,
                reason_codes=_append_reason(
                    automatic_prediction.reason_codes,
                    (
                        ReasonCode.LIGHTGBM_SELECTION
                        if automatic_prediction.action is DecisionAction.SELECT_STRATEGIES
                        else ReasonCode.LIGHTGBM_NO_TRADE
                    ),
                ),
                model_metadata=automatic_prediction.model_metadata,
            )

        invalid_reason = (
            ReasonCode.HEAD_UNAVAILABLE
            if automatic_prediction.model_metadata is None
            else ReasonCode.INVALID_MODEL_METADATA
        )
    else:
        invalid_reason = ReasonCode.HEAD_UNAVAILABLE

    return _fallback_decision(
        market_context,
        fallback,
        reason=invalid_reason,
    )


def _manual_decision(
    market_context: MarketContext,
    strategies: tuple[StrategyFamily, ...],
) -> StrategyHeadDecision:
    action = DecisionAction.SELECT_STRATEGIES if strategies else DecisionAction.NO_TRADE
    rankings = _manual_rankings(strategies)
    reason = ReasonCode.MANUAL_SELECTION if strategies else ReasonCode.MANUAL_NO_TRADE
    return StrategyHeadDecision(
        market_context=market_context,
        mode=SelectionMode.MANUAL,
        action=action,
        source=DecisionSource.MANUAL,
        ranked_strategies=rankings,
        selected_strategy_families=strategies,
        reason_codes=(reason.value,),
    )


def _fallback_decision(
    market_context: MarketContext,
    strategies: tuple[StrategyFamily, ...],
    *,
    reason: ReasonCode,
) -> StrategyHeadDecision:
    action = DecisionAction.SELECT_STRATEGIES if strategies else DecisionAction.NO_TRADE
    reason_codes = [reason.value, ReasonCode.FALLBACK_USED.value]
    if strategies:
        reason_codes.append(ReasonCode.FALLBACK_SELECTION.value)
    else:
        reason_codes.append(ReasonCode.NO_FALLBACK_STRATEGIES.value)
    return StrategyHeadDecision(
        market_context=market_context,
        mode=SelectionMode.AUTOMATIC,
        action=action,
        source=DecisionSource.FALLBACK,
        ranked_strategies=_manual_rankings(strategies),
        selected_strategy_families=strategies,
        reason_codes=tuple(reason_codes),
    )


def _manual_rankings(strategies: tuple[StrategyFamily, ...]) -> tuple[StrategyRanking, ...]:
    return tuple(
        StrategyRanking(strategy_family=strategy, rank=rank)
        for rank, strategy in enumerate(strategies, start=1)
    )


def _validate_rankings(
    rankings: Iterable[StrategyRanking],
) -> tuple[StrategyRanking, ...]:
    result = tuple(rankings)
    seen: set[str] = set()
    expected_rank = 1
    for ranking in result:
        if not isinstance(ranking, StrategyRanking):
            raise TypeError("ranked_strategies must contain StrategyRanking values")
        if ranking.strategy_family in seen:
            raise ValueError("ranked_strategies cannot contain duplicate strategies")
        if ranking.rank != expected_rank:
            raise ValueError("ranked_strategies ranks must start at 1 and be consecutive")
        seen.add(ranking.strategy_family)
        expected_rank += 1
    return result


def _validate_selection(
    action: DecisionAction,
    rankings: tuple[StrategyRanking, ...],
    selected: tuple[StrategyFamily, ...],
) -> None:
    ranking_names = {ranking.strategy_family for ranking in rankings}
    if not set(selected).issubset(ranking_names):
        raise ValueError("selected strategies must be present in ranked_strategies")
    if action is DecisionAction.NO_TRADE and selected:
        raise ValueError("NO_TRADE cannot contain selected strategies")
    if action is DecisionAction.SELECT_STRATEGIES and not selected:
        raise ValueError("SELECT_STRATEGIES requires at least one selected strategy")


def _normalise_strategy_name(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("strategy family names must be strings")
    result = value.strip().lower()
    if not result:
        raise ValueError("strategy family names must not be empty")
    return result


def _normalise_names(
    values: Iterable[Any],
    *,
    field_name: str,
    uppercase: bool = False,
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must contain strings")
        name = value.strip()
        if not name:
            raise ValueError(f"{field_name} must not contain empty names")
        name = name.upper() if uppercase else name.lower()
        if name not in seen:
            result.append(name)
            seen.add(name)
    return tuple(result)


def _normalise_reason_codes(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = value.value if isinstance(value, ReasonCode) else str(value).strip()
        if not code:
            raise ValueError("reason_codes must not contain empty values")
        if code not in seen:
            result.append(code)
            seen.add(code)
    return tuple(result)


def _append_reason(values: Iterable[str], reason: ReasonCode) -> tuple[str, ...]:
    return _normalise_reason_codes((*values, reason.value))


def _coerce_enum(enum_type: type[Enum], value: Any, field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


def _is_lightgbm(metadata: ModelMetadata) -> bool:
    return metadata.framework.strip().lower() == DecisionSource.LIGHTGBM.value


def _require_text(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_timezone_aware(field_name: str, value: Any) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _finite_number(field_name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


__all__ = [
    "DecisionAction",
    "DecisionSource",
    "MarketContext",
    "ModelMetadata",
    "ReasonCode",
    "SelectionMode",
    "StrategyFamily",
    "StrategyHeadDecision",
    "StrategyHeadPrediction",
    "StrategyRanking",
    "resolve_strategy_head_decision",
]
