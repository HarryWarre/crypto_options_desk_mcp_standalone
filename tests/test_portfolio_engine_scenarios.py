import pytest

from portfolio_lib.engine import PortfolioEngine
from portfolio_lib.types import Greeks, Portfolio, Position, Scenario


def _portfolio(*, quantity: float = 1.0, underlying_price=None) -> Portfolio:
    metadata = {}
    if underlying_price is not None:
        metadata["underlying_price"] = underlying_price

    return Portfolio(
        name="scenario-regression",
        positions={
            "BTC-OPTION": Position(
                symbol="BTC-OPTION",
                quantity=quantity,
                current_price=1.0,
                greeks=Greeks(delta=0.6, gamma=0.02, theta=-1.5, vega=2.0),
            )
        },
        metadata=metadata,
    )


def _pnl(portfolio: Portfolio, scenario: Scenario) -> float:
    result = PortfolioEngine(portfolio_dir="/tmp/flowsurface-portfolio-engine-tests").analyze_scenario(
        portfolio, [scenario]
    )
    return result.pnl_matrix.iloc[0]["pnl"]


def test_spot_only_uses_absolute_underlying_move_not_option_price() -> None:
    scenario = Scenario(name="spot-up", spot_change_pct=10.0)

    assert _pnl(_portfolio(underlying_price=100.0), scenario) == pytest.approx(6.0)


def test_vol_only_uses_vega_per_vol_percentage_point() -> None:
    scenario = Scenario(name="vol-up", iv_change_pct=10.0)

    assert _pnl(_portfolio(underlying_price=100.0), scenario) == pytest.approx(20.0)


def test_theta_uses_theta_per_calendar_day() -> None:
    scenario = Scenario(name="time-decay", days_forward=3)

    assert _pnl(_portfolio(underlying_price=100.0), scenario) == pytest.approx(-4.5)


def test_signed_quantity_reverses_and_scales_pnl() -> None:
    scenario = Scenario(name="short-spot-up", spot_change_pct=10.0)

    assert _pnl(_portfolio(quantity=-2.0, underlying_price=100.0), scenario) == pytest.approx(-12.0)


def test_missing_underlying_price_fails_clearly_without_using_option_price() -> None:
    scenario = Scenario(name="spot-up", spot_change_pct=10.0)

    with pytest.raises(ValueError, match="underlying_price"):
        _pnl(_portfolio(), scenario)
