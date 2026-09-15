import math
from datetime import UTC, datetime, timedelta

import pytest

from options_lib.volatility_surface import (
    ExtrapolationError,
    InsufficientDataError,
    VolatilityObservation,
    build_volatility_surface,
)

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def observation(
    asset: str,
    days: int,
    strike: float,
    iv: float,
    *,
    forward: float = 100.0,
    bid: float | None = 1.0,
    ask: float | None = 1.2,
    liquidity: float | None = None,
    expiry: datetime | None = None,
) -> VolatilityObservation:
    return VolatilityObservation(
        asset=asset,
        expiry=expiry or VALUATION_TIME + timedelta(days=days),
        strike=strike,
        spot=forward,
        forward=forward,
        iv=iv,
        bid=bid,
        ask=ask,
        liquidity=liquidity,
    )


def dense_chain(asset: str = "BTC") -> list[VolatilityObservation]:
    return [
        observation(asset, 60, 110, 0.60),
        observation(asset, 30, 90, 0.40),
        observation(asset, 30, 110, 0.60),
        observation(asset, 60, 90, 0.40),
    ]


def test_build_surface_sorts_real_expiries_and_keeps_decimal_total_variance():
    result = build_volatility_surface(dense_chain(), valuation_time=VALUATION_TIME)

    surface = result.surface_for("BTC")

    assert surface.is_valuation_ready is True
    assert surface.front_expiry == VALUATION_TIME + timedelta(days=30)
    assert surface.back_expiry == VALUATION_TIME + timedelta(days=60)
    assert [point.expiry for point in surface.observed_points] == sorted(
        point.expiry for point in surface.observed_points
    )
    point = next(point for point in surface.observed_points if point.expiry == surface.front_expiry)
    assert point.iv == pytest.approx(0.40)
    assert point.total_variance == pytest.approx(0.40**2 * point.time_to_expiry)
    assert point.status == "observed"


def test_query_interpolates_total_variance_in_log_moneyness():
    result = build_volatility_surface(
        [observation("BTC", 30, 90, 0.40), observation("BTC", 30, 110, 0.60)],
        valuation_time=VALUATION_TIME,
    )

    quote = result.surface_for("BTC").quote(
        expiry=VALUATION_TIME + timedelta(days=30),
        strike=100,
        forward=100,
    )
    left_x = math.log(90 / 100)
    right_x = math.log(110 / 100)
    log_weight = (0 - left_x) / (right_x - left_x)
    expected_iv_squared = 0.40**2 + log_weight * (0.60**2 - 0.40**2)
    expected_variance = expected_iv_squared * quote.time_to_expiry

    assert quote.status == "interpolated"
    assert quote.log_moneyness == pytest.approx(0.0, abs=1e-12)
    assert quote.total_variance == pytest.approx(expected_variance)
    assert quote.iv == pytest.approx((expected_variance / quote.time_to_expiry) ** 0.5)


def test_query_can_fit_around_an_observed_contract_for_fair_value():
    result = build_volatility_surface(
        [
            observation("BTC", 30, 90, 0.40),
            observation("BTC", 30, 100, 0.50),
            observation("BTC", 30, 110, 0.60),
        ],
        valuation_time=VALUATION_TIME,
    )
    surface = result.surface_for("BTC")
    expiry = VALUATION_TIME + timedelta(days=30)

    observed = surface.quote(expiry=expiry, strike=100, forward=100)
    fitted = surface.quote(
        expiry=expiry,
        strike=100,
        forward=100,
        prefer_observed=False,
    )

    assert observed.status == "observed"
    assert fitted.status == "interpolated"
    assert fitted.iv != pytest.approx(observed.iv)
    left_x = math.log(90 / 100)
    right_x = math.log(110 / 100)
    left_weight = (right_x - 0) / (right_x - left_x)
    right_weight = (0 - left_x) / (right_x - left_x)
    expected_iv = (
        left_weight * 0.40**2 + right_weight * 0.60**2
    ) ** 0.5
    assert fitted.iv == pytest.approx(expected_iv)


def test_query_interpolates_between_chronological_expiries_using_total_variance():
    result = build_volatility_surface(dense_chain(), valuation_time=VALUATION_TIME)
    target_expiry = VALUATION_TIME + timedelta(days=45)

    quote = result.surface_for("BTC").quote(
        expiry=target_expiry,
        strike=100,
        forward=100,
    )
    left_x = math.log(90 / 100)
    right_x = math.log(110 / 100)
    log_weight = (0 - left_x) / (right_x - left_x)
    short_iv_squared = 0.40**2 + log_weight * (0.60**2 - 0.40**2)
    long_iv_squared = short_iv_squared
    short_variance = short_iv_squared * (30 / 365)
    long_variance = long_iv_squared * (60 / 365)

    assert quote.status == "interpolated"
    assert quote.total_variance == pytest.approx((short_variance + long_variance) / 2)
    assert quote.expiry == target_expiry


def test_quality_filter_rejects_bad_iv_zero_quotes_expired_and_missing_liquidity():
    observations = [
        *dense_chain(),
        observation("BTC", 30, 100, 0.0),
        observation("BTC", 30, 101, -0.2),
        observation("BTC", 30, 102, 6.0),
        observation("BTC", 30, 103, 0.5, bid=0.0, ask=1.0),
        observation("BTC", 30, 104, 0.5, bid=None, ask=None),
        observation("BTC", -1, 105, 0.5),
    ]

    result = build_volatility_surface(observations, valuation_time=VALUATION_TIME)
    surface = result.surface_for("BTC")
    warning_codes = {warning.code for warning in surface.warnings}

    assert all(point.strike < 102 or point.strike > 104 for point in surface.observed_points)
    assert {
        "invalid_iv",
        "zero_quote",
        "insufficient_liquidity",
        "expired_observation",
    } <= warning_codes


def test_sparse_surface_warns_and_refuses_fair_value_claim():
    result = build_volatility_surface(
        [observation("BTC", 30, 100, 0.5)], valuation_time=VALUATION_TIME
    )
    surface = result.surface_for("BTC")

    assert surface.is_valuation_ready is False
    assert any(warning.code == "insufficient_data" for warning in surface.warnings)
    with pytest.raises(InsufficientDataError, match="at least two valid points"):
        surface.quote(
            expiry=VALUATION_TIME + timedelta(days=30), strike=100, forward=100
        )


def test_out_of_range_query_is_explicit_and_optional_extrapolation_is_marked():
    result = build_volatility_surface(
        [observation("BTC", 30, 90, 0.4), observation("BTC", 30, 110, 0.6)],
        valuation_time=VALUATION_TIME,
    )
    surface = result.surface_for("BTC")
    expiry = VALUATION_TIME + timedelta(days=30)

    with pytest.raises(ExtrapolationError, match="strike"):
        surface.quote(expiry=expiry, strike=120, forward=100)

    quote = surface.quote(
        expiry=expiry, strike=120, forward=100, allow_extrapolation=True
    )
    assert quote.status == "extrapolated"


def test_multiple_assets_and_duplicate_points_are_deterministic():
    observations = [
        observation("ETH", 30, 3000, 0.5, forward=3000, bid=5, ask=6),
        observation("BTC", 30, 90, 0.4),
        observation("BTC", 30, 110, 0.6),
        observation("BTC", 30, 90, 0.9, bid=2, ask=3),
        observation("ETH", 30, 3020, 0.55, forward=3000, bid=5, ask=6),
    ]

    result = build_volatility_surface(list(reversed(observations)), valuation_time=VALUATION_TIME)

    assert result.assets == ("BTC", "ETH")
    btc = result.surface_for("BTC")
    kept = next(point for point in btc.observed_points if point.strike == 90)
    assert kept.iv == pytest.approx(0.4)
    assert any(warning.code == "duplicate_point" for warning in btc.warnings)


def test_bybit_expiry_code_uses_eight_am_utc_delivery_convention():
    result = build_volatility_surface(
        [
            observation("BTC", 30, 90, 0.40, expiry="25SEP26"),
            observation("BTC", 30, 110, 0.60, expiry="25SEP26"),
        ],
        valuation_time=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
    )

    assert result.surface_for("BTC").front_expiry == datetime(
        2026, 9, 25, 8, 0, tzinfo=UTC
    )


def test_explicit_zero_forward_is_rejected_instead_of_using_spot():
    result = build_volatility_surface(
        [
            VolatilityObservation(
                asset="BTC",
                expiry=VALUATION_TIME + timedelta(days=30),
                strike=90,
                spot=100,
                forward=0,
                iv=0.4,
                bid=1,
                ask=1.2,
            ),
            observation("BTC", 30, 110, 0.6),
        ],
        valuation_time=VALUATION_TIME,
    )

    surface = result.surface_for("BTC")
    assert any(warning.code == "invalid_price" for warning in surface.warnings)
    assert all(point.strike != 90 for point in surface.observed_points)
