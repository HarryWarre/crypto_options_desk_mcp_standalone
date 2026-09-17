"""Validation and reporting for manual versus automatic strategy selection."""

from .evaluator import (
    DataQuality,
    DataQualityReport,
    DecisionStatus,
    EvidenceStatus,
    ModelEstimateSummary,
    PerformanceMetrics,
    ProfileReport,
    RolloutGate,
    RolloutGateFailure,
    StrategyDecision,
    StrategyHeadOutcome,
    StrategyHeadValidationConfig,
    StrategyHeadValidationReport,
    evaluate_strategy_head_validation,
)

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
