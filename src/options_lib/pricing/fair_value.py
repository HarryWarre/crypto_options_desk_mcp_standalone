"""Auditable single-option fair value and Greeks calculations.

The public seam is :func:`price_fair_value`: a validated request produces a
result with an explicit model, time convention, and Greek units.  Volatility
and rates are decimal values (for example, ``0.25`` means 25%).

Greek conventions returned by this module:

* ``theta`` is price change per calendar day;
* ``vega`` is price change for one volatility percentage point;
* ``rho`` is price change for one interest-rate percentage point.

The Black-76 delta and gamma treat the supplied forward as moving one-for-one
with the underlying.  This is the useful risk convention for a forward-based
crypto option quote, and is stated here rather than hidden in the formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import erf, exp, isfinite, log, pi, sqrt
from numbers import Real
from typing import Any

SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0


class PricingValidationError(ValueError):
    """Raised when a pricing request cannot be valued safely."""


@dataclass(frozen=True)
class FairValueRequest:
    """Inputs for one European option valuation.

    Exactly one of ``spot`` or ``forward`` must be supplied.  A spot request
    uses Black-Scholes with ``dividend_yield``; a forward request uses
    Black-76.  ``iv`` and ``risk_free_rate`` are required at runtime even
    though ``None`` defaults make missing-input errors explicit and typed.
    """

    option_type: str
    strike: float
    expiry: datetime
    valuation_time: datetime
    iv: float | None = None
    risk_free_rate: float | None = None
    spot: float | None = None
    forward: float | None = None
    dividend_yield: float = 0.0
    surface: Any | None = None
    prefer_observed_surface: bool = True
    market_price: float | None = None
    market_bid: float | None = None
    market_ask: float | None = None
    market_iv: float | None = None


@dataclass(frozen=True)
class FairValueResult:
    """Fair value, decomposition, and Greeks for one option.

    ``time_value`` is the non-negative premium remaining after subtracting
    spot/forward intrinsic value.  At expiry, model Greeks are zero because
    the mathematical derivatives are discontinuous or undefined there.
    """

    model: str
    status: str
    option_type: str
    fair_price: float
    intrinsic_value: float
    time_value: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    time_to_expiry_years: float
    valuation_time: datetime
    expiry: datetime
    underlying_value: float
    fair_iv: float
    surface_status: str | None
    market_mid: float | None
    iv_edge: float | None
    price_edge: float | None


def price_fair_value(request: FairValueRequest) -> FairValueResult:
    """Price one European call or put using an explicit model input.

    No implied-volatility or risk-free-rate fallback is used.  Invalid inputs
    and non-finite model results raise :class:`PricingValidationError` rather
    than silently returning intrinsic value.
    """

    option_type = _normalise_option_type(request.option_type)
    valuation_time, expiry = _normalise_times(
        request.valuation_time,
        request.expiry,
    )
    _validate_number("strike", request.strike, strictly_positive=True)
    _validate_number("risk_free_rate", request.risk_free_rate)
    _validate_number("dividend_yield", request.dividend_yield)

    if (request.spot is None) == (request.forward is None):
        raise PricingValidationError("exactly one of spot or forward must be supplied")

    if request.spot is not None:
        underlying = _validate_number("spot", request.spot, strictly_positive=True)
        model = "black_scholes"
    else:
        underlying = _validate_number("forward", request.forward, strictly_positive=True)
        if request.dividend_yield != 0.0:
            raise PricingValidationError(
                "dividend_yield must be zero when forward is supplied"
            )
        model = "black_76"

    if expiry < valuation_time and request.iv is not None:
        raise PricingValidationError("expiry must be on or after valuation_time")

    time_to_expiry = max(0.0, (expiry - valuation_time).total_seconds() / SECONDS_PER_YEAR)
    intrinsic = _intrinsic_value(
        underlying,
        request.strike,
        option_type,
        model=model,
        time_to_expiry=time_to_expiry,
        risk_free_rate=request.risk_free_rate,
    )
    market_mid = _market_mid(request)
    market_iv = (
        _validate_number("market_iv", request.market_iv, strictly_positive=True)
        if request.market_iv is not None
        else None
    )

    if time_to_expiry == 0.0:
        # Expired contracts have no time value. Do not require or query an IV
        # surface merely to return their intrinsic settlement value.
        resolved_iv = (
            _validate_number("iv", request.iv, strictly_positive=True)
            if request.iv is not None
            else 0.0
        )
        return FairValueResult(
            model=model,
            status="expired",
            option_type=option_type,
            fair_price=intrinsic,
            intrinsic_value=intrinsic,
            time_value=0.0,
            delta=0.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0,
            time_to_expiry_years=0.0,
            valuation_time=valuation_time,
            expiry=expiry,
            underlying_value=underlying,
            fair_iv=resolved_iv,
                surface_status=None,
            market_mid=market_mid,
            iv_edge=(resolved_iv - market_iv) if market_iv is not None else None,
            price_edge=(intrinsic - market_mid) if market_mid is not None else None,
        )

    surface_status: str | None = None
    if request.iv is None:
        if request.surface is None:
            raise PricingValidationError(
                "iv is required unless a volatility surface is supplied"
            )
        try:
            surface_point = request.surface.quote(
                expiry=expiry,
                strike=request.strike,
                forward=request.forward,
                prefer_observed=request.prefer_observed_surface,
            )
        except Exception as exc:  # surface implementations expose domain errors
            raise PricingValidationError(
                f"unable to resolve fair IV from surface: {exc}"
            ) from exc
        resolved_iv = _validate_number(
            "surface fair_iv", getattr(surface_point, "iv", None), strictly_positive=True
        )
        surface_status = str(getattr(surface_point, "status", "unknown"))
    else:
        resolved_iv = _validate_number("iv", request.iv, strictly_positive=True)

    if model == "black_scholes":
        fair_price, delta, gamma, theta, vega, rho = _black_scholes(
            option_type=option_type,
            spot=underlying,
            strike=request.strike,
            time_to_expiry=time_to_expiry,
            iv=resolved_iv,
            risk_free_rate=request.risk_free_rate,
            dividend_yield=request.dividend_yield,
        )
    else:
        fair_price, delta, gamma, theta, vega, rho = _black_76(
            option_type=option_type,
            forward=underlying,
            strike=request.strike,
            time_to_expiry=time_to_expiry,
            iv=resolved_iv,
            risk_free_rate=request.risk_free_rate,
        )

    values = (fair_price, delta, gamma, theta, vega, rho)
    if not all(isfinite(value) for value in values):
        raise PricingValidationError("pricing calculation returned a non-finite result")
    if fair_price < -1e-12:
        raise PricingValidationError("pricing calculation returned a negative fair price")

    fair_price = max(0.0, fair_price)
    return FairValueResult(
        model=model,
        status="ok",
        option_type=option_type,
        fair_price=fair_price,
        intrinsic_value=intrinsic,
        time_value=max(0.0, fair_price - intrinsic),
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho,
        time_to_expiry_years=time_to_expiry,
        valuation_time=valuation_time,
        expiry=expiry,
        underlying_value=underlying,
        fair_iv=resolved_iv,
        surface_status=surface_status,
        market_mid=market_mid,
        iv_edge=(resolved_iv - market_iv) if market_iv is not None else None,
        price_edge=(fair_price - market_mid) if market_mid is not None else None,
    )


def _black_scholes(
    *,
    option_type: str,
    spot: float,
    strike: float,
    time_to_expiry: float,
    iv: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> tuple[float, float, float, float, float, float]:
    root_t = sqrt(time_to_expiry)
    d1 = (
        log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * iv * iv) * time_to_expiry
    ) / (iv * root_t)
    d2 = d1 - iv * root_t
    discounted_spot = spot * exp(-dividend_yield * time_to_expiry)
    discounted_strike = strike * exp(-risk_free_rate * time_to_expiry)
    nd1 = _normal_cdf(d1)
    nd2 = _normal_cdf(d2)
    pdf_d1 = _normal_pdf(d1)

    if option_type == "call":
        price = discounted_spot * nd1 - discounted_strike * nd2
        delta = exp(-dividend_yield * time_to_expiry) * nd1
        theta_year = (
            -discounted_spot * pdf_d1 * iv / (2.0 * root_t)
            + dividend_yield * discounted_spot * nd1
            - risk_free_rate * discounted_strike * nd2
        )
        rho_rate = time_to_expiry * discounted_strike * nd2
    else:
        price = discounted_strike * _normal_cdf(-d2) - discounted_spot * _normal_cdf(-d1)
        delta = exp(-dividend_yield * time_to_expiry) * (nd1 - 1.0)
        theta_year = (
            -discounted_spot * pdf_d1 * iv / (2.0 * root_t)
            - dividend_yield * discounted_spot * _normal_cdf(-d1)
            + risk_free_rate * discounted_strike * _normal_cdf(-d2)
        )
        rho_rate = -time_to_expiry * discounted_strike * _normal_cdf(-d2)

    gamma = exp(-dividend_yield * time_to_expiry) * pdf_d1 / (spot * iv * root_t)
    vega_per_vol_point = discounted_spot * pdf_d1 * root_t / 100.0
    rho_per_rate_point = rho_rate / 100.0
    theta_per_day = theta_year / 365.0
    return price, delta, gamma, theta_per_day, vega_per_vol_point, rho_per_rate_point


def _black_76(
    *,
    option_type: str,
    forward: float,
    strike: float,
    time_to_expiry: float,
    iv: float,
    risk_free_rate: float,
) -> tuple[float, float, float, float, float, float]:
    root_t = sqrt(time_to_expiry)
    d1 = (log(forward / strike) + 0.5 * iv * iv * time_to_expiry) / (iv * root_t)
    d2 = d1 - iv * root_t
    discount = exp(-risk_free_rate * time_to_expiry)
    nd1 = _normal_cdf(d1)
    nd2 = _normal_cdf(d2)
    pdf_d1 = _normal_pdf(d1)

    if option_type == "call":
        price = discount * (forward * nd1 - strike * nd2)
        delta = discount * nd1
    else:
        price = discount * (strike * _normal_cdf(-d2) - forward * _normal_cdf(-d1))
        delta = -discount * _normal_cdf(-d1)

    gamma = discount * pdf_d1 / (forward * iv * root_t)
    theta_year = risk_free_rate * price - discount * forward * pdf_d1 * iv / (2.0 * root_t)
    vega_per_vol_point = discount * forward * pdf_d1 * root_t / 100.0
    rho_per_rate_point = -time_to_expiry * price / 100.0
    theta_per_day = theta_year / 365.0
    return price, delta, gamma, theta_per_day, vega_per_vol_point, rho_per_rate_point


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return exp(-0.5 * value * value) / sqrt(2.0 * pi)


def _normalise_option_type(option_type: str) -> str:
    if not isinstance(option_type, str):
        raise PricingValidationError("option_type must be call or put")
    normalized = option_type.strip().lower()
    if normalized in {"c", "call"}:
        return "call"
    if normalized in {"p", "put"}:
        return "put"
    raise PricingValidationError("option_type must be call or put")


def _normalise_times(
    valuation_time: datetime,
    expiry: datetime,
) -> tuple[datetime, datetime]:
    if not isinstance(valuation_time, datetime) or not isinstance(expiry, datetime):
        raise PricingValidationError("valuation_time and expiry must be datetime values")
    valuation_is_aware = valuation_time.tzinfo is not None
    expiry_is_aware = expiry.tzinfo is not None
    if valuation_is_aware != expiry_is_aware:
        raise PricingValidationError("valuation_time and expiry must use the same timezone")
    if valuation_is_aware:
        return (
            valuation_time.astimezone(UTC),
            expiry.astimezone(UTC),
        )
    return valuation_time, expiry


def _validate_number(
    name: str,
    value: Real | None,
    *,
    strictly_positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise PricingValidationError(f"{name} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise PricingValidationError(f"{name} must be a finite number")
    if strictly_positive and number <= 0.0:
        raise PricingValidationError(f"{name} must be greater than zero")
    return number


def _market_mid(request: FairValueRequest) -> float | None:
    has_bid = request.market_bid is not None
    has_ask = request.market_ask is not None
    if has_bid != has_ask:
        raise PricingValidationError("market_bid and market_ask must be supplied together")
    if has_bid:
        bid = _validate_number("market_bid", request.market_bid, strictly_positive=True)
        ask = _validate_number("market_ask", request.market_ask, strictly_positive=True)
        if ask < bid:
            raise PricingValidationError("market_ask cannot be below market_bid")
        if request.market_price is not None:
            raise PricingValidationError("use market_price or market_bid/market_ask, not both")
        return (bid + ask) / 2.0
    if request.market_price is None:
        return None
    return _validate_number("market_price", request.market_price, strictly_positive=True)


def _intrinsic_value(
    underlying: float,
    strike: float,
    option_type: str,
    *,
    model: str = "black_scholes",
    time_to_expiry: float = 0.0,
    risk_free_rate: float = 0.0,
) -> float:
    if option_type == "call":
        intrinsic = max(0.0, underlying - strike)
    else:
        intrinsic = max(0.0, strike - underlying)
    if model == "black_76":
        intrinsic *= exp(-risk_free_rate * time_to_expiry)
    return intrinsic


__all__ = [
    "FairValueRequest",
    "FairValueResult",
    "PricingValidationError",
    "price_fair_value",
]
