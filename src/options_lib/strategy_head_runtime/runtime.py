"""Safe runtime adapter between a strategy head and the option scanner.

This package intentionally does not define the strategy-head domain contract.
It accepts that contract structurally so it can be used before or after the
shared contract package is merged. The adapter only selects strategy families;
the caller remains responsible for applying the result to a scan request and
calling the deterministic scanner.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Literal, Protocol, TypeVar, get_args

NO_TRADE = "no_trade"
SELECT_STRATEGIES = "select_strategies"
DecisionAction = Literal["select_strategies", "no_trade"]
Mode = Literal["manual", "automatic"]


class StrategyHeadModel(Protocol):
    """Small injected model seam used by the runtime.

    A LightGBM adapter can expose ``predict`` and return the shared
    ``StrategyHeadPrediction`` or an equivalent mapping/object. The runtime
    does not import LightGBM and does not prescribe the training artifact.
    """

    def predict(self, features: Mapping[str, object]) -> object:
        """Return one model prediction for the current feature mapping."""


class MarketContextLike(Protocol):
    """Only the fields needed from the shared market-context contract."""

    observed_at: datetime
    features: Mapping[str, object]


@dataclass(frozen=True)
class RuntimeScanDecision:
    """Reduced adapter result for the caller that owns the scan request.

    This is deliberately not the shared strategy-head decision contract. It
    contains only the action needed to decide whether a scan may run, the
    selected strategy families, and auditable runtime reasons.
    """

    action: DecisionAction
    selected_strategy_families: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    ranking_score: float | None = None

    def __post_init__(self) -> None:
        if self.action not in {SELECT_STRATEGIES, NO_TRADE}:
            raise ValueError("action must be select_strategies or no_trade")
        if self.action == NO_TRADE and self.selected_strategy_families:
            raise ValueError("no_trade cannot contain selected strategies")
        if self.action == SELECT_STRATEGIES and not self.selected_strategy_families:
            raise ValueError("select_strategies requires selected strategies")
        if self.ranking_score is not None and not isfinite(float(self.ranking_score)):
            raise ValueError("ranking_score must be finite")
        if any(
            not isinstance(reason, str) or not reason.strip()
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-empty strings")

    @property
    def should_scan(self) -> bool:
        """Whether a caller may pass a prepared request to the scanner."""

        return self.action == SELECT_STRATEGIES


class ScanRequestLike(Protocol):
    """The only request field this adapter is allowed to replace."""

    strategies: tuple[str, ...]


RequestT = TypeVar("RequestT")


def apply_strategy_decision(
    request: RequestT,
    decision: RuntimeScanDecision,
) -> RequestT | None:
    """Return a copy with selected strategies, or ``None`` for ``NO_TRADE``.

    The input request is never mutated. Dataclasses (including the repository
    ``ScanRequest``), named tuples, and request-like objects with a
    ``with_strategies`` method are supported. ``None`` is the explicit guard a
    caller can use to skip the scanner entirely.
    """

    if not decision.should_scan:
        return None

    with_strategies = getattr(request, "with_strategies", None)
    if callable(with_strategies):
        return with_strategies(decision.selected_strategy_families)

    if is_dataclass(request):
        try:
            return replace(request, strategies=decision.selected_strategy_families)
        except (TypeError, ValueError) as exc:
            raise TypeError("scan request dataclass must have a strategies field") from exc

    named_tuple_replace = getattr(request, "_replace", None)
    if callable(named_tuple_replace):
        try:
            return named_tuple_replace(strategies=decision.selected_strategy_families)
        except (TypeError, ValueError) as exc:
            raise TypeError("scan request named tuple must have a strategies field") from exc

    if not hasattr(request, "strategies"):
        raise TypeError("request must be a ScanRequest-like object")
    raise TypeError(
        "request must be a dataclass, named tuple, or expose with_strategies"
    )


class StrategyHeadRuntime:
    """Run manual or automatic strategy selection with fail-closed fallback.

    The runtime has one external seam: :meth:`decide`. It validates fresh
    context and usable features before asking the injected head for a
    selection. Missing or invalid model output, stale context, unavailable
    features, and a score below the configured threshold use the configured
    fallback strategies. With no fallback configured, they become
    ``NO_TRADE`` and the caller must not scan.
    """

    def __init__(
        self,
        head: StrategyHeadModel | Any | None = None,
        *,
        min_ranking_score: float | None = None,
        max_context_age: timedelta = timedelta(minutes=15),
        required_features: Iterable[str] = (),
        fallback_strategies: Iterable[str] = (),
        allowed_strategy_families: Iterable[str] | None = None,
    ) -> None:
        if min_ranking_score is not None and not isfinite(float(min_ranking_score)):
            raise ValueError("min_ranking_score must be finite")
        if max_context_age <= timedelta(0):
            raise ValueError("max_context_age must be positive")

        self._head = head
        self._min_ranking_score = (
            None if min_ranking_score is None else float(min_ranking_score)
        )
        self._max_context_age = max_context_age
        self._required_features = _normalise_feature_names(required_features)
        self._allowed_strategy_families = (
            _default_allowed_strategy_families()
            if allowed_strategy_families is None
            else _normalise_allowed_strategies(allowed_strategy_families)
        )
        self._fallback_strategies = self._normalise_strategies(fallback_strategies) or ()

    def decide(
        self,
        *,
        mode: Mode,
        market_context: MarketContextLike | object | None = None,
        manual_strategies: Iterable[str] = (),
        fallback_strategies: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> RuntimeScanDecision:
        """Return a decision without calling the scanner.

        Manual mode bypasses the model and uses the explicitly supplied
        families. Automatic mode passes only the context's feature mapping to
        the injected model, which keeps model invocation independent from the
        shared contract's concrete class.
        """

        fallback = self._fallback_strategies
        if fallback_strategies is not None:
            fallback = self._normalise_strategies(fallback_strategies) or ()

        if mode == "manual":
            strategies = self._normalise_strategies(manual_strategies)
            if strategies is None or not strategies:
                return _no_trade("manual_no_trade")
            return RuntimeScanDecision(
                action=SELECT_STRATEGIES,
                selected_strategy_families=strategies,
                reason_codes=("manual_selection",),
            )

        if mode != "automatic":
            return _fallback_or_no_trade("invalid_mode", fallback)

        context_reason = self._context_failure(market_context, now)
        if context_reason is not None:
            return _fallback_or_no_trade(context_reason, fallback)

        features = getattr(market_context, "features", None)
        feature_reason = self._feature_failure(features)
        if feature_reason is not None:
            return _fallback_or_no_trade(feature_reason, fallback)

        prediction = self._call_head(features)
        if prediction is _MISSING_MODEL:
            return _fallback_or_no_trade("head_unavailable", fallback)
        if prediction is _INVALID_MODEL:
            return _fallback_or_no_trade("invalid_model", fallback)

        parsed = _parse_prediction(prediction, self._allowed_strategy_families)
        if parsed is None:
            return _fallback_or_no_trade("invalid_prediction", fallback)
        if parsed.action == NO_TRADE:
            return RuntimeScanDecision(
                action=NO_TRADE,
                reason_codes=(*parsed.reason_codes, "lightgbm_no_trade"),
                ranking_score=parsed.ranking_score,
            )
        if parsed.ranking_score is None:
            return _fallback_or_no_trade("invalid_prediction", fallback)
        if (
            self._min_ranking_score is not None
            and parsed.ranking_score < self._min_ranking_score
        ):
            return _fallback_or_no_trade("below_threshold", fallback)
        if not parsed.selected_strategy_families:
            return _fallback_or_no_trade("invalid_prediction", fallback)

        return RuntimeScanDecision(
            action=SELECT_STRATEGIES,
            selected_strategy_families=parsed.selected_strategy_families,
            reason_codes=(*parsed.reason_codes, "lightgbm_selection"),
            ranking_score=parsed.ranking_score,
        )

    def _normalise_strategies(self, values: Iterable[str]) -> tuple[str, ...] | None:
        try:
            candidates = tuple(values)
        except TypeError:
            return None
        return _normalise_strategies(candidates, self._allowed_strategy_families)

    def _feature_failure(self, features: object) -> str | None:
        if not isinstance(features, Mapping):
            return "features_unavailable"
        if any(name not in features or features[name] is None for name in self._required_features):
            return "features_unavailable"
        for value in features.values():
            if isinstance(value, bool):
                return "features_invalid"
            try:
                if not isfinite(float(value)):
                    return "features_invalid"
            except (TypeError, ValueError):
                return "features_invalid"
        return None

    def _context_failure(
        self,
        market_context: object | None,
        now: datetime | None,
    ) -> str | None:
        observed_at = getattr(market_context, "observed_at", None)
        if not isinstance(observed_at, datetime):
            return "context_unavailable"
        checked_at = now or datetime.now(UTC)
        if not isinstance(checked_at, datetime):
            return "context_invalid"
        if observed_at.tzinfo is None or checked_at.tzinfo is None:
            return "context_invalid"
        age = checked_at - observed_at
        if age < timedelta(0):
            return "context_invalid"
        if age > self._max_context_age:
            return "stale_context"
        return None

    def _call_head(self, features: Mapping[str, object]) -> object:
        if self._head is None:
            return _MISSING_MODEL
        predictor = getattr(self._head, "predict", None)
        if not callable(predictor):
            if callable(self._head):
                predictor = self._head
            else:
                return _INVALID_MODEL
        try:
            return predictor(features)
        except Exception:  # noqa: BLE001 - model failures must fail closed
            return _INVALID_MODEL


@dataclass(frozen=True)
class _ParsedPrediction:
    action: DecisionAction
    selected_strategy_families: tuple[str, ...]
    ranking_score: float | None
    reason_codes: tuple[str, ...]


_MISSING_MODEL = object()
_INVALID_MODEL = object()


def _normalise_feature_names(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


def _normalise_allowed_strategies(values: Iterable[str]) -> frozenset[str]:
    allowed = frozenset(
        str(value).strip().lower() for value in values if str(value).strip()
    )
    if not allowed:
        raise ValueError("allowed_strategy_families cannot be empty")
    return allowed


def _default_allowed_strategy_families() -> frozenset[str] | None:
    """Read the existing scanner vocabulary instead of copying its registry."""

    try:
        from options_lib.opportunity_scanner import Strategy
    except (ImportError, AttributeError):
        return None
    return frozenset(str(value).lower() for value in get_args(Strategy))


def _normalise_strategies(
    values: Iterable[object],
    allowed: frozenset[str] | None,
) -> tuple[str, ...] | None:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            return None
        strategy = value.strip().lower()
        if not strategy or (allowed is not None and strategy not in allowed):
            return None
        if strategy not in normalized:
            normalized.append(strategy)
    return tuple(normalized)


def _prediction_value(prediction: object, *names: str) -> object | None:
    if isinstance(prediction, Mapping):
        for name in names:
            if name in prediction:
                return prediction[name]
        return None
    for name in names:
        if hasattr(prediction, name):
            return getattr(prediction, name)
    return None


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _parse_action(value: object) -> DecisionAction | None:
    if value is None:
        return SELECT_STRATEGIES
    value = _enum_value(value)
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {NO_TRADE, SELECT_STRATEGIES}:
        return normalized  # type: ignore[return-value]
    if normalized == "scan":
        return SELECT_STRATEGIES
    return None


def _parse_score(value: object) -> float | None | object:
    if value is None:
        return None
    if isinstance(value, bool):
        return _INVALID_SCORE
    try:
        score = float(value)
    except (TypeError, ValueError):
        return _INVALID_SCORE
    return score if isfinite(score) else _INVALID_SCORE


_INVALID_SCORE = object()


def _parse_prediction(
    prediction: object,
    allowed: frozenset[str] | None,
) -> _ParsedPrediction | None:
    if prediction is None or isinstance(prediction, (str, bytes)):
        return None

    action_value = _prediction_value(prediction, "action", "decision")
    no_trade = _prediction_value(prediction, "no_trade")
    if no_trade is True:
        action: DecisionAction = NO_TRADE
    else:
        action = _parse_action(action_value)
        if action is None:
            return None

    selected_value = _prediction_value(
        prediction,
        "selected_strategy_families",
        "strategy_families",
        "strategies",
        "selected_strategies",
    )
    if selected_value is None:
        selected: tuple[str, ...] = ()
    elif isinstance(selected_value, (str, bytes)):
        return None
    else:
        try:
            selected = _normalise_strategies(selected_value, allowed)  # type: ignore[arg-type]
        except TypeError:
            return None
        if selected is None:
            return None

    if action == NO_TRADE and selected:
        return None

    ranked_value = _prediction_value(prediction, "ranked_strategies", "rankings")
    ranking_scores: dict[str, float] = {}
    if ranked_value is not None:
        if isinstance(ranked_value, (str, bytes)):
            return None
        try:
            rankings = tuple(ranked_value)  # type: ignore[arg-type]
        except TypeError:
            return None
        for ranking in rankings:
            name = _prediction_value(ranking, "strategy_family", "strategy", "name")
            score_value = _prediction_value(ranking, "ranking_score", "score")
            if not isinstance(name, str):
                return None
            score = _parse_score(score_value)
            if score is _INVALID_SCORE or score is None:
                return None
            normalized_name = name.strip().lower()
            if not normalized_name or normalized_name in ranking_scores:
                return None
            if allowed is not None and normalized_name not in allowed:
                return None
            ranking_scores[normalized_name] = score
        if selected and not set(selected).issubset(ranking_scores):
            return None

    score_value = _prediction_value(
        prediction,
        "ranking_score",
        "score",
        "confidence",
        "probability",
    )
    score = _parse_score(score_value)
    if score is _INVALID_SCORE:
        return None
    if score is None and selected:
        selected_scores = [ranking_scores[name] for name in selected if name in ranking_scores]
        if len(selected_scores) == len(selected):
            score = min(selected_scores) if selected_scores else None

    metadata = _prediction_value(prediction, "model_metadata")
    if _looks_like_shared_prediction(prediction):
        framework = _prediction_value(metadata, "framework") if metadata is not None else None
        if not isinstance(framework, str) or framework.strip().lower() != "lightgbm":
            return None

    reason_codes = _parse_reason_codes(_prediction_value(prediction, "reason_codes"))
    if reason_codes is None:
        return None
    return _ParsedPrediction(action, selected, score, reason_codes)


def _looks_like_shared_prediction(prediction: object) -> bool:
    return hasattr(prediction, "selected_strategy_families") and hasattr(
        prediction, "ranked_strategies"
    )


def _parse_reason_codes(value: object | None) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return None
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return None
    result: list[str] = []
    for item in values:
        item = _enum_value(item)
        if not isinstance(item, str) or not item.strip():
            return None
        code = item.strip()
        if code not in result:
            result.append(code)
    return tuple(result)


def _no_trade(*reason_codes: str) -> RuntimeScanDecision:
    return RuntimeScanDecision(action=NO_TRADE, reason_codes=reason_codes)


def _fallback_or_no_trade(
    reason: str,
    fallback_strategies: tuple[str, ...],
) -> RuntimeScanDecision:
    if fallback_strategies:
        return RuntimeScanDecision(
            action=SELECT_STRATEGIES,
            selected_strategy_families=fallback_strategies,
            reason_codes=(reason, "fallback_used", "fallback_selection"),
        )
    return _no_trade(reason, "fallback_used", "no_fallback_strategies")


__all__ = [
    "NO_TRADE",
    "SELECT_STRATEGIES",
    "MarketContextLike",
    "RuntimeScanDecision",
    "ScanRequestLike",
    "StrategyHeadModel",
    "StrategyHeadRuntime",
    "apply_strategy_decision",
]
