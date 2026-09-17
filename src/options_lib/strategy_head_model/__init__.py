"""Offline LightGBM adapter for selecting option strategy families.

The adapter scores strategy outcomes from historical rows.  It does not price
options, search contracts, create signals, or submit orders.
"""

from .model import (
    ARTIFACT_TYPE,
    ARTIFACT_VERSION,
    MODEL_VERSION,
    NO_TRADE,
    ChronologicalSplit,
    EvaluationSummary,
    InvalidModelArtifactError,
    LightGBMStrategyHead,
    LightGBMUnavailableError,
    SelectionPolicy,
    StrategyHeadDataset,
    StrategyHeadPrediction,
    StrategyHeadScore,
    StrategyHeadTrainingResult,
    StrategyOutcomeRecord,
    TrainingConfig,
    train_strategy_head,
)

__all__ = [
    "ARTIFACT_TYPE",
    "ARTIFACT_VERSION",
    "MODEL_VERSION",
    "NO_TRADE",
    "ChronologicalSplit",
    "EvaluationSummary",
    "InvalidModelArtifactError",
    "LightGBMStrategyHead",
    "LightGBMUnavailableError",
    "SelectionPolicy",
    "StrategyHeadDataset",
    "StrategyHeadPrediction",
    "StrategyHeadScore",
    "StrategyHeadTrainingResult",
    "StrategyOutcomeRecord",
    "TrainingConfig",
    "train_strategy_head",
]
