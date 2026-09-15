from datetime import UTC, datetime, timedelta

import pytest

from options_lib.scenario_engine import (
    ExecutionAssumptions,
    MarketScenario,
    OptionLeg,
    ScenarioSet,
    ScenarioValidationError,
    StrategyDefinition,
    evaluate_scenarios,
)
from options_lib.volatility_surface import VolatilityObservation, build_volatility_surface

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
EXPIRY = VALUATION_TIME + timedelta(days=30)


def _leg(
    strike: float,
    *,
    option_type: str = "call",
    position: int = 1,
    iv: float = 0.30,
    bid: float = 5.0,
    ask: float = 5.5,
    expiry: datetime = EXPIRY,
    surface=None,
) -> OptionLeg:
    return OptionLeg(
        symbol=f"BTC-{strike:g}-{option_type[0].upper()}",
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        valuation_time=VALUATION_TIME,
        spot=100.0,
        iv=iv,
        risk_free_rate=0.0,
        bid=bid,
        ask=ask,
        position=position,
        surface=surface,
    )


def _scenario_set(*scenarios: MarketScenario, **kwargs) -> ScenarioSet:
    return ScenarioSet(
        scenarios=tuple(scenarios),
        execution=ExecutionAssumptions(**kwargs),
    )


def test_debit_call_spread_reports_bounded_pnl_and_greeks() -> None:
    strategy = StrategyDefinition(
        strategy_type="call_vertical",
        legs=(
            _leg(100.0, bid=4.8, ask=5.5),
            _leg(110.0, position=-1, bid=1.5, ask=1.8),
        ),
    )
    report = evaluate_scenarios(
        strategy,
        _scenario_set(
            MarketScenario("flat_at_expiry", underlying_move_pct=0.0, elapsed_days=30),
            MarketScenario("large_up", underlying_move_pct=25.0, elapsed_days=30),
            exit_price_source="model",
        ),
    )

    assert report.status == "model_only"
    assert report.max_loss == pytest.approx(4.0)
    assert report.max_profit == pytest.approx(6.0)
    assert report.breakevens == pytest.approx((104.0,))
    assert report.aggregate_greeks.delta == pytest.approx(0.0, abs=1.0)
    assert report.scenarios[0].pnl == pytest.approx(-4.0)
    assert report.scenarios[1].pnl == pytest.approx(6.0)
    assert all(item.pnl >= -report.max_loss - 1e-9 for item in report.scenarios)


def test_debit_put_spread_has_put_breakeven_and_bounded_loss() -> None:
    strategy = StrategyDefinition(
        strategy_type="put_vertical",
        legs=(
            _leg(110.0, option_type="put", bid=10.0, ask=10.5),
            _leg(100.0, option_type="put", position=-1, bid=6.0, ask=6.5),
        ),
    )
    report = evaluate_scenarios(
        strategy,
        _scenario_set(
            MarketScenario("large_down", underlying_move_pct=-25.0, elapsed_days=30),
            exit_price_source="model",
        ),
    )

    assert report.max_loss == pytest.approx(4.5)
    assert report.max_profit == pytest.approx(5.5)
    assert report.breakevens == pytest.approx((105.5,))
    assert report.scenarios[0].pnl == pytest.approx(5.5)


def test_flat_price_and_time_decay_reduce_long_call_value() -> None:
    strategy = StrategyDefinition(
        strategy_type="long_call",
        legs=(_leg(100.0, bid=5.0, ask=5.5),),
    )
    report = evaluate_scenarios(
        strategy,
        _scenario_set(
            MarketScenario("now", elapsed_days=0),
            MarketScenario("five_days", elapsed_days=5),
            exit_price_source="model",
        ),
    )

    assert report.scenarios[1].pnl < report.scenarios[0].pnl
    assert report.scenarios[1].greeks.theta < 0.0


def test_iv_crush_hurts_long_option_even_without_price_move() -> None:
    strategy = StrategyDefinition(
        strategy_type="long_call",
        legs=(_leg(100.0, bid=5.0, ask=5.5, iv=0.40),),
    )
    report = evaluate_scenarios(
        strategy,
        _scenario_set(
            MarketScenario("unchanged_iv", iv_move=0.0),
            MarketScenario("iv_crush", iv_move=-0.20),
            exit_price_source="model",
        ),
    )

    assert report.scenarios[1].pnl < report.scenarios[0].pnl


def test_costs_bid_ask_and_multiplier_are_included_in_loss_bound() -> None:
    strategy = StrategyDefinition(
        strategy_type="call_vertical",
        legs=(
            _leg(100.0, bid=4.0, ask=6.0),
            _leg(120.0, position=-1, bid=0.5, ask=1.0),
        ),
    )
    report = evaluate_scenarios(
        strategy,
        _scenario_set(
            MarketScenario("expiry_flat", elapsed_days=30),
            fee_per_contract=0.25,
            slippage_bps=100.0,
            contract_multiplier=2.0,
            exit_price_source="model",
        ),
    )

    assert report.max_loss > (6.0 - 0.5) * 2.0
    assert report.max_loss == pytest.approx(12.0 + 1.0 + 0.13)
    assert report.scenarios[0].pnl >= -report.max_loss - 1e-9
    assert any("cost" in warning.code for warning in report.warnings)


def test_model_only_and_surface_extrapolation_are_explicitly_labelled() -> None:
    model_only_strategy = StrategyDefinition(
        strategy_type="long_call",
        legs=(_leg(100.0),),
    )
    model_only = evaluate_scenarios(
        model_only_strategy,
        _scenario_set(MarketScenario("flat"), exit_price_source="model"),
    )
    assert model_only.status == "model_only"
    assert any(warning.code == "model_only" for warning in model_only.warnings)

    surface = build_volatility_surface(
        [
            VolatilityObservation("BTC", EXPIRY, 90, 100, 0.25, bid=1, ask=2),
            VolatilityObservation("BTC", EXPIRY, 110, 100, 0.35, bid=1, ask=2),
        ],
        valuation_time=VALUATION_TIME,
    ).surface_for("BTC")
    extrapolated_strategy = StrategyDefinition(
        strategy_type="long_call",
        legs=(_leg(130.0, surface=surface),),
    )
    extrapolated = evaluate_scenarios(
        extrapolated_strategy,
        _scenario_set(MarketScenario("flat"), exit_price_source="model"),
    )
    assert extrapolated.status == "extrapolated"
    assert any(warning.code == "surface_extrapolated" for warning in extrapolated.warnings)


@pytest.mark.parametrize(
    ("strategy_type", "legs"),
    [
        ("long_call", (_leg(100.0, position=-1),)),
        ("call_vertical", (_leg(110.0), _leg(100.0, position=-1))),
        ("put_vertical", (_leg(100.0, option_type="put"), _leg(110.0, option_type="put", position=-1))),
        ("call_vertical", (_leg(100.0),)),
    ],
)
def test_naked_short_and_invalid_verticals_are_rejected(strategy_type, legs) -> None:
    with pytest.raises(ScenarioValidationError):
        evaluate_scenarios(
            StrategyDefinition(strategy_type=strategy_type, legs=legs),
            _scenario_set(MarketScenario("flat"), exit_price_source="model"),
        )
