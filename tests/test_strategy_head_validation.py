from datetime import UTC, datetime, timedelta

import pytest

from options_lib.strategy_head_validation import (
    DataQuality,
    EvidenceStatus,
    StrategyDecision,
    StrategyHeadOutcome,
    StrategyHeadValidationConfig,
    evaluate_strategy_head_validation,
)


@pytest.fixture
def chronological_outcomes() -> tuple[StrategyHeadOutcome, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def decision(
        *,
        day: int,
        manual: StrategyDecision,
        automatic: StrategyDecision,
    ) -> StrategyHeadOutcome:
        return StrategyHeadOutcome(
            timestamp=start + timedelta(days=day),
            manual=manual,
            automatic=automatic,
        )

    return (
        decision(
            day=3,
            manual=StrategyDecision.signal(
                strategy="bull_call_spread",
                gross_pnl=12.0,
                costs=2.0,
                max_loss=100.0,
            ),
            automatic=StrategyDecision.signal(
                strategy="bull_call_spread",
                gross_pnl=10.0,
                costs=1.0,
                max_loss=100.0,
                model_estimate=0.42,
            ),
        ),
        decision(
            day=1,
            manual=StrategyDecision.signal(
                strategy="bear_put_spread",
                gross_pnl=-2.0,
                costs=1.0,
                max_loss=80.0,
            ),
            automatic=StrategyDecision.no_trade(model_estimate=-0.04),
        ),
        decision(
            day=4,
            manual=StrategyDecision.signal(
                strategy="bull_call_spread",
                gross_pnl=8.0,
                costs=1.0,
                max_loss=100.0,
            ),
            automatic=StrategyDecision.signal(
                strategy="bull_call_spread",
                gross_pnl=5.0,
                costs=1.0,
                max_loss=110.0,
                model_estimate=0.31,
            ),
        ),
        decision(
            day=0,
            manual=StrategyDecision.skipped(),
            automatic=StrategyDecision.skipped(),
        ),
        decision(
            day=2,
            manual=StrategyDecision.signal(
                strategy="bear_put_spread",
                gross_pnl=6.0,
                costs=1.0,
                max_loss=80.0,
            ),
            automatic=StrategyDecision.signal(
                strategy="bear_put_spread",
                gross_pnl=3.0,
                costs=1.0,
                max_loss=90.0,
                model_estimate=0.18,
            ),
        ),
        decision(
            day=5,
            manual=StrategyDecision.signal(
                strategy="bull_call_spread",
                gross_pnl=-4.0,
                costs=2.0,
                max_loss=120.0,
            ),
            automatic=StrategyDecision.signal(
                strategy="bear_put_spread",
                gross_pnl=-3.0,
                costs=1.0,
                max_loss=90.0,
                model_estimate=-0.07,
            ),
        ),
    )


@pytest.fixture
def validated_data_quality() -> DataQuality:
    return DataQuality(
        quality_score=0.95,
        lookahead_verified=True,
        used_proxy_data=True,
        warnings=("one archived interval was reconstructed",),
    )


def test_evaluator_sorts_outcomes_and_compares_after_cost_metrics(
    chronological_outcomes: tuple[StrategyHeadOutcome, ...],
    validated_data_quality: DataQuality,
) -> None:
    report = evaluate_strategy_head_validation(
        chronological_outcomes,
        data_quality=validated_data_quality,
        config=StrategyHeadValidationConfig(
            holdout_start=datetime(2026, 1, 5, tzinfo=UTC),
            minimum_train_samples=3,
            minimum_holdout_samples=2,
        ),
    )

    assert report.rollout_gate.passed is True
    assert report.rollout_gate.failures == ()
    assert report.split_timestamp == datetime(2026, 1, 5, tzinfo=UTC)

    assert report.manual.train.signal_count == 3
    assert report.manual.train.skipped_count == 1
    assert report.manual.train.net_pnl == pytest.approx(12.0)
    assert report.manual.train.total_cost == pytest.approx(4.0)
    assert report.manual.train.expected_value == pytest.approx(4.0)
    assert report.manual.train.maximum_loss == pytest.approx(100.0)
    assert report.manual.train.evidence_status is EvidenceStatus.HISTORICAL_OBSERVATION

    assert report.manual.holdout.signal_count == 2
    assert report.manual.holdout.net_pnl == pytest.approx(1.0)
    assert report.manual.holdout.max_drawdown == pytest.approx(6.0)
    assert report.manual.holdout.evidence_status is EvidenceStatus.HISTORICALLY_VALIDATED

    assert report.automatic.train.signal_count == 2
    assert report.automatic.train.no_trade_count == 1
    assert report.automatic.train.skipped_count == 1
    assert report.automatic.train.net_pnl == pytest.approx(11.0)
    assert report.automatic.holdout.net_pnl == pytest.approx(0.0)
    assert report.automatic.model_estimates is not None
    assert report.automatic.model_estimates.count == 5
    assert report.automatic.model_estimates.average == pytest.approx(0.16)
    assert report.automatic.model_estimates.evidence_status is EvidenceStatus.MODEL_ESTIMATE

    assert report.no_trade.train.signal_count == 0
    assert report.no_trade.holdout.signal_count == 0
    assert report.no_trade.train.no_trade_count + report.no_trade.holdout.no_trade_count == 6
    assert report.no_trade.holdout.net_pnl == 0.0
    assert report.no_trade.holdout.evidence_status is EvidenceStatus.NOT_APPLICABLE

    assert "proxy_data_used" in report.data_quality.warnings
    assert "one archived interval was reconstructed" in report.data_quality.warnings


def test_rollout_gate_reports_each_required_failure(
    chronological_outcomes: tuple[StrategyHeadOutcome, ...],
) -> None:
    report = evaluate_strategy_head_validation(
        chronological_outcomes[:2],
        data_quality=DataQuality(
            quality_score=0.2,
            lookahead_verified=False,
        ),
        config=StrategyHeadValidationConfig(
            holdout_start=None,
            minimum_train_samples=3,
            minimum_holdout_samples=2,
        ),
    )

    assert report.rollout_gate.passed is False
    assert {failure.code for failure in report.rollout_gate.failures} == {
        "missing_holdout",
        "lookahead_not_verified",
        "too_few_samples",
        "insufficient_data_quality",
    }
    assert report.automatic.holdout.evidence_status is EvidenceStatus.UNAVAILABLE


def test_model_estimates_are_not_historical_evidence(
    chronological_outcomes: tuple[StrategyHeadOutcome, ...],
    validated_data_quality: DataQuality,
) -> None:
    report = evaluate_strategy_head_validation(
        chronological_outcomes,
        data_quality=validated_data_quality,
        config=StrategyHeadValidationConfig(
            holdout_start=datetime(2026, 1, 4, tzinfo=UTC),
            minimum_train_samples=3,
            minimum_holdout_samples=2,
        ),
    )

    assert report.automatic.model_estimates is not None
    assert report.automatic.model_estimates.evidence_status is EvidenceStatus.MODEL_ESTIMATE
    assert report.automatic.holdout.evidence_status is EvidenceStatus.HISTORICALLY_VALIDATED
    assert report.automatic.model_estimates.evidence_status is not report.automatic.holdout.evidence_status


def test_proxy_warning_and_missing_max_loss_are_explicit() -> None:
    outcomes = (
        StrategyHeadOutcome(
            timestamp=datetime(2026, 2, 1, tzinfo=UTC),
            manual=StrategyDecision.signal(
                strategy="long_call",
                gross_pnl=5.0,
                costs=1.0,
            ),
            automatic=StrategyDecision.signal(
                strategy="long_call",
                gross_pnl=4.0,
                costs=1.0,
                max_loss=100.0,
                model_estimate=0.2,
            ),
        ),
        StrategyHeadOutcome(
            timestamp=datetime(2026, 2, 2, tzinfo=UTC),
            manual=StrategyDecision.no_trade(),
            automatic=StrategyDecision.no_trade(model_estimate=-0.1),
        ),
    )
    report = evaluate_strategy_head_validation(
        outcomes,
        data_quality=DataQuality(
            quality_score=0.9,
            lookahead_verified=True,
            used_proxy_data=True,
        ),
        config=StrategyHeadValidationConfig(
            holdout_start=datetime(2026, 2, 2, tzinfo=UTC),
            minimum_train_samples=1,
            minimum_holdout_samples=1,
        ),
    )

    assert report.manual.train.maximum_loss is None
    assert "max_loss_unavailable" in report.manual.warnings
    assert "max_loss_unavailable" not in report.automatic.warnings
    assert "proxy_data_used" in report.data_quality.warnings


def test_invalid_decision_cannot_hide_an_unrealized_signal() -> None:
    with pytest.raises(ValueError, match="gross_pnl is required for a signal"):
        StrategyDecision.signal(strategy="long_call", gross_pnl=None, costs=1.0)


def test_report_can_be_serialized_without_changing_evidence_labels(
    chronological_outcomes: tuple[StrategyHeadOutcome, ...],
    validated_data_quality: DataQuality,
) -> None:
    report = evaluate_strategy_head_validation(
        chronological_outcomes,
        data_quality=validated_data_quality,
        config=StrategyHeadValidationConfig(
            holdout_start=datetime(2026, 1, 4, tzinfo=UTC),
            minimum_train_samples=3,
            minimum_holdout_samples=2,
        ),
    )

    serialized = report.to_dict()

    assert serialized["automatic"]["holdout"]["evidence_status"] == "historically_validated"
    assert serialized["automatic"]["model_estimates"]["evidence_status"] == "model_estimate"
    assert serialized["rollout_gate"]["passed"] is True
