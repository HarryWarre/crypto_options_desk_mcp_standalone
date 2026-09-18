"""Unit tests for the Strategy Builder engine."""

from datetime import UTC, datetime, timedelta

import pytest

from options_lib.strategy.builder import (
    STRATEGY_TEMPLATES,
    BuilderLegInput,
    build_template_legs_from_chain,
    evaluate_builder_strategy,
)


def test_strategy_templates_coverage():
    """Ensure catalog contains standard strategies."""
    expected = [
        "long_call",
        "long_put",
        "covered_call",
        "protective_put",
        "bull_call_vertical",
        "bear_put_vertical",
        "bear_call_vertical",
        "bull_put_vertical",
        "iron_condor",
        "iron_butterfly",
        "long_straddle",
        "long_strangle",
        "butterfly",
    ]
    for key in expected:
        assert key in STRATEGY_TEMPLATES
        template = STRATEGY_TEMPLATES[key]
        assert "name" in template
        assert "legs" in template
        assert len(template["legs"]) > 0


def test_evaluate_long_call():
    """Test evaluation of a simple long call."""
    now = datetime.now(UTC)
    expiry = now + timedelta(days=14)
    spot = 60000.0
    strike = 62000.0

    leg = BuilderLegInput(
        option_type="call",
        strike=strike,
        expiry=expiry,
        iv=0.65,
        spot=spot,
        position=1,
        mid_price=1200.0,
        risk_free_rate=0.05,
    )

    result = evaluate_builder_strategy([leg], strategy_type="long_call")

    assert result.strategy_type == "long_call"
    assert result.net_premium == 1200.0
    assert len(result.payoff_curve) > 0
    # Long call max loss is premium paid
    assert result.max_loss == -1200.0
    # Long call max profit is unlimited
    assert result.max_profit is None
    # Breakeven should be strike + premium = 63200
    assert len(result.breakevens) == 1
    assert abs(result.breakevens[0] - 63200.0) < 200.0
    # Greeks
    assert result.delta > 0
    assert result.gamma > 0
    assert result.theta < 0  # theta decay for long option
    assert result.vega > 0   # long vega


def test_evaluate_bull_call_vertical():
    """Test evaluation of a bull call spread (defined risk/reward)."""
    now = datetime.now(UTC)
    expiry = now + timedelta(days=21)
    spot = 60000.0

    long_leg = BuilderLegInput(
        option_type="call",
        strike=60000.0,
        expiry=expiry,
        iv=0.60,
        spot=spot,
        position=1,
        mid_price=2500.0,
    )
    short_leg = BuilderLegInput(
        option_type="call",
        strike=65000.0,
        expiry=expiry,
        iv=0.62,
        spot=spot,
        position=-1,
        mid_price=1000.0,
    )

    result = evaluate_builder_strategy([long_leg, short_leg], strategy_type="bull_call_vertical")

    assert result.strategy_type == "bull_call_vertical"
    assert result.net_premium == 1500.0  # debit = 2500 - 1000
    # Max loss = debit
    assert result.max_loss == -1500.0
    # Max profit = spread width (5000) - debit (1500) = 3500
    assert result.max_profit == 3500.0
    # Breakeven = 60000 + 1500 = 61500
    assert len(result.breakevens) == 1
    assert abs(result.breakevens[0] - 61500.0) < 150.0
    # Delta should be positive
    assert result.delta > 0


def test_evaluate_iron_condor():
    """Test evaluation of an iron condor (4 legs, credit)."""
    now = datetime.now(UTC)
    expiry = now + timedelta(days=30)
    spot = 60000.0

    legs = [
        BuilderLegInput(option_type="put", strike=52000.0, expiry=expiry, iv=0.65, spot=spot, position=1, mid_price=400.0),
        BuilderLegInput(option_type="put", strike=55000.0, expiry=expiry, iv=0.62, spot=spot, position=-1, mid_price=900.0),
        BuilderLegInput(option_type="call", strike=65000.0, expiry=expiry, iv=0.60, spot=spot, position=-1, mid_price=800.0),
        BuilderLegInput(option_type="call", strike=68000.0, expiry=expiry, iv=0.63, spot=spot, position=1, mid_price=350.0),
    ]

    result = evaluate_builder_strategy(legs, strategy_type="iron_condor")

    assert result.strategy_type == "iron_condor"
    # Net credit = -400 + 900 + 800 - 350 = 950 => net_premium is negative = -950
    assert result.net_premium == -950.0
    assert result.max_profit == 950.0
    # Max loss = spread width (3000) - credit (950) = 2050 => -2050
    assert result.max_loss == -2050.0
    # Two breakevens
    assert len(result.breakevens) == 2


def test_build_template_legs_from_chain():
    """Test auto-populating legs from simulated options chain."""
    spot = 60000.0
    contracts = [
        {"symbol": "BTC-28MAR25-50000-P", "option_type": "put", "strike": 50000.0, "expiry": "2025-03-28", "iv": 0.65, "bid": 200.0, "ask": 250.0},
        {"symbol": "BTC-28MAR25-55000-P", "option_type": "put", "strike": 55000.0, "expiry": "2025-03-28", "iv": 0.62, "bid": 600.0, "ask": 650.0},
        {"symbol": "BTC-28MAR25-60000-P", "option_type": "put", "strike": 60000.0, "expiry": "2025-03-28", "iv": 0.60, "bid": 1500.0, "ask": 1600.0},
        {"symbol": "BTC-28MAR25-60000-C", "option_type": "call", "strike": 60000.0, "expiry": "2025-03-28", "iv": 0.60, "bid": 1500.0, "ask": 1600.0},
        {"symbol": "BTC-28MAR25-65000-C", "option_type": "call", "strike": 65000.0, "expiry": "2025-03-28", "iv": 0.61, "bid": 500.0, "ask": 550.0},
        {"symbol": "BTC-28MAR25-70000-C", "option_type": "call", "strike": 70000.0, "expiry": "2025-03-28", "iv": 0.64, "bid": 150.0, "ask": 200.0},
    ]

    legs = build_template_legs_from_chain("bull_call_vertical", spot=spot, contracts=contracts)
    assert len(legs) == 2
    assert legs[0].option_type == "call"
    assert legs[0].position == 1
    assert legs[1].option_type == "call"
    assert legs[1].position == -1
    assert legs[0].strike < legs[1].strike
