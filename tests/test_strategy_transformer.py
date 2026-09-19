"""Unit tests for StrategyTransformer in portfolio_lib."""

from datetime import datetime, timezone
import pytest

from portfolio_lib.transformer import StrategyTransformer
from portfolio_lib.types import Portfolio, Position


def test_strategy_transformer_condor_adjustment_roll_untested():
    transformer = StrategyTransformer()
    # Iron Condor: LP 58k, SP 61k, SC 69k, LC 72k
    portfolio = Portfolio(
        name="test_condor",
        positions={
            "BTC-26SEP26-58000-P": Position(symbol="BTC-26SEP26-58000-P", quantity=1.0),
            "BTC-26SEP26-61000-P": Position(symbol="BTC-26SEP26-61000-P", quantity=-1.0),
            "BTC-26SEP26-69000-C": Position(symbol="BTC-26SEP26-69000-C", quantity=-1.0),
            "BTC-26SEP26-72000-C": Position(symbol="BTC-26SEP26-72000-C", quantity=1.0),
        },
        metadata={"strategy": "iron_condor"},
        created_at=datetime.now(timezone.utc),
    )

    # Call breached: roll untested put spread up by 2000
    adj_portfolio = transformer.condor_adjustment(
        portfolio,
        adjustment_type="roll_untested",
        breached_side="call",
        roll_strike_offset=2000.0,
    )

    assert "BTC-26SEP26-69000-C" in adj_portfolio.positions
    assert "BTC-26SEP26-72000-C" in adj_portfolio.positions
    # Old puts removed
    assert "BTC-26SEP26-58000-P" not in adj_portfolio.positions
    assert "BTC-26SEP26-61000-P" not in adj_portfolio.positions
    # New rolled puts added
    assert "BTC-26SEP26-60000-P" in adj_portfolio.positions
    assert "BTC-26SEP26-63000-P" in adj_portfolio.positions
    assert adj_portfolio.positions["BTC-26SEP26-63000-P"].quantity == -1.0
    assert adj_portfolio.positions["BTC-26SEP26-60000-P"].quantity == 1.0


def test_strategy_transformer_condor_adjustment_close_tested():
    transformer = StrategyTransformer()
    portfolio = Portfolio(
        name="test_condor",
        positions={
            "BTC-26SEP26-58000-P": Position(symbol="BTC-26SEP26-58000-P", quantity=1.0),
            "BTC-26SEP26-61000-P": Position(symbol="BTC-26SEP26-61000-P", quantity=-1.0),
            "BTC-26SEP26-69000-C": Position(symbol="BTC-26SEP26-69000-C", quantity=-1.0),
            "BTC-26SEP26-72000-C": Position(symbol="BTC-26SEP26-72000-C", quantity=1.0),
        },
        metadata={"strategy": "iron_condor"},
        created_at=datetime.now(timezone.utc),
    )

    # Put breached: close put spread
    adj_portfolio = transformer.condor_adjustment(
        portfolio,
        adjustment_type="close_tested",
        breached_side="put",
    )

    assert "BTC-26SEP26-58000-P" not in adj_portfolio.positions
    assert "BTC-26SEP26-61000-P" not in adj_portfolio.positions
    assert "BTC-26SEP26-69000-C" in adj_portfolio.positions
    assert "BTC-26SEP26-72000-C" in adj_portfolio.positions


def test_strategy_transformer_butterfly_to_broken_wing():
    transformer = StrategyTransformer()
    portfolio = Portfolio(
        name="test_butterfly",
        positions={
            "BTC-26SEP26-63000-C": Position(symbol="BTC-26SEP26-63000-C", quantity=1.0),
            "BTC-26SEP26-65000-C": Position(symbol="BTC-26SEP26-65000-C", quantity=-2.0),
            "BTC-26SEP26-67000-C": Position(symbol="BTC-26SEP26-67000-C", quantity=1.0),
        },
        metadata={"strategy": "iron_butterfly"},
        created_at=datetime.now(timezone.utc),
    )

    broken_wing = transformer.butterfly_to_broken_wing(portfolio, bias="bullish")
    # Upper wing moved farther out from 67000 to 68000
    assert "BTC-26SEP26-67000-C" not in broken_wing.positions
    assert "BTC-26SEP26-68000-C" in broken_wing.positions
    assert broken_wing.positions["BTC-26SEP26-68000-C"].quantity == 1.0
