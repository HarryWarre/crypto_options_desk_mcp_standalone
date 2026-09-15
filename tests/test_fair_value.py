import math
from datetime import UTC, datetime

import pytest

from options_lib.pricing import (
    FairValueRequest,
    PricingValidationError,
    price_fair_value,
)
from options_lib.volatility_surface import VolatilityObservation, build_volatility_surface

VALUATION_TIME = datetime(2026, 1, 1, tzinfo=UTC)
EXPIRY = datetime(2027, 1, 1, tzinfo=UTC)


def test_black_scholes_call_returns_price_and_auditable_greeks() -> None:
    result = price_fair_value(
        FairValueRequest(
            option_type="call",
            spot=100.0,
            strike=100.0,
            expiry=EXPIRY,
            valuation_time=VALUATION_TIME,
            iv=0.20,
            risk_free_rate=0.05,
        )
    )

    assert result.model == "black_scholes"
    assert result.status == "ok"
    assert result.fair_price == pytest.approx(10.45058357, rel=1e-7)
    assert result.intrinsic_value == 0.0
    assert result.time_value == pytest.approx(result.fair_price)
    assert result.delta == pytest.approx(0.63683065, rel=1e-7)
    assert result.gamma == pytest.approx(0.01876202, rel=1e-6)
    assert result.theta == pytest.approx(-0.01757268, rel=1e-6)
    assert result.vega == pytest.approx(0.37524035, rel=1e-7)
    assert result.rho == pytest.approx(0.53232482, rel=1e-7)
    assert result.time_to_expiry_years == pytest.approx(1.0, abs=1e-12)


def test_black_scholes_put_returns_put_greeks_and_intrinsic_value() -> None:
    result = price_fair_value(
        FairValueRequest(
            option_type="P",
            spot=90.0,
            strike=100.0,
            expiry=EXPIRY,
            valuation_time=VALUATION_TIME,
            iv=0.20,
            risk_free_rate=0.05,
        )
    )

    assert result.model == "black_scholes"
    assert result.option_type == "put"
    assert result.fair_price > result.intrinsic_value == 10.0
    assert result.delta < 0.0
    assert result.gamma > 0.0
    assert result.vega > 0.0
    assert result.rho < 0.0


def test_black_76_uses_forward_and_returns_discounted_fair_value() -> None:
    result = price_fair_value(
        FairValueRequest(
            option_type="call",
            forward=105.0,
            strike=100.0,
            expiry=EXPIRY,
            valuation_time=VALUATION_TIME,
            iv=0.20,
            risk_free_rate=0.05,
        )
    )

    assert result.model == "black_76"
    assert result.fair_price == pytest.approx(10.37372140, rel=1e-7)
    assert result.intrinsic_value == pytest.approx(5.0 * 2.718281828459045 ** -0.05)
    assert result.delta == pytest.approx(0.60361059, rel=1e-7)
    assert result.gamma == pytest.approx(0.01703284, rel=1e-7)
    assert result.theta == pytest.approx(-0.00886864, rel=1e-6)
    assert result.vega == pytest.approx(0.37557411, rel=1e-7)
    assert result.rho == pytest.approx(-0.10373721, rel=1e-7)


def test_black_76_deep_in_the_money_intrinsic_is_present_value() -> None:
    result = price_fair_value(
        FairValueRequest(
            option_type="call",
            forward=200.0,
            strike=100.0,
            expiry=EXPIRY,
            valuation_time=VALUATION_TIME,
            iv=0.20,
            risk_free_rate=0.05,
        )
    )

    discounted_intrinsic = 100.0 * 2.718281828459045 ** -0.05
    assert result.intrinsic_value == pytest.approx(discounted_intrinsic)
    assert result.fair_price >= result.intrinsic_value
    assert result.time_value >= 0.0


def test_surface_resolves_fair_iv_and_reports_fitted_status() -> None:
    surface = build_volatility_surface(
        [
            VolatilityObservation(
                asset="BTC",
                expiry=EXPIRY,
                strike=90,
                spot=100,
                forward=100,
                iv=0.40,
                bid=1,
                ask=1.2,
            ),
            VolatilityObservation(
                asset="BTC",
                expiry=EXPIRY,
                strike=100,
                spot=100,
                forward=100,
                iv=0.50,
                bid=1,
                ask=1.2,
            ),
            VolatilityObservation(
                asset="BTC",
                expiry=EXPIRY,
                strike=110,
                spot=100,
                forward=100,
                iv=0.60,
                bid=1,
                ask=1.2,
            ),
        ],
        valuation_time=VALUATION_TIME,
    ).surface_for("BTC")

    result = price_fair_value(
        FairValueRequest(
            option_type="call",
            forward=100.0,
            strike=100.0,
            expiry=EXPIRY,
            valuation_time=VALUATION_TIME,
            iv=None,
            risk_free_rate=0.05,
            surface=surface,
            prefer_observed_surface=False,
        )
    )

    left_x = math.log(90 / 100)
    right_x = math.log(110 / 100)
    left_weight = (right_x - 0) / (right_x - left_x)
    right_weight = (0 - left_x) / (right_x - left_x)
    expected_iv = (
        left_weight * 0.40**2 + right_weight * 0.60**2
    ) ** 0.5
    assert result.fair_iv == pytest.approx(expected_iv)
    assert result.surface_status == "interpolated"


def test_market_edges_are_reported_separately_from_fair_value() -> None:
    result = price_fair_value(
        FairValueRequest(
            option_type="call",
            spot=100.0,
            strike=100.0,
            expiry=EXPIRY,
            valuation_time=VALUATION_TIME,
            iv=0.20,
            risk_free_rate=0.05,
            market_bid=8.0,
            market_ask=10.0,
            market_iv=0.15,
        )
    )

    assert result.market_mid == pytest.approx(9.0)
    assert result.fair_iv == pytest.approx(0.20)
    assert result.iv_edge == pytest.approx(0.05)
    assert result.price_edge == pytest.approx(result.fair_price - 9.0)


def test_expiry_returns_intrinsic_without_fabricating_greeks() -> None:
    result = price_fair_value(
        FairValueRequest(
            option_type="put",
            spot=95.0,
            strike=100.0,
            expiry=VALUATION_TIME,
            valuation_time=VALUATION_TIME,
            iv=0.20,
            risk_free_rate=0.05,
        )
    )

    assert result.status == "expired"
    assert result.fair_price == 5.0
    assert result.intrinsic_value == 5.0
    assert result.time_value == 0.0
    assert result.time_to_expiry_years == 0.0
    assert result.delta == 0.0
    assert result.gamma == 0.0
    assert result.theta == 0.0
    assert result.vega == 0.0
    assert result.rho == 0.0


@pytest.mark.parametrize(
    ("pricing_request", "message"),
    [
        (
            FairValueRequest(
                option_type="call",
                strike=100.0,
                expiry=EXPIRY,
                valuation_time=VALUATION_TIME,
                iv=0.20,
                risk_free_rate=0.05,
            ),
            "exactly one of spot or forward",
        ),
        (
            FairValueRequest(
                option_type="call",
                spot=100.0,
                forward=101.0,
                strike=100.0,
                expiry=EXPIRY,
                valuation_time=VALUATION_TIME,
                iv=0.20,
                risk_free_rate=0.05,
            ),
            "exactly one of spot or forward",
        ),
        (
            FairValueRequest(
                option_type="call",
                spot=100.0,
                strike=100.0,
                expiry=EXPIRY,
                valuation_time=VALUATION_TIME,
                iv=None,
                risk_free_rate=0.05,
            ),
            "iv",
        ),
        (
            FairValueRequest(
                option_type="call",
                spot=100.0,
                strike=100.0,
                expiry=EXPIRY,
                valuation_time=VALUATION_TIME,
                iv=-0.20,
                risk_free_rate=0.05,
            ),
            "greater than zero",
        ),
        (
            FairValueRequest(
                option_type="call",
                spot=100.0,
                strike=0.0,
                expiry=EXPIRY,
                valuation_time=VALUATION_TIME,
                iv=0.20,
                risk_free_rate=0.05,
            ),
            "strike",
        ),
        (
            FairValueRequest(
                option_type="call",
                forward=100.0,
                strike=100.0,
                expiry=EXPIRY,
                valuation_time=VALUATION_TIME,
                iv=0.20,
                risk_free_rate=0.05,
                dividend_yield=0.01,
            ),
            "dividend_yield",
        ),
        (
            FairValueRequest(
                option_type="call",
                forward=0.0,
                strike=100.0,
                expiry=EXPIRY,
                valuation_time=VALUATION_TIME,
                iv=0.20,
                risk_free_rate=0.05,
            ),
            "greater than zero",
        ),
    ],
)
def test_invalid_inputs_raise_auditable_validation_errors(
    pricing_request: FairValueRequest, message: str
) -> None:
    with pytest.raises(PricingValidationError, match=message):
        price_fair_value(pricing_request)


def test_expiry_before_valuation_time_is_rejected() -> None:
    with pytest.raises(PricingValidationError, match="expiry"):
        price_fair_value(
            FairValueRequest(
                option_type="call",
                spot=100.0,
                strike=100.0,
                expiry=datetime(2025, 12, 31, tzinfo=UTC),
                valuation_time=VALUATION_TIME,
                iv=0.20,
                risk_free_rate=0.05,
            )
        )


def test_mixed_timezone_inputs_are_rejected_instead_of_being_silently_shifted() -> None:
    with pytest.raises(PricingValidationError, match="timezone"):
        price_fair_value(
            FairValueRequest(
                option_type="call",
                spot=100.0,
                strike=100.0,
                expiry=EXPIRY.replace(tzinfo=None),
                valuation_time=VALUATION_TIME,
                iv=0.20,
                risk_free_rate=0.05,
            )
        )
