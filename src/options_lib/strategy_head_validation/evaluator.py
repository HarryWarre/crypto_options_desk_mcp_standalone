"""Deterministic validation for a strategy-selecting head.

The evaluator compares supplied historical decisions only. It does not call a
scanner, train a model, place orders, or turn a model estimate into historical
evidence. A decision's P&L is realized evidence only when it belongs to an
available holdout period that passes the rollout gates.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class DecisionStatus(str, Enum):
    """What happened at one historical decision time."""

    SIGNAL = "signal"
    NO_TRADE = "no_trade"
    SKIPPED = "skipped"


class EvidenceStatus(str, Enum):
    """The status of a reported number, kept separate from model estimates."""

    HISTORICAL_OBSERVATION = "historical_observation"
    HISTORICALLY_VALIDATED = "historically_validated"
    MODEL_ESTIMATE = "model_estimate"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


ProfileName = Literal["manual", "automatic", "NO_TRADE"]


@dataclass(frozen=True)
class StrategyDecision:
    """One manual or automatic decision at a historical timestamp.

    A signal must include a completed gross result. Costs are supplied rather
    than inferred so the evaluator cannot silently use a different fill model.
    ``model_estimate`` is optional metadata and is never used as P&L.
    """

    status: DecisionStatus | str
    strategy: str | None = None
    gross_pnl: float | None = None
    costs: float = 0.0
    max_loss: float | None = None
    model_estimate: float | None = None

    def __post_init__(self) -> None:
        try:
            status = DecisionStatus(self.status)
        except ValueError as exc:
            raise ValueError(f"unsupported decision status: {self.status}") from exc
        object.__setattr__(self, "status", status)

        if status is DecisionStatus.SIGNAL:
            if self.gross_pnl is None:
                raise ValueError("gross_pnl is required for a signal")
            if not self.strategy or not self.strategy.strip():
                raise ValueError("strategy is required for a signal")
        elif self.gross_pnl is not None:
            raise ValueError("gross_pnl is only allowed for a signal")
        if status is not DecisionStatus.SIGNAL and self.costs != 0:
            raise ValueError("costs are only allowed for a signal")

        _finite("costs", self.costs)
        if self.costs < 0:
            raise ValueError("costs cannot be negative")
        if self.gross_pnl is not None:
            _finite("gross_pnl", self.gross_pnl)
        if self.max_loss is not None:
            _finite("max_loss", self.max_loss)
            if self.max_loss < 0:
                raise ValueError("max_loss cannot be negative")
        if self.model_estimate is not None:
            _finite("model_estimate", self.model_estimate)

    @classmethod
    def signal(
        cls,
        *,
        strategy: str,
        gross_pnl: float | None,
        costs: float = 0.0,
        max_loss: float | None = None,
        model_estimate: float | None = None,
    ) -> StrategyDecision:
        return cls(
            status=DecisionStatus.SIGNAL,
            strategy=strategy,
            gross_pnl=gross_pnl,
            costs=costs,
            max_loss=max_loss,
            model_estimate=model_estimate,
        )

    @classmethod
    def no_trade(cls, *, model_estimate: float | None = None) -> StrategyDecision:
        return cls(status=DecisionStatus.NO_TRADE, model_estimate=model_estimate)

    @classmethod
    def skipped(cls) -> StrategyDecision:
        return cls(status=DecisionStatus.SKIPPED)


@dataclass(frozen=True)
class StrategyHeadOutcome:
    """Paired manual and automatic decisions for one historical timestamp."""

    timestamp: datetime
    manual: StrategyDecision
    automatic: StrategyDecision

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")


@dataclass(frozen=True)
class DataQuality:
    """Quality facts supplied by the historical data loader."""

    quality_score: float | None
    lookahead_verified: bool
    used_proxy_data: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.quality_score is not None:
            _finite("quality_score", self.quality_score)
            if not 0 <= self.quality_score <= 1:
                raise ValueError("quality_score must be between 0 and 1")


@dataclass(frozen=True)
class StrategyHeadValidationConfig:
    """Chronological split and minimum quality requirements."""

    holdout_start: datetime | None
    minimum_train_samples: int = 30
    minimum_holdout_samples: int = 30
    minimum_data_quality: float = 0.8

    def __post_init__(self) -> None:
        if self.holdout_start is not None and self.holdout_start.tzinfo is None:
            raise ValueError("holdout_start must be timezone-aware")
        if isinstance(self.minimum_train_samples, bool) or self.minimum_train_samples < 0:
            raise ValueError("minimum_train_samples must be non-negative")
        if isinstance(self.minimum_holdout_samples, bool) or self.minimum_holdout_samples < 1:
            raise ValueError("minimum_holdout_samples must be positive")
        _finite("minimum_data_quality", self.minimum_data_quality)
        if not 0 <= self.minimum_data_quality <= 1:
            raise ValueError("minimum_data_quality must be between 0 and 1")


@dataclass(frozen=True)
class PerformanceMetrics:
    """Cost-adjusted performance for one profile and one time partition."""

    evidence_status: EvidenceStatus
    sample_count: int
    signal_count: int
    no_trade_count: int
    skipped_count: int
    gross_pnl: float
    total_cost: float
    net_pnl: float
    expected_value: float
    wins: int
    losses: int
    win_rate: float | None
    average_win: float
    average_loss: float
    maximum_loss: float | None
    worst_net_pnl: float | None
    max_drawdown: float


@dataclass(frozen=True)
class ModelEstimateSummary:
    """Raw automatic-head estimates, separate from realized metrics."""

    evidence_status: EvidenceStatus
    count: int
    average: float | None
    minimum: float | None
    maximum: float | None
    note: str = "These are model estimates, not historical outcomes."


@dataclass(frozen=True)
class ProfileReport:
    name: ProfileName
    train: PerformanceMetrics
    holdout: PerformanceMetrics
    warnings: tuple[str, ...] = ()
    model_estimates: ModelEstimateSummary | None = None


@dataclass(frozen=True)
class RolloutGateFailure:
    code: str
    message: str


@dataclass(frozen=True)
class RolloutGate:
    passed: bool
    failures: tuple[RolloutGateFailure, ...] = ()


@dataclass(frozen=True)
class DataQualityReport:
    quality_score: float | None
    minimum_quality: float
    lookahead_verified: bool
    used_proxy_data: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class StrategyHeadValidationReport:
    """Comparison report for manual, automatic, and no-trade profiles."""

    manual: ProfileReport
    automatic: ProfileReport
    no_trade: ProfileReport
    split_timestamp: datetime | None
    data_quality: DataQualityReport
    rollout_gate: RolloutGate

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready report without losing evidence labels."""

        return _to_jsonable(self)


def evaluate_strategy_head_validation(
    outcomes: Sequence[StrategyHeadOutcome],
    *,
    data_quality: DataQuality,
    config: StrategyHeadValidationConfig,
) -> StrategyHeadValidationReport:
    """Compare supplied chronological manual and automatic outcomes.

    ``holdout_start`` is an explicit time seam: rows before it are training
    observations and rows at or after it are holdout observations. The
    automatic profile is eligible for rollout only when every required gate
    passes. NO_TRADE is a zero-activity reference profile, not a profitable
    historical strategy.
    """

    ordered = tuple(sorted(outcomes, key=lambda outcome: outcome.timestamp))
    train, holdout = _split(ordered, config.holdout_start)
    gate = _rollout_gate(train, holdout, data_quality, config)
    quality_report = _quality_report(data_quality, config, holdout)

    manual_train = tuple(outcome.manual for outcome in train)
    manual_holdout = tuple(outcome.manual for outcome in holdout)
    automatic_train = tuple(outcome.automatic for outcome in train)
    automatic_holdout = tuple(outcome.automatic for outcome in holdout)
    no_trade_train = tuple(StrategyDecision.no_trade() for _ in train)
    no_trade_holdout = tuple(StrategyDecision.no_trade() for _ in holdout)

    manual = _profile_report(
        "manual",
        manual_train,
        manual_holdout,
        holdout_validated=gate.passed,
    )
    automatic = _profile_report(
        "automatic",
        automatic_train,
        automatic_holdout,
        holdout_validated=gate.passed,
        model_estimates=_model_estimates(tuple(outcome.automatic for outcome in ordered)),
    )
    no_trade = _profile_report(
        "NO_TRADE",
        no_trade_train,
        no_trade_holdout,
        holdout_validated=False,
        not_applicable=True,
    )

    return StrategyHeadValidationReport(
        manual=manual,
        automatic=automatic,
        no_trade=no_trade,
        split_timestamp=(
            config.holdout_start
            if config.holdout_start is not None and holdout
            else None
        ),
        data_quality=quality_report,
        rollout_gate=gate,
    )


def _split(
    outcomes: tuple[StrategyHeadOutcome, ...],
    holdout_start: datetime | None,
) -> tuple[tuple[StrategyHeadOutcome, ...], tuple[StrategyHeadOutcome, ...]]:
    if holdout_start is None:
        return outcomes, ()
    return (
        tuple(outcome for outcome in outcomes if outcome.timestamp < holdout_start),
        tuple(outcome for outcome in outcomes if outcome.timestamp >= holdout_start),
    )


def _rollout_gate(
    train: tuple[StrategyHeadOutcome, ...],
    holdout: tuple[StrategyHeadOutcome, ...],
    data_quality: DataQuality,
    config: StrategyHeadValidationConfig,
) -> RolloutGate:
    failures: list[RolloutGateFailure] = []
    if not holdout:
        failures.append(
            RolloutGateFailure(
                code="missing_holdout",
                message="A non-empty chronological holdout period is required.",
            )
        )
    if not data_quality.lookahead_verified:
        failures.append(
            RolloutGateFailure(
                code="lookahead_not_verified",
                message="The signal-generation process has not been verified as lookahead-free.",
            )
        )
    if len(train) < config.minimum_train_samples or len(holdout) < config.minimum_holdout_samples:
        failures.append(
            RolloutGateFailure(
                code="too_few_samples",
                message=(
                    "The chronological sample is too small: "
                    f"train={len(train)}, holdout={len(holdout)}."
                ),
            )
        )
    if data_quality.quality_score is None or data_quality.quality_score < config.minimum_data_quality:
        score = "missing" if data_quality.quality_score is None else f"{data_quality.quality_score:.3f}"
        failures.append(
            RolloutGateFailure(
                code="insufficient_data_quality",
                message=(
                    f"Data quality score {score} is below the required "
                    f"{config.minimum_data_quality:.3f}."
                ),
            )
        )
    return RolloutGate(passed=not failures, failures=tuple(failures))


def _quality_report(
    data_quality: DataQuality,
    config: StrategyHeadValidationConfig,
    holdout: tuple[StrategyHeadOutcome, ...],
) -> DataQualityReport:
    warnings = list(data_quality.warnings)
    if data_quality.used_proxy_data:
        _append_unique(warnings, "proxy_data_used")
    if not holdout:
        _append_unique(warnings, "holdout_missing")
    if not data_quality.lookahead_verified:
        _append_unique(warnings, "lookahead_not_verified")
    if data_quality.quality_score is None:
        _append_unique(warnings, "quality_score_missing")
    elif data_quality.quality_score < config.minimum_data_quality:
        _append_unique(warnings, "data_quality_below_threshold")
    return DataQualityReport(
        quality_score=data_quality.quality_score,
        minimum_quality=config.minimum_data_quality,
        lookahead_verified=data_quality.lookahead_verified,
        used_proxy_data=data_quality.used_proxy_data,
        warnings=tuple(warnings),
    )


def _profile_report(
    name: ProfileName,
    train: tuple[StrategyDecision, ...],
    holdout: tuple[StrategyDecision, ...],
    *,
    holdout_validated: bool,
    not_applicable: bool = False,
    model_estimates: ModelEstimateSummary | None = None,
) -> ProfileReport:
    warnings: list[str] = []
    signal_decisions = tuple(decision for decision in (*train, *holdout) if _is_signal(decision))
    if signal_decisions and any(decision.max_loss is None for decision in signal_decisions):
        _append_unique(warnings, "max_loss_unavailable")

    if not_applicable:
        train_status = EvidenceStatus.NOT_APPLICABLE
        holdout_status = EvidenceStatus.NOT_APPLICABLE
    else:
        train_status = (
            EvidenceStatus.HISTORICAL_OBSERVATION
            if any(_is_signal(decision) for decision in train)
            else EvidenceStatus.UNAVAILABLE
        )
        holdout_status = (
            EvidenceStatus.HISTORICALLY_VALIDATED
            if holdout_validated and any(_is_signal(decision) for decision in holdout)
            else EvidenceStatus.UNAVAILABLE
        )

    return ProfileReport(
        name=name,
        train=_metrics(train, evidence_status=train_status),
        holdout=_metrics(holdout, evidence_status=holdout_status),
        warnings=tuple(warnings),
        model_estimates=model_estimates,
    )


def _metrics(
    decisions: tuple[StrategyDecision, ...],
    *,
    evidence_status: EvidenceStatus,
) -> PerformanceMetrics:
    signals = tuple(decision for decision in decisions if _is_signal(decision))
    net_values = tuple(float(decision.gross_pnl) - decision.costs for decision in signals)
    wins = tuple(value for value in net_values if value > 0)
    losses = tuple(value for value in net_values if value < 0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    maximum_losses = tuple(
        float(decision.max_loss) for decision in signals if decision.max_loss is not None
    )
    total_cost = sum(decision.costs for decision in signals)
    gross_pnl = sum(float(decision.gross_pnl) for decision in signals)
    net_pnl = sum(net_values)
    return PerformanceMetrics(
        evidence_status=evidence_status,
        sample_count=len(decisions),
        signal_count=len(signals),
        no_trade_count=sum(decision.status is DecisionStatus.NO_TRADE for decision in decisions),
        skipped_count=sum(decision.status is DecisionStatus.SKIPPED for decision in decisions),
        gross_pnl=gross_pnl,
        total_cost=total_cost,
        net_pnl=net_pnl,
        expected_value=net_pnl / len(signals) if signals else 0.0,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / len(signals) if signals else None,
        average_win=sum(wins) / len(wins) if wins else 0.0,
        average_loss=sum(losses) / len(losses) if losses else 0.0,
        maximum_loss=max(maximum_losses) if maximum_losses else None,
        worst_net_pnl=min(net_values) if net_values else None,
        max_drawdown=max_drawdown,
    )


def _model_estimates(decisions: tuple[StrategyDecision, ...]) -> ModelEstimateSummary:
    values = tuple(
        float(decision.model_estimate)
        for decision in decisions
        if decision.model_estimate is not None
    )
    return ModelEstimateSummary(
        evidence_status=EvidenceStatus.MODEL_ESTIMATE,
        count=len(values),
        average=sum(values) / len(values) if values else None,
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
    )


def _is_signal(decision: StrategyDecision) -> bool:
    return decision.status is DecisionStatus.SIGNAL


def _finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value


__all__ = [
    "DataQuality",
    "DataQualityReport",
    "DecisionStatus",
    "EvidenceStatus",
    "ModelEstimateSummary",
    "PerformanceMetrics",
    "ProfileReport",
    "RolloutGate",
    "RolloutGateFailure",
    "StrategyDecision",
    "StrategyHeadOutcome",
    "StrategyHeadValidationConfig",
    "StrategyHeadValidationReport",
    "evaluate_strategy_head_validation",
]
