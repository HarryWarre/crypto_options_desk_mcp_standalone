from datetime import UTC, datetime, timedelta

import pytest

from position_monitoring import (
    DecisionAction,
    ExitDecisionEngine,
    ExitPolicy,
    PositionSide,
    ThesisStatus,
    TrackedPosition,
)

AS_OF = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def position(
    *,
    side: PositionSide = PositionSide.LONG,
    mark_price: float = 105,
    pnl: float = 10,
    liquidation_price: float | None = None,
    category: str = "option",
) -> TrackedPosition:
    return TrackedPosition(
        symbol="BTC-25SEP26-100000-C",
        category=category,
        side=side,
        quantity=1,
        avg_entry_price=100,
        mark_price=mark_price,
        unrealized_pnl=pnl,
        liquidation_price=liquidation_price,
        observed_at=AS_OF,
        source="fixture",
    )


def test_take_profit_requests_manual_close_on_the_opposite_side() -> None:
    decision = ExitDecisionEngine().decide(
        position(mark_price=110),
        ExitPolicy(symbol="BTC-25SEP26-100000-C", take_profit_price=108),
        as_of=AS_OF,
    )

    assert decision.action is DecisionAction.CLOSE
    assert decision.reasons == ("take_profit",)
    assert decision.manual_close_instruction == {
        "mode": "manual_review_required",
        "category": "option",
        "symbol": "BTC-25SEP26-100000-C",
        "side": "sell",
        "quantity": 1,
        "reduce_only": True,
        "close_on_trigger": False,
        "reason": "exit decision engine requested a human-reviewed close",
    }


def test_short_stop_loss_requests_buy_to_close() -> None:
    decision = ExitDecisionEngine().decide(
        position(side=PositionSide.SHORT, mark_price=110, pnl=-10),
        ExitPolicy(symbol="BTC-25SEP26-100000-C", stop_loss_price=108),
        as_of=AS_OF,
    )

    assert decision.action is DecisionAction.CLOSE
    assert decision.reasons == ("stop_loss",)
    assert decision.manual_close_instruction["side"] == "buy"


def test_position_is_hold_only_when_a_policy_exists_and_no_rule_triggers() -> None:
    decision = ExitDecisionEngine().decide(
        position(mark_price=105, pnl=1),
        ExitPolicy(symbol="BTC-25SEP26-100000-C", stop_loss_price=90, take_profit_price=120),
        as_of=AS_OF,
    )

    assert decision.action is DecisionAction.HOLD
    assert decision.reasons == ("no_exit_condition_met",)


def test_missing_policy_is_review_not_hold() -> None:
    decision = ExitDecisionEngine().decide(position(), None, as_of=AS_OF)

    assert decision.action is DecisionAction.REVIEW
    assert decision.reasons == ("missing_exit_policy",)
    assert decision.manual_close_instruction is None


def test_max_loss_percentage_uses_explicit_risk_budget() -> None:
    decision = ExitDecisionEngine().decide(
        position(pnl=-25),
        ExitPolicy(
            symbol="BTC-25SEP26-100000-C",
            max_loss_pct=0.2,
            risk_budget=100,
        ),
        as_of=AS_OF,
    )

    assert decision.action is DecisionAction.CLOSE
    assert decision.assessment.loss_pct == pytest.approx(0.25)
    assert decision.reasons == ("max_loss_pct",)


def test_liquidation_distance_is_a_hard_close_rule_for_derivatives() -> None:
    decision = ExitDecisionEngine().decide(
        position(mark_price=100, pnl=-2, liquidation_price=92, category="linear"),
        ExitPolicy(
            symbol="BTC-25SEP26-100000-C",
            min_liquidation_distance_pct=0.1,
        ),
        as_of=AS_OF,
    )

    assert decision.action is DecisionAction.CLOSE
    assert decision.reasons == ("liquidation_distance",)
    assert decision.manual_close_instruction["close_on_trigger"] is True


def test_expired_holding_time_closes() -> None:
    decision = ExitDecisionEngine().decide(
        position(),
        ExitPolicy(
            symbol="BTC-25SEP26-100000-C",
            max_holding_hours=24,
            opened_at=AS_OF - timedelta(hours=25),
        ),
        as_of=AS_OF,
    )

    assert decision.action is DecisionAction.CLOSE
    assert decision.reasons == ("max_holding_time",)


def test_invalid_thesis_closes_even_without_price_target() -> None:
    decision = ExitDecisionEngine().decide(
        position(),
        ExitPolicy(
            symbol="BTC-25SEP26-100000-C",
            thesis_status=ThesisStatus.INVALID,
        ),
        as_of=AS_OF,
    )

    assert decision.action is DecisionAction.CLOSE
    assert decision.reasons == ("thesis_invalid",)


def test_loss_percentage_requires_explicit_risk_budget() -> None:
    with pytest.raises(ValueError, match="risk_budget"):
        ExitPolicy(symbol="BTC-25SEP26-100000-C", max_loss_pct=0.2)
