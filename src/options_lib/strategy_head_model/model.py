"""Small, offline LightGBM adapter for the strategy-selection head.

The first baseline uses one LightGBM regression model per strategy family.
Each model predicts the historical after-cost outcome in the units supplied by
the training rows.  At prediction time the strategy families are ranked and a
threshold policy may return ``NO_TRADE`` when every predicted outcome is too
low.  This keeps the model focused on selecting strategy families; the
deterministic strategy scanner remains responsible for finding contracts and
producing trade signals.

LightGBM is deliberately imported only when training or loading an artifact.
Applications that do not install the optional dependency can still construct
and validate datasets, inspect invalid artifacts, and receive a clear error at
the model seam.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

NO_TRADE = "NO_TRADE"
ARTIFACT_TYPE = "strategy_head_lightgbm"
ARTIFACT_VERSION = 1
MODEL_VERSION = "lightgbm-strategy-head-v1"


class LightGBMUnavailableError(RuntimeError):
    """Raised when a training or loading operation needs missing LightGBM."""


class InvalidModelArtifactError(ValueError):
    """Raised when a saved strategy-head artifact is missing or inconsistent."""


@dataclass(frozen=True)
class StrategyOutcomeRecord:
    """One timestamped after-cost outcome for one strategy family."""

    timestamp: datetime
    strategy: str
    features: Mapping[str, float]
    outcome: float

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise TypeError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        strategy = str(self.strategy).strip()
        if not strategy:
            raise ValueError("strategy is required")
        if strategy == NO_TRADE:
            raise ValueError("NO_TRADE is a prediction, not a training strategy")
        if isinstance(self.outcome, bool) or not math.isfinite(float(self.outcome)):
            raise ValueError("outcome must be finite")
        if not isinstance(self.features, Mapping):
            raise TypeError("features must be a mapping")

        normalized_features: dict[str, float] = {}
        for name, value in self.features.items():
            feature_name = str(name).strip()
            if not feature_name:
                raise ValueError("feature names must not be empty")
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"feature {feature_name!r} must be finite")
            normalized_features[feature_name] = float(value)

        object.__setattr__(self, "timestamp", self.timestamp.astimezone(UTC))
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "features", normalized_features)
        object.__setattr__(self, "outcome", float(self.outcome))


@dataclass(frozen=True)
class StrategyHeadDataset:
    """Typed tabular rows used to train the strategy-selection head."""

    records: tuple[StrategyOutcomeRecord, ...]
    feature_names: tuple[str, ...]
    data_version: str

    def __post_init__(self) -> None:
        records = tuple(self.records)
        feature_names = tuple(str(name).strip() for name in self.feature_names)
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("feature_names must be unique")
        if any(not name for name in feature_names):
            raise ValueError("feature_names must not be empty")
        data_version = str(self.data_version).strip()
        if not data_version:
            raise ValueError("data_version is required")
        if not all(isinstance(record, StrategyOutcomeRecord) for record in records):
            raise TypeError("records must contain StrategyOutcomeRecord values")

        expected = set(feature_names)
        for record in records:
            actual = set(record.features)
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                details = []
                if missing:
                    details.append(f"missing features: {', '.join(missing)}")
                if extra:
                    details.append(f"extra features: {', '.join(extra)}")
                raise ValueError(
                    "each record must contain exactly the dataset feature names "
                    f"({'; '.join(details)})"
                )

        object.__setattr__(self, "records", records)
        object.__setattr__(self, "feature_names", feature_names)
        object.__setattr__(self, "data_version", data_version)

    @classmethod
    def from_records(
        cls,
        records: Sequence[StrategyOutcomeRecord],
        *,
        feature_names: Sequence[str] | None = None,
        data_version: str,
    ) -> StrategyHeadDataset:
        """Build a dataset from simple typed rows, optionally inferring columns."""

        normalized_records = tuple(records)
        if feature_names is None:
            if not normalized_records:
                raise ValueError("feature_names are required for an empty dataset")
            feature_names = tuple(sorted(normalized_records[0].features))
        return cls(
            records=normalized_records,
            feature_names=tuple(feature_names),
            data_version=data_version,
        )

    @property
    def strategy_names(self) -> tuple[str, ...]:
        """Return deterministic strategy order for model training and output."""

        return tuple(sorted({record.strategy for record in self.records}))


@dataclass(frozen=True)
class SelectionPolicy:
    """Policy that converts predicted outcomes into selections or ``NO_TRADE``."""

    no_trade_threshold: float = 0.0
    max_strategies: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.no_trade_threshold, bool) or not math.isfinite(
            float(self.no_trade_threshold)
        ):
            raise ValueError("no_trade_threshold must be finite")
        if isinstance(self.max_strategies, bool) or self.max_strategies < 1:
            raise ValueError("max_strategies must be positive")
        object.__setattr__(self, "no_trade_threshold", float(self.no_trade_threshold))


@dataclass(frozen=True)
class TrainingConfig:
    """Deterministic first-pass training and chronological split settings."""

    train_fraction: float = 0.6
    validation_fraction: float = 0.2
    holdout_fraction: float = 0.2
    num_boost_round: int = 64
    learning_rate: float = 0.05
    num_leaves: int = 7
    min_data_in_leaf: int = 1
    seed: int = 7
    selection_policy: SelectionPolicy = SelectionPolicy()

    def __post_init__(self) -> None:
        fractions = (
            self.train_fraction,
            self.validation_fraction,
            self.holdout_fraction,
        )
        if any(
            isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0
            for value in fractions
        ):
            raise ValueError("split fractions must be finite and positive")
        if not math.isclose(sum(fractions), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("split fractions must sum to 1")
        if isinstance(self.num_boost_round, bool) or self.num_boost_round < 1:
            raise ValueError("num_boost_round must be positive")
        if (
            isinstance(self.learning_rate, bool)
            or not math.isfinite(float(self.learning_rate))
            or self.learning_rate <= 0
        ):
            raise ValueError("learning_rate must be finite and positive")
        if isinstance(self.num_leaves, bool) or self.num_leaves < 2:
            raise ValueError("num_leaves must be at least 2")
        if isinstance(self.min_data_in_leaf, bool) or self.min_data_in_leaf < 1:
            raise ValueError("min_data_in_leaf must be positive")


@dataclass(frozen=True)
class ChronologicalSplit:
    """Three non-overlapping time slices used for model fitting and checking."""

    train: tuple[StrategyOutcomeRecord, ...]
    validation: tuple[StrategyOutcomeRecord, ...]
    holdout: tuple[StrategyOutcomeRecord, ...]


@dataclass(frozen=True)
class EvaluationSummary:
    """Simple outcome errors for one chronological slice."""

    sample_count: int
    mean_absolute_error: float
    root_mean_squared_error: float
    mean_predicted_outcome: float
    mean_realized_outcome: float


@dataclass(frozen=True)
class StrategyHeadScore:
    """One predicted after-cost outcome for a strategy family."""

    strategy: str
    score: float


@dataclass(frozen=True)
class StrategyHeadPrediction:
    """Ranked strategy scores and the resulting human-review decision."""

    decision: Literal["SELECT", "NO_TRADE"]
    selected_strategies: tuple[str, ...]
    scores: tuple[StrategyHeadScore, ...]


@dataclass(frozen=True)
class StrategyHeadTrainingResult:
    """Trained model plus the validation evidence produced during training."""

    model: LightGBMStrategyHead
    split: ChronologicalSplit
    validation: EvaluationSummary
    holdout: EvaluationSummary


class LightGBMStrategyHead:
    """Offline per-strategy LightGBM scoring adapter.

    The model has a deliberately small interface: train from typed rows,
    predict from the exact saved feature set, and save/load a self-describing
    artifact.  It is not a pricing model and has no order or execution methods.
    """

    def __init__(
        self,
        *,
        boosters: Mapping[str, Any],
        feature_names: tuple[str, ...],
        strategy_names: tuple[str, ...],
        data_version: str,
        trained_at: datetime,
        selection_policy: SelectionPolicy,
        model_version: str = MODEL_VERSION,
    ) -> None:
        if not boosters:
            raise ValueError("at least one strategy model is required")
        if tuple(sorted(boosters)) != tuple(strategy_names):
            raise ValueError("strategy models must match strategy_names")
        self._boosters = dict(boosters)
        self._feature_names = tuple(feature_names)
        self._strategy_names = tuple(strategy_names)
        self._data_version = str(data_version)
        self._trained_at = trained_at.astimezone(UTC)
        self._selection_policy = selection_policy
        self._model_version = model_version

    @classmethod
    def train(
        cls,
        dataset: StrategyHeadDataset | Sequence[StrategyOutcomeRecord],
        *,
        config: TrainingConfig | None = None,
        feature_names: Sequence[str] | None = None,
        data_version: str | None = None,
    ) -> StrategyHeadTrainingResult:
        """Fit one outcome model per strategy using a chronological split."""

        training_config = config or TrainingConfig()
        normalized_dataset = _coerce_dataset(
            dataset,
            feature_names=feature_names,
            data_version=data_version,
        )
        split = _chronological_split(normalized_dataset.records, training_config)
        lightgbm = _load_lightgbm()
        boosters: dict[str, Any] = {}

        for strategy in normalized_dataset.strategy_names:
            rows = tuple(record for record in split.train if record.strategy == strategy)
            if not rows:
                raise ValueError(
                    f"strategy {strategy!r} has no training rows in the chronological split"
                )
            train_set = lightgbm.Dataset(
                [
                    [record.features[name] for name in normalized_dataset.feature_names]
                    for record in rows
                ],
                label=[record.outcome for record in rows],
                feature_name=list(normalized_dataset.feature_names),
                free_raw_data=False,
            )
            boosters[strategy] = lightgbm.train(
                _lightgbm_parameters(training_config),
                train_set,
                num_boost_round=training_config.num_boost_round,
            )

        model = cls(
            boosters=boosters,
            feature_names=normalized_dataset.feature_names,
            strategy_names=normalized_dataset.strategy_names,
            data_version=normalized_dataset.data_version,
            trained_at=datetime.now(UTC),
            selection_policy=training_config.selection_policy,
        )
        return StrategyHeadTrainingResult(
            model=model,
            split=split,
            validation=_evaluate(model, split.validation),
            holdout=_evaluate(model, split.holdout),
        )

    @classmethod
    def load(cls, path: str | Path) -> LightGBMStrategyHead:
        """Load and fully validate one self-describing model artifact."""

        artifact_path = Path(path)
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidModelArtifactError(f"could not read model artifact: {exc}") from exc

        metadata = _validate_artifact_payload(payload)
        lightgbm = _load_lightgbm()
        boosters: dict[str, Any] = {}
        for strategy in metadata["strategy_names"]:
            try:
                booster = lightgbm.Booster(model_str=metadata["models"][strategy])
            except Exception as exc:  # LightGBM exposes several backend-specific exceptions.
                raise InvalidModelArtifactError(
                    f"invalid LightGBM model for strategy {strategy!r}"
                ) from exc
            actual_features = tuple(str(name) for name in booster.feature_name())
            if actual_features != tuple(metadata["feature_names"]):
                raise InvalidModelArtifactError(
                    f"model feature_names do not match artifact feature_names for {strategy!r}"
                )
            boosters[strategy] = booster

        return cls(
            boosters=boosters,
            feature_names=tuple(metadata["feature_names"]),
            strategy_names=tuple(metadata["strategy_names"]),
            data_version=metadata["data_version"],
            trained_at=metadata["trained_at"],
            selection_policy=metadata["selection_policy"],
            model_version=metadata["model_version"],
        )

    def predict(self, features: Mapping[str, float]) -> StrategyHeadPrediction:
        """Score all strategies and apply the configured ``NO_TRADE`` policy."""

        row = _validate_feature_mapping(features, self._feature_names)
        scores = tuple(
            sorted(
                (
                    StrategyHeadScore(
                        strategy=strategy,
                        score=self._predict_strategy(strategy, row),
                    )
                    for strategy in self._strategy_names
                ),
                key=lambda item: (-item.score, item.strategy),
            )
        )
        selected = tuple(
            item.strategy
            for item in scores
            if item.score >= self._selection_policy.no_trade_threshold
        )[: self._selection_policy.max_strategies]
        return StrategyHeadPrediction(
            decision="SELECT" if selected else NO_TRADE,
            selected_strategies=selected,
            scores=scores,
        )

    def save(self, path: str | Path) -> None:
        """Save model metadata and LightGBM text models as JSON."""

        artifact_path = Path(path)
        payload = {
            "artifact_type": ARTIFACT_TYPE,
            "artifact_version": ARTIFACT_VERSION,
            "model_version": self._model_version,
            "trained_at": self._trained_at.isoformat(),
            "data_version": self._data_version,
            "feature_names": list(self._feature_names),
            "strategy_names": list(self._strategy_names),
            "selection_policy": {
                "no_trade_threshold": self._selection_policy.no_trade_threshold,
                "max_strategies": self._selection_policy.max_strategies,
            },
            "models": {
                strategy: booster.model_to_string() for strategy, booster in self._boosters.items()
            },
        }
        try:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            raise InvalidModelArtifactError(f"could not write model artifact: {exc}") from exc

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def strategy_names(self) -> tuple[str, ...]:
        return self._strategy_names

    @property
    def data_version(self) -> str:
        return self._data_version

    @property
    def trained_at(self) -> datetime:
        return self._trained_at

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def selection_policy(self) -> SelectionPolicy:
        return self._selection_policy

    def _predict_strategy(self, strategy: str, features: Mapping[str, float]) -> float:
        try:
            raw_prediction = self._boosters[strategy].predict(
                [[features[name] for name in self._feature_names]]
            )
            score = float(raw_prediction[0])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise InvalidModelArtifactError(
                f"could not predict strategy {strategy!r} from model artifact"
            ) from exc
        if not math.isfinite(score):
            raise InvalidModelArtifactError(
                f"model returned a non-finite score for strategy {strategy!r}"
            )
        return score


def train_strategy_head(
    dataset: StrategyHeadDataset | Sequence[StrategyOutcomeRecord],
    *,
    config: TrainingConfig | None = None,
    feature_names: Sequence[str] | None = None,
    data_version: str | None = None,
) -> StrategyHeadTrainingResult:
    """Functional entry point for offline head training."""

    return LightGBMStrategyHead.train(
        dataset,
        config=config,
        feature_names=feature_names,
        data_version=data_version,
    )


def _coerce_dataset(
    dataset: StrategyHeadDataset | Sequence[StrategyOutcomeRecord],
    *,
    feature_names: Sequence[str] | None,
    data_version: str | None,
) -> StrategyHeadDataset:
    if isinstance(dataset, StrategyHeadDataset):
        if feature_names is not None or data_version is not None:
            raise ValueError("feature_names and data_version belong to the dataset")
        return dataset
    if feature_names is None or data_version is None:
        raise ValueError(
            "feature_names and data_version are required when training from simple records"
        )
    return StrategyHeadDataset.from_records(
        dataset,
        feature_names=feature_names,
        data_version=data_version,
    )


def _chronological_split(
    records: Sequence[StrategyOutcomeRecord],
    config: TrainingConfig,
) -> ChronologicalSplit:
    if not records:
        raise ValueError("at least one training record is required")
    ordered = tuple(sorted(records, key=lambda record: (record.timestamp, record.strategy)))
    timestamps = tuple(sorted({record.timestamp for record in ordered}))
    if len(timestamps) < 3:
        raise ValueError("at least three distinct timestamps are required for chronological splits")

    train_end = max(1, min(len(timestamps) - 2, int(len(timestamps) * config.train_fraction)))
    validation_end = max(
        train_end + 1,
        min(
            len(timestamps) - 1,
            int(len(timestamps) * (config.train_fraction + config.validation_fraction)),
        ),
    )
    train_timestamps = set(timestamps[:train_end])
    validation_timestamps = set(timestamps[train_end:validation_end])
    holdout_timestamps = set(timestamps[validation_end:])
    return ChronologicalSplit(
        train=tuple(record for record in ordered if record.timestamp in train_timestamps),
        validation=tuple(record for record in ordered if record.timestamp in validation_timestamps),
        holdout=tuple(record for record in ordered if record.timestamp in holdout_timestamps),
    )


def _lightgbm_parameters(config: TrainingConfig) -> dict[str, Any]:
    return {
        "objective": "regression",
        "metric": "l2",
        "verbosity": -1,
        "seed": config.seed,
        "feature_fraction_seed": config.seed,
        "bagging_seed": config.seed,
        "data_random_seed": config.seed,
        "num_threads": 1,
        "deterministic": True,
        "force_col_wise": True,
        "learning_rate": config.learning_rate,
        "num_leaves": config.num_leaves,
        "min_data_in_leaf": config.min_data_in_leaf,
        "feature_fraction": 1.0,
        "bagging_fraction": 1.0,
        "bagging_freq": 0,
    }


def _evaluate(
    model: LightGBMStrategyHead,
    records: Sequence[StrategyOutcomeRecord],
) -> EvaluationSummary:
    if not records:
        return EvaluationSummary(0, 0.0, 0.0, 0.0, 0.0)
    predictions = [model._predict_strategy(record.strategy, record.features) for record in records]
    actual = [record.outcome for record in records]
    errors = [prediction - outcome for prediction, outcome in zip(predictions, actual)]
    return EvaluationSummary(
        sample_count=len(records),
        mean_absolute_error=sum(abs(error) for error in errors) / len(errors),
        root_mean_squared_error=math.sqrt(sum(error * error for error in errors) / len(errors)),
        mean_predicted_outcome=sum(predictions) / len(predictions),
        mean_realized_outcome=sum(actual) / len(actual),
    )


def _validate_feature_mapping(
    features: Mapping[str, float],
    expected_names: Sequence[str],
) -> dict[str, float]:
    if not isinstance(features, Mapping):
        raise TypeError("features must be a mapping")
    expected = set(expected_names)
    actual = set(features)
    non_string_names = {str(name) for name in actual if not isinstance(name, str)}
    actual_string_names = {name for name in actual if isinstance(name, str)}
    missing = sorted(expected - actual)
    extra = sorted((actual_string_names - expected) | non_string_names)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing features: {', '.join(missing)}")
        if extra:
            details.append(f"extra features: {', '.join(extra)}")
        raise ValueError(
            "feature names must match the trained model exactly (" + "; ".join(details) + ")"
        )
    normalized: dict[str, float] = {}
    for name in expected_names:
        value = features[name]
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(f"feature {name!r} must be finite")
        normalized[name] = float(value)
    return normalized


def _validate_artifact_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidModelArtifactError("model artifact must be a JSON object")
    expected_keys = {
        "artifact_type",
        "artifact_version",
        "model_version",
        "trained_at",
        "data_version",
        "feature_names",
        "strategy_names",
        "selection_policy",
        "models",
    }
    unknown_keys = set(payload) - expected_keys
    if unknown_keys:
        raise InvalidModelArtifactError(
            f"artifact contains unknown fields: {', '.join(sorted(unknown_keys))}"
        )
    if payload.get("artifact_type") != ARTIFACT_TYPE:
        raise InvalidModelArtifactError("invalid artifact_type")
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        raise InvalidModelArtifactError("unsupported artifact_version")
    if payload.get("model_version") != MODEL_VERSION:
        raise InvalidModelArtifactError("unsupported model_version")

    feature_names = payload.get("feature_names")
    if (
        not isinstance(feature_names, list)
        or not feature_names
        or any(
            not isinstance(name, str) or not name.strip() or name != name.strip()
            for name in feature_names
        )
    ):
        raise InvalidModelArtifactError("artifact feature_names are missing or invalid")
    if len(feature_names) != len(set(feature_names)):
        raise InvalidModelArtifactError("artifact feature_names must be unique")

    strategy_names = payload.get("strategy_names")
    if (
        not isinstance(strategy_names, list)
        or not strategy_names
        or any(
            not isinstance(name, str)
            or not name.strip()
            or name != name.strip()
            or name == NO_TRADE
            for name in strategy_names
        )
    ):
        raise InvalidModelArtifactError("artifact strategy_names are missing or invalid")
    if len(strategy_names) != len(set(strategy_names)):
        raise InvalidModelArtifactError("artifact strategy_names must be unique")

    trained_at_raw = payload.get("trained_at")
    if not isinstance(trained_at_raw, str):
        raise InvalidModelArtifactError("artifact trained_at is missing or invalid")
    try:
        trained_at = datetime.fromisoformat(trained_at_raw)
    except ValueError as exc:
        raise InvalidModelArtifactError("artifact trained_at is invalid") from exc
    if trained_at.tzinfo is None or trained_at.utcoffset() is None:
        raise InvalidModelArtifactError("artifact trained_at must be timezone-aware")

    data_version = payload.get("data_version")
    if not isinstance(data_version, str) or not data_version.strip():
        raise InvalidModelArtifactError("artifact data_version is missing or invalid")

    policy_raw = payload.get("selection_policy")
    if not isinstance(policy_raw, dict):
        raise InvalidModelArtifactError("artifact selection_policy is missing or invalid")
    try:
        selection_policy = SelectionPolicy(
            no_trade_threshold=policy_raw["no_trade_threshold"],
            max_strategies=policy_raw["max_strategies"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidModelArtifactError("artifact selection_policy is invalid") from exc

    models = payload.get("models")
    if not isinstance(models, dict):
        raise InvalidModelArtifactError("artifact models are missing or invalid")
    if set(models) != set(strategy_names) or any(
        not isinstance(value, str) or not value.strip() for value in models.values()
    ):
        raise InvalidModelArtifactError("artifact models must match strategy_names exactly")

    return {
        "feature_names": feature_names,
        "strategy_names": strategy_names,
        "trained_at": trained_at.astimezone(UTC),
        "data_version": data_version.strip(),
        "selection_policy": selection_policy,
        "model_version": payload["model_version"],
        "models": models,
    }


def _load_lightgbm() -> Any:
    try:
        import lightgbm  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise LightGBMUnavailableError(
            "LightGBM is required for strategy-head training or artifact loading; "
            "install the optional 'lightgbm' package"
        ) from exc
    return lightgbm


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
