from datetime import UTC, datetime, timedelta

import pytest

from options_lib.payoff_metrics import calculate_payoff_metrics, estimate_payoff_metrics
from options_lib.scenario_engine import ExecutionAssumptions, OptionLeg, StrategyDefinition

VALUATION_TIME = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
EXPIRY = VALUATION_TIME + timedelta(days=365)


def _leg(
    symbol: str,
    strike: float,
    *,
    position: int = 1,
    option_type: str = "call",
    bid: float = 9.0,
    ask: float = 10.0,
    expiry: datetime = EXPIRY,
    risk_free_rate: float = 0.0,
) -> OptionLeg:
    return OptionLeg(
        symbol=symbol,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        valuation_time=VALUATION_TIME,
        spot=100.0,
        iv=0.20,
        risk_free_rate=risk_free_rate,
        bid=bid,
        ask=ask,
        position=position,
    )


def test_long_call_returns_chart_curve_and_model_estimates_without_historical_claim() -> None:
    metrics = estimate_payoff_metrics(
        StrategyDefinition("long_call", (_leg("C100", 100.0),)),
    )

    points = {point.underlying_price: point.pnl for point in metrics.payoff_curve}
    assert metrics.status == "estimated"
    assert metrics.expected_value == pytest.approx(-2.034432, abs=1e-5)
    assert metrics.win_probability == pytest.approx(0.2821, abs=1e-3)
    assert metrics.breakevens == (110.0,)
    assert points[0.0] == pytest.approx(-10.0)
    assert points[100.0] == pytest.approx(-10.0)
    assert points[110.0] == pytest.approx(0.0)
    assert metrics.risk_reward == pytest.approx(
        metrics.expected_positive_pnl / abs(metrics.expected_negative_pnl)
    )
    assert metrics.expected_negative_pnl < 0
    assert metrics.risk_reward_status == "available"
    assert metrics.assumptions is not None
    assert metrics.assumptions.entry_price_source == "long ask / short bid"
    assert metrics.assumptions.historical_outcomes_used is False
    assert any("not historical" in note.lower() for note in metrics.limitations)


def test_canonical_metrics_separate_conditional_reward_risk_from_legacy_contribution_ratio() -> (
    None
):
    metrics = calculate_payoff_metrics(
        StrategyDefinition("long_call", (_leg("C100", 100.0),)),
    )

    assert metrics.average_win == pytest.approx(15.2133456, abs=1e-5)
    assert metrics.average_loss == pytest.approx(8.8126932, abs=1e-5)
    assert metrics.reward_risk_ratio == pytest.approx(1.7262993, abs=1e-5)
    assert metrics.risk_reward_ratio == pytest.approx(metrics.reward_risk_ratio)
    assert metrics.payoff_contribution_ratio == pytest.approx(0.6784240, abs=1e-5)
    assert metrics.risk_reward == pytest.approx(metrics.payoff_contribution_ratio)
    assert metrics.risk_reward != pytest.approx(metrics.reward_risk_ratio)
    assert metrics.expectancy == pytest.approx(
        metrics.win_probability * metrics.average_win
        - (1.0 - metrics.win_probability) * metrics.average_loss
    )
    assert metrics.break_even_win_probability == pytest.approx(0.3667976, abs=1e-5)
    assert metrics.breakeven_win_probability == pytest.approx(metrics.break_even_win_probability)
    assert metrics.break_even_probability == pytest.approx(metrics.break_even_win_probability)
    assert metrics.reward_risk_ratio_status == "available"
    assert metrics.payoff_contribution_ratio_status == metrics.risk_reward_status
    assert metrics.break_even_win_probability_status == "available"


def test_model_probability_and_expiry_expectancy_have_explicit_basis_and_evidence() -> None:
    metrics = calculate_payoff_metrics(
        StrategyDefinition("long_call", (_leg("C100", 100.0),)),
    )

    assert metrics.win_probability_basis == "risk_neutral_model"
    assert metrics.probability_basis == "risk_neutral_model"
    assert metrics.evidence_status == "model_estimate"
    assert metrics.expectancy == pytest.approx(-2.0344325, abs=1e-5)
    assert metrics.expiry_expectancy == pytest.approx(metrics.expectancy)
    assert metrics.expected_value == pytest.approx(metrics.expiry_expectancy)
    assert metrics.expectancy_basis == "expiry_pnl"
    assert metrics.present_value_edge == pytest.approx(-2.0344325, abs=1e-5)
    assert metrics.fair_value_edge == pytest.approx(metrics.present_value_edge)
    assert metrics.present_value_edge_basis == "discounted_expiry_payoff_minus_entry_cash_flow"
    assert metrics.expectancy_status == "model_estimate"


def test_present_value_edge_is_separate_from_undiscounted_expiry_expectancy() -> None:
    metrics = calculate_payoff_metrics(
        StrategyDefinition(
            "long_call",
            (_leg("C100", 100.0, risk_free_rate=0.05),),
        ),
    )

    assert metrics.expectancy_basis == "expiry_pnl"
    assert metrics.present_value_edge_basis == "discounted_expiry_payoff_minus_entry_cash_flow"
    assert metrics.present_value_edge != pytest.approx(metrics.expiry_expectancy)


def test_binary_expectancy_contract_catches_one_to_one_rr_at_thirty_three_percent_wins() -> None:
    win_probability = 0.33
    average_win = 1.0
    average_loss = 1.0

    expectancy = win_probability * average_win - (1.0 - win_probability) * average_loss
    break_even_win_probability = average_loss / (average_win + average_loss)

    assert expectancy == pytest.approx(-0.34)
    assert break_even_win_probability == pytest.approx(0.50)
    assert win_probability < break_even_win_probability


def test_vertical_uses_executable_credit_and_costs_for_payoff_and_risk_reward() -> None:
    metrics = estimate_payoff_metrics(
        StrategyDefinition(
            "call_vertical",
            (
                _leg("C100", 100.0, ask=8.0),
                _leg("C120", 120.0, position=-1, bid=2.0, ask=3.0),
            ),
        ),
        ExecutionAssumptions(fee_per_contract=0.5),
    )

    points = {point.underlying_price: point.pnl for point in metrics.payoff_curve}
    assert metrics.assumptions.net_entry_cash_flow == pytest.approx(7.0)
    assert metrics.max_loss == pytest.approx(7.0)
    assert metrics.max_profit == pytest.approx(13.0)
    assert metrics.risk_reward == pytest.approx(
        metrics.expected_positive_pnl / abs(metrics.expected_negative_pnl)
    )
    assert metrics.expected_negative_pnl < 0
    assert metrics.risk_reward_status == "available"
    assert metrics.breakevens == (107.0,)
    assert points[100.0] == pytest.approx(-7.0)
    assert points[107.0] == pytest.approx(0.0)
    assert points[120.0] == pytest.approx(13.0)
    assert 0.0 < metrics.win_probability < 1.0


def test_mixed_expiry_strategy_returns_explicit_unavailable_state() -> None:
    metrics = estimate_payoff_metrics(
        StrategyDefinition(
            "calendar_spread",
            (
                _leg("C100-NEAR", 100.0, position=-1, expiry=EXPIRY),
                _leg("C100-FAR", 100.0, expiry=EXPIRY + timedelta(days=30)),
            ),
        )
    )

    assert metrics.status == "unavailable"
    assert metrics.payoff_curve == ()
    assert metrics.expected_value is None
    assert metrics.win_probability is None
    assert metrics.risk_reward is None
    assert "mixed-expiry" in metrics.limitations[0]


def test_empty_strategy_returns_inspectable_unavailable_result() -> None:
    metrics = estimate_payoff_metrics(StrategyDefinition("long_call", ()))

    assert metrics.status == "unavailable"
    assert metrics.expected_value is None
    assert metrics.assumptions is not None
    assert metrics.assumptions.net_entry_cash_flow is None
    assert "option leg" in metrics.limitations[0]
