"""Transparent expiry-payoff decision metrics for option strategies.

The public seam is :func:`calculate_payoff_metrics`.  It accepts the scenario
engine's strategy and execution contracts, builds one expiry P&L curve from
executable opening prices, and estimates distribution-based decision metrics.
The estimates are deliberately labelled as model estimates: without completed
historical outcomes they are not a historical win rate or validated EV.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Literal

from .scenario_engine import ExecutionAssumptions, OptionLeg, StrategyDefinition

MetricStatus = Literal[
    "estimated",
    "model_estimate",
    "historically_validated",
    "unavailable",
    "available",
    "unavailable_insufficient_data",
    "unavailable_unbounded_loss",
    "unavailable_unbounded_profit",
    "unavailable_zero_max_loss",
]

METHODOLOGY = (
    "Risk-neutral lognormal expiry distribution using the stated spot, annualized IV, "
    "risk-free rate, and time to expiry. Payoff uses ask prices for long legs, bid prices "
    "for short legs, and stated opening fees/slippage. EV and win probability are model "
    "estimates because historical outcomes were not supplied."
)


@dataclass(frozen=True)
class PayoffPoint:
    """One chart-ready point on the strategy's expiry P&L line."""

    underlying_price: float
    pnl: float


@dataclass(frozen=True)
class PayoffAssumptions:
    """Inputs and definitions required to interpret payoff decision metrics."""

    valuation_time: datetime | None = None
    expiry_at: datetime | None = None
    spot_price: float | None = None
    annualized_volatility: float | None = None
    risk_free_rate: float | None = None
    time_to_expiry_years: float | None = None
    quantity: float | None = None
    contract_multiplier: float | None = None
    fee_per_contract: float | None = None
    slippage_bps: float | None = None
    net_entry_cash_flow: float | None = None
    distribution: str = "risk_neutral_lognormal"
    entry_price_source: str = "long ask / short bid"
    costs_included: str = "opening_fees_and_slippage"
    win_definition: str = "expiry_pnl_strictly_positive"
    risk_reward_definition: str = "expected_positive_pnl_divided_by_absolute_expected_negative_pnl"
    historical_outcomes_used: bool = False


@dataclass(frozen=True)
class PayoffMetrics:
    """Chart data, payoff bounds, and explicitly qualified decision metrics."""

    payoff_curve: tuple[PayoffPoint, ...]
    expected_value: float | None
    win_probability: float | None
    risk_reward: float | None
    expected_positive_pnl: float | None
    expected_negative_pnl: float | None
    max_loss: float | None
    max_profit: float | None
    breakevens: tuple[float, ...]
    status: MetricStatus
    expected_value_status: MetricStatus
    win_probability_status: MetricStatus
    risk_reward_status: MetricStatus
    methodology: str
    assumptions: PayoffAssumptions | None
    limitations: tuple[str, ...]

    @property
    def metrics_status(self) -> MetricStatus:
        """Compatibility name for consumers that label the aggregate status."""

        return self.status


def calculate_payoff_metrics(
    strategy: StrategyDefinition,
    execution: ExecutionAssumptions | None = None,
    *,
    quantity: float = 1.0,
    model_iv: float | None = None,
    entry_price_source: str = "long ask / short bid",
    curve_points: int = 101,
) -> PayoffMetrics:
    """Return expiry payoff and model-estimated EV, win probability, and RR.

    All legs must describe the same underlying, valuation time, and expiry.
    Calendar strategies therefore return an explicit ``unavailable``
    result rather than pretending that they have a single expiry payoff.
    ``risk_reward`` is expected positive P&L divided by the absolute expected
    negative P&L under the same model distribution.
    """

    execution = execution or ExecutionAssumptions()
    issue = _input_issue(strategy, execution, quantity, model_iv, curve_points)
    if issue is not None:
        return _unavailable(issue)

    legs = strategy.legs
    first = legs[0]
    valuation_time = _as_utc(first.valuation_time)
    expiry = _as_utc(first.expiry)
    time_to_expiry = max(0.0, (expiry - valuation_time).total_seconds() / 31_536_000.0)
    volatility = float(model_iv) if model_iv is not None else _representative_iv(legs)
    scale = float(quantity) * float(execution.contract_multiplier)
    net_debit = _net_debit(legs, execution, scale)
    assumptions = PayoffAssumptions(
        valuation_time=valuation_time,
        expiry_at=expiry,
        spot_price=float(first.spot),
        annualized_volatility=volatility,
        risk_free_rate=float(first.risk_free_rate),
        time_to_expiry_years=time_to_expiry,
        quantity=float(quantity),
        contract_multiplier=float(execution.contract_multiplier),
        fee_per_contract=float(execution.fee_per_contract),
        slippage_bps=float(execution.slippage_bps),
        net_entry_cash_flow=net_debit,
        entry_price_source=entry_price_source,
    )

    payoff = lambda price: _expiry_pnl(price, legs, net_debit, scale)
    breakevens = _breakevens(legs, payoff, scale)
    max_loss, max_profit = _payoff_bounds(legs, payoff, scale)
    curve = _payoff_curve(
        legs,
        payoff,
        breakevens,
        spot=float(first.spot),
        point_count=curve_points,
    )
    expected_value, win_probability, expected_gain, expected_loss = _distribution_metrics(
        legs,
        payoff,
        breakevens,
        spot=float(first.spot),
        volatility=volatility,
        risk_free_rate=float(first.risk_free_rate),
        time_to_expiry=time_to_expiry,
        scale=scale,
    )
    if expected_loss > 1e-12 and math.isfinite(expected_gain) and math.isfinite(expected_loss):
        risk_reward = expected_gain / expected_loss
        risk_reward_status = "available"
    elif math.isinf(max_loss):
        risk_reward = None
        risk_reward_status = "unavailable_unbounded_loss"
    else:
        risk_reward = None
        risk_reward_status = "unavailable_zero_max_loss"

    return PayoffMetrics(
        payoff_curve=curve,
        expected_value=expected_value,
        win_probability=win_probability,
        risk_reward=risk_reward,
        expected_positive_pnl=expected_gain,
        expected_negative_pnl=-expected_loss,
        max_loss=max_loss,
        max_profit=max_profit,
        breakevens=breakevens,
        status="estimated",
        expected_value_status="model_estimate",
        win_probability_status="model_estimate",
        risk_reward_status=risk_reward_status,
        methodology=_methodology(entry_price_source),
        assumptions=assumptions,
        limitations=(
            "These are model estimates, not historical results; no completed outcomes were supplied.",
            "The risk-neutral distribution is a pricing model, not a forecast of realized returns.",
            "Expiry payoff includes opening costs but no early-exit or assignment costs.",
        )
        + (
            (
                "Bid/ask was unavailable; theoretical fair value was used as the model entry price "
                + "and does not represent an executable quote.",
            )
            if entry_price_source == "theoretical_fair_value"
            else ()
        )
        + (
            (
                "Bid/ask was synthesized from mark/fair value and an assumed spread; it is an "
                + "estimated quote and does not represent an executable quote.",
            )
            if entry_price_source == "synthetic_bid_ask"
            else ()
        ),
    )


def _input_issue(
    strategy: StrategyDefinition,
    execution: ExecutionAssumptions,
    quantity: float,
    model_iv: float | None,
    curve_points: int,
) -> str | None:
    if not isinstance(strategy, StrategyDefinition):
        return "strategy must be a StrategyDefinition"
    if not isinstance(execution, ExecutionAssumptions):
        return "execution must be an ExecutionAssumptions"
    if not strategy.legs:
        return "at least one option leg is required"
    if not _positive_finite(quantity):
        return "quantity must be a positive finite number"
    if isinstance(curve_points, bool) or not isinstance(curve_points, int) or curve_points < 2:
        return "curve_points must be an integer of at least 2"
    if model_iv is not None and not _positive_finite(model_iv):
        return "model_iv must be a positive finite number"
    if not _non_negative_finite(execution.fee_per_contract):
        return "fee_per_contract must be a non-negative finite number"
    if not _non_negative_finite(execution.slippage_bps):
        return "slippage_bps must be a non-negative finite number"
    if not _positive_finite(execution.contract_multiplier):
        return "contract_multiplier must be a positive finite number"

    first = strategy.legs[0]
    first_expiry = _as_utc(first.expiry)
    first_valuation = _as_utc(first.valuation_time)
    for leg in strategy.legs:
        if leg.position not in {-1, 1}:
            return "each option leg position must be exactly +1 or -1"
        if leg.option_type.strip().lower() not in {"call", "put", "c", "p"}:
            return f"unsupported option type for {leg.symbol}"
        for value in (leg.strike, leg.spot, leg.iv):
            if not _positive_finite(value):
                return f"{leg.symbol} has incomplete payoff model inputs"
        for value in (leg.bid, leg.ask):
            if not _non_negative_finite(value):
                return f"{leg.symbol} has invalid executable prices"
        if not _finite(leg.risk_free_rate):
            return f"{leg.symbol} has an invalid risk-free rate"
        if _as_utc(leg.expiry) != first_expiry:
            return "mixed-expiry legs do not have one unambiguous expiry payoff"
        if _as_utc(leg.valuation_time) != first_valuation:
            return "all payoff legs must share a valuation time"
        if not math.isclose(float(leg.spot), float(first.spot), rel_tol=1e-9, abs_tol=1e-9):
            return "all payoff legs must share an underlying spot price"
        if not math.isclose(
            float(leg.risk_free_rate),
            float(first.risk_free_rate),
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            return "all payoff legs must share a risk-free rate"
    if first_expiry < first_valuation:
        return "option expiry precedes the valuation time"
    return None


def _unavailable(issue: str) -> PayoffMetrics:
    return PayoffMetrics(
        payoff_curve=(),
        expected_value=None,
        win_probability=None,
        risk_reward=None,
        expected_positive_pnl=None,
        expected_negative_pnl=None,
        max_loss=None,
        max_profit=None,
        breakevens=(),
        status="unavailable",
        expected_value_status="unavailable",
        win_probability_status="unavailable",
        risk_reward_status="unavailable_insufficient_data",
        methodology=f"Payoff decision metrics unavailable: {issue}.",
        assumptions=PayoffAssumptions(),
        limitations=(issue,),
    )


def _methodology(entry_price_source: str) -> str:
    if entry_price_source == "theoretical_fair_value":
        return (
            "Risk-neutral lognormal expiry distribution using the stated spot, annualized IV, "
            "risk-free rate, and time to expiry. Payoff uses theoretical fair value for each "
            "leg plus stated opening fees/slippage as a model estimate; no executable bid/ask "
            "quote was available."
        )
    if entry_price_source == "synthetic_bid_ask":
        return (
            "Risk-neutral lognormal expiry distribution using the stated spot, annualized IV, "
            "risk-free rate, and time to expiry. Payoff uses bid/ask synthesized from mark/fair "
            "value and an assumed spread, plus stated opening fees/slippage; the quote is not "
            "executable."
        )
    return METHODOLOGY


def _representative_iv(legs: tuple[OptionLeg, ...]) -> float:
    ordered = sorted(float(leg.iv) for leg in legs)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _net_debit(
    legs: tuple[OptionLeg, ...],
    execution: ExecutionAssumptions,
    scale: float,
) -> float:
    premium = sum((leg.ask if leg.position > 0 else -leg.bid) * scale for leg in legs)
    fees = execution.fee_per_contract * scale * len(legs)
    slippage = sum(
        (leg.ask if leg.position > 0 else leg.bid) * execution.slippage_bps / 10_000.0 * scale
        for leg in legs
    )
    return premium + fees + slippage


def _expiry_pnl(
    underlying_price: float,
    legs: tuple[OptionLeg, ...],
    net_debit: float,
    scale: float,
) -> float:
    intrinsic = 0.0
    for leg in legs:
        if leg.option_type.strip().lower() in {"call", "c"}:
            leg_intrinsic = max(underlying_price - leg.strike, 0.0)
        else:
            leg_intrinsic = max(leg.strike - underlying_price, 0.0)
        intrinsic += leg.position * leg_intrinsic
    return intrinsic * scale - net_debit


def _breakevens(
    legs: tuple[OptionLeg, ...],
    payoff: Callable[[float], float],
    scale: float,
) -> tuple[float, ...]:
    strikes = sorted({float(leg.strike) for leg in legs})
    boundaries = [0.0, *strikes]
    roots: list[float] = []
    for left, right in pairwise(boundaries):
        left_value = payoff(left)
        right_value = payoff(right)
        if abs(left_value) <= 1e-10:
            roots.append(left)
        if left_value * right_value < 0:
            roots.append(left - left_value * (right - left) / (right_value - left_value))
    last = boundaries[-1]
    last_value = payoff(last)
    if abs(last_value) <= 1e-10:
        roots.append(last)
    tail_slope = _tail_slope(legs, scale)
    if abs(tail_slope) > 1e-12:
        root = last - last_value / tail_slope
        if root > last + 1e-10:
            roots.append(root)
    return tuple(sorted({round(root, 12) for root in roots if root >= 0.0}))


def _payoff_bounds(
    legs: tuple[OptionLeg, ...],
    payoff: Callable[[float], float],
    scale: float,
) -> tuple[float, float]:
    strikes = sorted({float(leg.strike) for leg in legs})
    values = [payoff(0.0), *(payoff(strike) for strike in strikes)]
    tail_slope = _tail_slope(legs, scale)
    max_loss = math.inf if tail_slope < -1e-12 else max(0.0, -min(values))
    max_profit = math.inf if tail_slope > 1e-12 else max(0.0, max(values))
    return max_loss, max_profit


def _tail_slope(legs: tuple[OptionLeg, ...], scale: float) -> float:
    return sum(
        leg.position * scale for leg in legs if leg.option_type.strip().lower() in {"call", "c"}
    )


def _payoff_curve(
    legs: tuple[OptionLeg, ...],
    payoff: Callable[[float], float],
    breakevens: tuple[float, ...],
    *,
    spot: float,
    point_count: int,
) -> tuple[PayoffPoint, ...]:
    strikes = tuple(float(leg.strike) for leg in legs)
    upper = max(spot * 2.0, max(strikes) * 1.5, max(breakevens, default=0.0) * 1.25)
    step = upper / (point_count - 1)
    prices = {index * step for index in range(point_count)}
    prices.update(strikes)
    prices.update(breakevens)
    prices.add(spot)
    return tuple(PayoffPoint(underlying_price=price, pnl=payoff(price)) for price in sorted(prices))


def _distribution_metrics(
    legs: tuple[OptionLeg, ...],
    payoff: Callable[[float], float],
    breakevens: tuple[float, ...],
    *,
    spot: float,
    volatility: float,
    risk_free_rate: float,
    time_to_expiry: float,
    scale: float,
) -> tuple[float, float, float, float]:
    if time_to_expiry == 0.0:
        pnl = payoff(spot)
        return pnl, float(pnl > 0.0), max(pnl, 0.0), max(-pnl, 0.0)

    strikes = {float(leg.strike) for leg in legs}
    finite_boundaries = sorted({0.0, *strikes, *breakevens})
    intervals = [(left, right) for left, right in pairwise(finite_boundaries) if right > left]
    intervals.append((finite_boundaries[-1], math.inf))

    expected_value = 0.0
    win_probability = 0.0
    expected_gain = 0.0
    expected_loss = 0.0
    for lower, upper in intervals:
        sample = (lower + upper) / 2.0 if math.isfinite(upper) else lower + max(spot, lower, 1.0)
        slope = _payoff_slope(sample, legs, scale)
        intercept = payoff(sample) - slope * sample
        probability, first_moment = _lognormal_interval_moments(
            lower,
            upper,
            spot=spot,
            volatility=volatility,
            risk_free_rate=risk_free_rate,
            time_to_expiry=time_to_expiry,
        )
        interval_value = slope * first_moment + intercept * probability
        expected_value += interval_value
        if payoff(sample) > 0.0:
            win_probability += probability
            expected_gain += interval_value
        elif payoff(sample) < 0.0:
            expected_loss -= interval_value
    return expected_value, win_probability, expected_gain, expected_loss


def _payoff_slope(price: float, legs: tuple[OptionLeg, ...], scale: float) -> float:
    slope = 0.0
    for leg in legs:
        option_type = leg.option_type.strip().lower()
        if option_type in {"call", "c"} and price > leg.strike:
            slope += leg.position * scale
        elif option_type in {"put", "p"} and price < leg.strike:
            slope -= leg.position * scale
    return slope


def _lognormal_interval_moments(
    lower: float,
    upper: float,
    *,
    spot: float,
    volatility: float,
    risk_free_rate: float,
    time_to_expiry: float,
) -> tuple[float, float]:
    sigma_t = volatility * math.sqrt(time_to_expiry)
    log_mean = math.log(spot) + (risk_free_rate - 0.5 * volatility**2) * time_to_expiry
    probability = _lognormal_cdf(upper, log_mean, sigma_t) - _lognormal_cdf(
        lower, log_mean, sigma_t
    )
    shifted_probability = _shifted_lognormal_cdf(upper, log_mean, sigma_t) - (
        _shifted_lognormal_cdf(lower, log_mean, sigma_t)
    )
    first_moment = math.exp(log_mean + 0.5 * sigma_t**2) * shifted_probability
    return probability, first_moment


def _lognormal_cdf(value: float, log_mean: float, sigma: float) -> float:
    if value <= 0.0:
        return 0.0
    if math.isinf(value):
        return 1.0
    return _normal_cdf((math.log(value) - log_mean) / sigma)


def _shifted_lognormal_cdf(value: float, log_mean: float, sigma: float) -> float:
    if value <= 0.0:
        return 0.0
    if math.isinf(value):
        return 1.0
    return _normal_cdf((math.log(value) - log_mean - sigma**2) / sigma)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _finite(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _positive_finite(value: object) -> bool:
    return _finite(value) and float(value) > 0.0


def _non_negative_finite(value: object) -> bool:
    return _finite(value) and float(value) >= 0.0


# ``estimate`` is the domain-facing verb used by scanner consumers.  Keep the
# more explicit calculation name as an equivalent interface for direct users.
estimate_payoff_metrics = calculate_payoff_metrics


__all__ = [
    "METHODOLOGY",
    "MetricStatus",
    "PayoffAssumptions",
    "PayoffMetrics",
    "PayoffPoint",
    "calculate_payoff_metrics",
    "estimate_payoff_metrics",
]
