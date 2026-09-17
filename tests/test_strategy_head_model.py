from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import pytest

from options_lib.strategy_head_model import (
    InvalidModelArtifactError,
    LightGBMStrategyHead,
    LightGBMUnavailableError,
    SelectionPolicy,
    StrategyHeadDataset,
    StrategyOutcomeRecord,
    TrainingConfig,
)

START = datetime(2026, 1, 1, 12, tzinfo=UTC)
FEATURE_NAMES = ("trend", "volatility")


def _lightgbm_or_skip():
    try:
        import lightgbm
    except (ImportError, OSError) as exc:
        pytest.skip(f"LightGBM is unavailable in this environment: {exc}")
    return lightgbm


def _dataset(*, data_version: str = "fixture-v1") -> StrategyHeadDataset:
    records: list[StrategyOutcomeRecord] = []
    for day in range(12):
        timestamp = START + timedelta(days=day)
        trend = float((day % 5) - 2)
        volatility = float((day % 4) + 1)
        records.extend(
            (
                StrategyOutcomeRecord(
                    timestamp=timestamp,
                    strategy="long_call",
                    features={"trend": trend, "volatility": volatility},
                    outcome=trend * 0.4 + volatility * 0.1,
                ),
                StrategyOutcomeRecord(
                    timestamp=timestamp,
                    strategy="long_put",
                    features={"trend": trend, "volatility": volatility},
                    outcome=-trend * 0.4 + volatility * 0.1,
                ),
            )
        )
    return StrategyHeadDataset(
        records=tuple(records),
        feature_names=FEATURE_NAMES,
        data_version=data_version,
    )


def test_dataset_rejects_missing_or_extra_features() -> None:
    with pytest.raises(ValueError, match="exactly the dataset feature names"):
        StrategyHeadDataset(
            records=(
                StrategyOutcomeRecord(
                    timestamp=START,
                    strategy="long_call",
                    features={"trend": 1.0},
                    outcome=1.0,
                ),
            ),
            feature_names=FEATURE_NAMES,
            data_version="fixture-v1",
        )

    with pytest.raises(ValueError, match="exactly the dataset feature names"):
        StrategyHeadDataset(
            records=(
                StrategyOutcomeRecord(
                    timestamp=START,
                    strategy="long_call",
                    features={"trend": 1.0, "volatility": 0.5, "extra": 2.0},
                    outcome=1.0,
                ),
            ),
            feature_names=FEATURE_NAMES,
            data_version="fixture-v1",
        )


def test_training_reports_three_chronological_splits() -> None:
    lightgbm = _lightgbm_or_skip()
    assert lightgbm is not None

    result = LightGBMStrategyHead.train(
        _dataset(),
        config=TrainingConfig(
            train_fraction=0.5,
            validation_fraction=0.25,
            holdout_fraction=0.25,
            num_boost_round=8,
        ),
    )

    assert result.split.train
    assert result.split.validation
    assert result.split.holdout
    assert max(item.timestamp for item in result.split.train) < min(
        item.timestamp for item in result.split.validation
    )
    assert max(item.timestamp for item in result.split.validation) < min(
        item.timestamp for item in result.split.holdout
    )
    assert result.validation.sample_count == len(result.split.validation)
    assert result.holdout.sample_count == len(result.split.holdout)


def test_training_reports_clear_error_when_lightgbm_is_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "lightgbm", None)

    with pytest.raises(LightGBMUnavailableError, match="LightGBM is required"):
        LightGBMStrategyHead.train(_dataset())


def test_prediction_rejects_missing_and_extra_features() -> None:
    lightgbm = _lightgbm_or_skip()
    assert lightgbm is not None
    model = LightGBMStrategyHead.train(_dataset()).model

    with pytest.raises(ValueError, match="missing features"):
        model.predict({"trend": 1.0})

    with pytest.raises(ValueError, match="extra features"):
        model.predict({"trend": 1.0, "volatility": 0.5, "unexpected": 3.0})


def test_threshold_policy_returns_no_trade_when_all_scores_are_too_low() -> None:
    lightgbm = _lightgbm_or_skip()
    assert lightgbm is not None
    model = LightGBMStrategyHead.train(
        _dataset(),
        config=TrainingConfig(
            selection_policy=SelectionPolicy(no_trade_threshold=10_000.0),
            num_boost_round=8,
        ),
    ).model

    prediction = model.predict({"trend": 1.0, "volatility": 1.0})

    assert prediction.decision == "NO_TRADE"
    assert prediction.selected_strategies == ()
    assert {score.strategy for score in prediction.scores} == {"long_call", "long_put"}


def test_artifact_round_trip_preserves_metadata_and_prediction(tmp_path) -> None:
    lightgbm = _lightgbm_or_skip()
    assert lightgbm is not None
    result = LightGBMStrategyHead.train(
        _dataset(data_version="options-history-v7"),
        config=TrainingConfig(num_boost_round=8),
    )
    model = result.model
    features = {"trend": 1.0, "volatility": 2.0}
    before = model.predict(features)
    artifact = tmp_path / "strategy-head.json"

    model.save(artifact)
    loaded = LightGBMStrategyHead.load(artifact)
    after = loaded.predict(features)

    assert loaded.feature_names == FEATURE_NAMES
    assert loaded.strategy_names == ("long_call", "long_put")
    assert loaded.data_version == "options-history-v7"
    assert loaded.model_version == model.model_version
    assert loaded.trained_at.tzinfo is not None
    assert after.decision == before.decision
    assert [item.strategy for item in after.scores] == [item.strategy for item in before.scores]
    assert [item.score for item in after.scores] == pytest.approx(
        [item.score for item in before.scores]
    )


def test_load_rejects_invalid_artifact_before_loading_lightgbm(tmp_path) -> None:
    artifact = tmp_path / "invalid.json"
    artifact.write_text(
        json.dumps(
            {
                "artifact_type": "strategy_head_lightgbm",
                "artifact_version": 1,
                "model_version": "lightgbm-strategy-head-v1",
                "trained_at": START.isoformat(),
                "data_version": "fixture-v1",
                "strategy_names": ["long_call"],
                "models": {"long_call": "not-a-lightgbm-model"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(InvalidModelArtifactError, match="feature_names"):
        LightGBMStrategyHead.load(artifact)


def test_load_rejects_feature_metadata_mismatch(tmp_path) -> None:
    lightgbm = _lightgbm_or_skip()
    assert lightgbm is not None
    model = LightGBMStrategyHead.train(_dataset(), config=TrainingConfig(num_boost_round=8)).model
    artifact = tmp_path / "mismatched.json"
    model.save(artifact)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["feature_names"] = ["different_feature", "volatility"]
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidModelArtifactError, match="feature_names"):
        LightGBMStrategyHead.load(artifact)
