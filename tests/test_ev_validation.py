from datetime import UTC, datetime, timedelta

import pytest

from options_lib.ev_validation import (
    BacktestStatus,
    HistoricalTradeSample,
    ValidationConfig,
    validate_backtest,
)

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _sample(day: int, gross_pnl: float, *, notional: float = 100.0) -> HistoricalTradeSample:
    return HistoricalTradeSample(
        timestamp=START + timedelta(days=day),
        gross_pnl=gross_pnl,
        notional=notional,
    )


def test_backtest_sorts_chronologically_and_reports_net_holdout_metrics() -> None:
    report = validate_backtest(
        (
            _sample(3, 1.0),
            _sample(0, -4.0),
            _sample(2, 20.0),
            _sample(1, 10.0),
        ),
        ValidationConfig(
            holdout_count=2,
            minimum_train_samples=1,
            minimum_holdout_samples=2,
            fee_bps_per_leg=100.0,
            slippage_bps_per_leg=50.0,
            lookahead_verified=True,
        ),
    )

    assert report.status == "validated_positive_ev"
    assert report.split_timestamp == START + timedelta(days=2)
    assert report.train.trade_count == 2
    assert report.holdout.trade_count == 2
    assert report.holdout.wins == 1
    assert report.holdout.losses == 1
    assert report.holdout.average_win == pytest.approx(17.0)
    assert report.holdout.average_loss == pytest.approx(-2.0)
    assert report.holdout.net_pnl == pytest.approx(15.0)
    assert report.holdout.expected_value == pytest.approx(7.5)
    assert report.holdout.max_drawdown == pytest.approx(2.0)
    assert report.holdout.total_cost == pytest.approx(6.0)
    assert report.train.win_rate == pytest.approx(0.5)
    assert report.holdout.win_rate == pytest.approx(0.5)
    assert report.holdout.historical_win_rate == pytest.approx(0.5)
    assert report.evidence_metadata == {
        "evidence_status": "validated_positive_ev",
        "outcome_type": "historical_realized",
        "historical_outcomes_used": True,
        "probability_basis": "historical_net_pnl_after_costs",
        "win_rate_basis": "historical_net_pnl_after_costs",
        "win_rate_definition": "wins / completed trades where net_pnl > 0",
        "costs_included": True,
        "lookahead_free": True,
        "sample_sufficient": True,
        "train_sample_count": 2,
        "holdout_sample_count": 2,
        "minimum_train_samples": 1,
        "minimum_holdout_samples": 2,
    }
    assert report.lookahead_free is True


def test_positive_ev_requires_minimum_held_out_sample_count() -> None:
    report = validate_backtest(
        (_sample(0, 2.0), _sample(1, 3.0), _sample(2, 4.0)),
        ValidationConfig(
            holdout_count=2,
            minimum_train_samples=1,
            minimum_holdout_samples=3,
            fee_bps_per_leg=0.0,
            slippage_bps_per_leg=0.0,
        ),
    )

    assert report.status == "insufficient_evidence"
    assert report.holdout.expected_value == pytest.approx(3.5)
    assert report.evidence_note


def test_positive_ev_remains_blocked_without_lookahead_verification() -> None:
    report = validate_backtest(
        (_sample(0, 2.0), _sample(1, 3.0), _sample(2, 4.0)),
        ValidationConfig(
            holdout_count=2,
            minimum_train_samples=1,
            minimum_holdout_samples=2,
        ),
    )

    assert report.status == BacktestStatus.INSUFFICIENT_EVIDENCE
    assert report.holdout.expected_value == pytest.approx(3.5)
    assert report.lookahead_free is False
    assert report.evidence_metadata["sample_sufficient"] is True
    assert report.evidence_metadata["lookahead_free"] is False


def test_non_positive_ev_is_reported_after_costs() -> None:
    report = validate_backtest(
        (_sample(0, 5.0), _sample(1, 1.0), _sample(2, 1.0)),
        ValidationConfig(
            holdout_count=2,
            minimum_train_samples=1,
            minimum_holdout_samples=2,
            fee_bps_per_leg=300.0,
            slippage_bps_per_leg=300.0,
            lookahead_verified=True,
        ),
    )

    assert report.status == "validated_non_positive_ev"
    assert report.holdout.expected_value < 0
    assert report.holdout.wins == 0
    assert report.holdout.losses == 2


def test_cost_sensitivity_shows_edge_disappearing_when_costs_increase() -> None:
    report = validate_backtest(
        (_sample(0, 1.0), _sample(1, 10.0), _sample(2, 10.0)),
        ValidationConfig(
            holdout_count=2,
            minimum_train_samples=1,
            minimum_holdout_samples=2,
            fee_bps_per_leg=100.0,
            slippage_bps_per_leg=0.0,
            cost_sensitivity_multipliers=(1.0, 5.0),
        ),
    )

    base, stressed = report.cost_sensitivity
    assert base.multiplier == pytest.approx(1.0)
    assert base.expected_value == pytest.approx(8.0)
    assert stressed.multiplier == pytest.approx(5.0)
    assert stressed.expected_value == pytest.approx(0.0)
    assert stressed.net_pnl == pytest.approx(0.0)


def test_invalid_sample_and_config_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        HistoricalTradeSample(
            timestamp=datetime.fromisoformat("2026-01-01"),
            gross_pnl=1.0,
            notional=100.0,
        )

    with pytest.raises(ValueError, match="finite"):
        HistoricalTradeSample(timestamp=START, gross_pnl=float("nan"), notional=100.0)

    with pytest.raises(ValueError, match="holdout_fraction"):
        ValidationConfig(holdout_fraction=1.0)


def test_empty_history_is_insufficient_without_claiming_a_future_return() -> None:
    report = validate_backtest((), ValidationConfig())

    assert report.status == BacktestStatus.INSUFFICIENT_EVIDENCE
    assert report.train.trade_count == 0
    assert report.holdout.trade_count == 0
    assert "not a guarantee" in report.evidence_note.lower()
