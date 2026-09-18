"""Options Strategy Builder — multi-leg strategy construction and evaluation.

Inspired by open-source projects such as opstrat, OptionLab, and OpenBull.
The public API is:

* ``STRATEGY_TEMPLATES`` — catalog of pre-defined strategy recipes.
* ``evaluate_builder_strategy()`` — compute payoff curve, Greeks, breakevens,
  max profit/loss, probability of profit, and expected value for any multi-leg
  combination.
* ``build_template_legs_from_chain()`` — auto-populate leg inputs from a live
  options chain for a named strategy template.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from options_lib.pricing.fair_value import FairValueRequest, price_fair_value

# ---------------------------------------------------------------------------
# Strategy template catalogue
# ---------------------------------------------------------------------------

STRATEGY_TEMPLATES: dict[str, dict[str, Any]] = {
    "long_call": {
        "name": "Long Call",
        "description": "Unlimited upside, limited risk. Buy a call option.",
        "legs": [{"option_type": "call", "position": 1, "role": "long_strike"}],
        "market_bias": "bullish",
        "max_loss": "premium paid",
        "max_profit": "unlimited",
    },
    "long_put": {
        "name": "Long Put",
        "description": "Unlimited downside profit, limited risk. Buy a put option.",
        "legs": [{"option_type": "put", "position": 1, "role": "long_strike"}],
        "market_bias": "bearish",
        "max_loss": "premium paid",
        "max_profit": "strike - premium (at zero)",
    },
    "covered_call": {
        "name": "Covered Call",
        "description": "Hold underlying, sell OTM call to collect premium.",
        "legs": [{"option_type": "call", "position": -1, "role": "short_strike"}],
        "market_bias": "neutral-bullish",
        "max_loss": "underlying cost - premium",
        "max_profit": "strike - entry + premium",
    },
    "protective_put": {
        "name": "Protective Put",
        "description": "Hold underlying, buy put as downside insurance.",
        "legs": [{"option_type": "put", "position": 1, "role": "long_strike"}],
        "market_bias": "bullish with hedge",
        "max_loss": "entry - strike + premium",
        "max_profit": "unlimited",
    },
    "bull_call_vertical": {
        "name": "Bull Call Spread",
        "description": "Buy lower call, sell upper call. Limited risk, limited reward.",
        "legs": [
            {"option_type": "call", "position": 1, "role": "long_strike"},
            {"option_type": "call", "position": -1, "role": "short_strike"},
        ],
        "market_bias": "bullish",
        "max_loss": "net debit",
        "max_profit": "spread width - net debit",
    },
    "bear_put_vertical": {
        "name": "Bear Put Spread",
        "description": "Buy upper put, sell lower put. Limited risk, limited reward.",
        "legs": [
            {"option_type": "put", "position": 1, "role": "long_strike"},
            {"option_type": "put", "position": -1, "role": "short_strike"},
        ],
        "market_bias": "bearish",
        "max_loss": "net debit",
        "max_profit": "spread width - net debit",
    },
    "bear_call_vertical": {
        "name": "Bear Call Spread",
        "description": "Sell lower call, buy upper call. Collect credit.",
        "legs": [
            {"option_type": "call", "position": -1, "role": "short_strike"},
            {"option_type": "call", "position": 1, "role": "long_strike"},
        ],
        "market_bias": "bearish-neutral",
        "max_loss": "spread width - credit",
        "max_profit": "net credit",
    },
    "bull_put_vertical": {
        "name": "Bull Put Spread",
        "description": "Sell upper put, buy lower put. Collect credit.",
        "legs": [
            {"option_type": "put", "position": -1, "role": "short_strike"},
            {"option_type": "put", "position": 1, "role": "long_strike"},
        ],
        "market_bias": "bullish-neutral",
        "max_loss": "spread width - credit",
        "max_profit": "net credit",
    },
    "iron_condor": {
        "name": "Iron Condor",
        "description": "Sell OTM call spread + sell OTM put spread. Profit in range.",
        "legs": [
            {"option_type": "put", "position": 1, "role": "far_put"},
            {"option_type": "put", "position": -1, "role": "near_put"},
            {"option_type": "call", "position": -1, "role": "near_call"},
            {"option_type": "call", "position": 1, "role": "far_call"},
        ],
        "market_bias": "neutral",
        "max_loss": "spread width - credit",
        "max_profit": "net credit",
    },
    "iron_butterfly": {
        "name": "Iron Butterfly",
        "description": "Sell ATM straddle, buy wings. Max profit at the money.",
        "legs": [
            {"option_type": "put", "position": 1, "role": "put_wing"},
            {"option_type": "put", "position": -1, "role": "atm_put"},
            {"option_type": "call", "position": -1, "role": "atm_call"},
            {"option_type": "call", "position": 1, "role": "call_wing"},
        ],
        "market_bias": "neutral",
        "max_loss": "spread width - credit",
        "max_profit": "net credit",
    },
    "long_straddle": {
        "name": "Long Straddle",
        "description": "Buy ATM call + ATM put. Profit from large move either way.",
        "legs": [
            {"option_type": "call", "position": 1, "role": "atm_call"},
            {"option_type": "put", "position": 1, "role": "atm_put"},
        ],
        "market_bias": "volatile",
        "max_loss": "net debit",
        "max_profit": "unlimited",
    },
    "long_strangle": {
        "name": "Long Strangle",
        "description": "Buy OTM call + OTM put. Cheaper straddle, wider breakevens.",
        "legs": [
            {"option_type": "put", "position": 1, "role": "otm_put"},
            {"option_type": "call", "position": 1, "role": "otm_call"},
        ],
        "market_bias": "volatile",
        "max_loss": "net debit",
        "max_profit": "unlimited",
    },
    "butterfly": {
        "name": "Butterfly",
        "description": "Buy 1 ITM, sell 2 ATM, buy 1 OTM. Profit near ATM.",
        "legs": [
            {"option_type": "call", "position": 1, "role": "lower_strike"},
            {"option_type": "call", "position": -2, "role": "middle_strike"},
            {"option_type": "call", "position": 1, "role": "upper_strike"},
        ],
        "market_bias": "neutral",
        "max_loss": "net debit",
        "max_profit": "spread width - net debit",
    },
    "calendar_spread": {
        "name": "Calendar Spread",
        "description": "Sell near-term, buy far-term at same strike. Theta play.",
        "legs": [
            {"option_type": "call", "position": -1, "role": "near_term"},
            {"option_type": "call", "position": 1, "role": "far_term"},
        ],
        "market_bias": "neutral",
        "max_loss": "net debit",
        "max_profit": "time value difference at expiry",
    },
    "broken_wing_butterfly": {
        "name": "Broken Wing Butterfly",
        "description": "Asymmetric butterfly with no downside risk on one side.",
        "legs": [
            {"option_type": "call", "position": 1, "role": "lower_strike"},
            {"option_type": "call", "position": -2, "role": "middle_strike"},
            {"option_type": "call", "position": 1, "role": "upper_strike"},
        ],
        "market_bias": "directional-neutral",
        "max_loss": "net debit or zero",
        "max_profit": "spread dependent",
    },
    "short_straddle": {
        "name": "Short Straddle",
        "description": "Sell ATM call + ATM put. Profit from low volatility.",
        "legs": [
            {"option_type": "call", "position": -1, "role": "atm_call"},
            {"option_type": "put", "position": -1, "role": "atm_put"},
        ],
        "market_bias": "neutral",
        "max_loss": "unlimited",
        "max_profit": "net credit",
    },
    "short_strangle": {
        "name": "Short Strangle",
        "description": "Sell OTM call + OTM put. Wider range than straddle.",
        "legs": [
            {"option_type": "call", "position": -1, "role": "otm_call"},
            {"option_type": "put", "position": -1, "role": "otm_put"},
        ],
        "market_bias": "neutral",
        "max_loss": "unlimited",
        "max_profit": "net credit",
    },
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BuilderLegInput:
    """One leg of a strategy as submitted by the user/frontend."""

    option_type: Literal["call", "put"]
    strike: float
    expiry: datetime           # UTC-aware
    iv: float                  # decimal (e.g. 0.80 = 80%)
    spot: float
    position: int              # +1 long, -1 short, ±N for ratio spreads
    mid_price: float           # market mid (bid+ask)/2
    bid: float = 0.0
    ask: float = 0.0
    risk_free_rate: float = 0.05
    quantity: int = 1          # number of contracts
    symbol: str = ""


@dataclass
class BuilderEvaluationResult:
    """Full evaluation output for a multi-leg builder strategy."""

    strategy_type: str
    legs: list[dict[str, Any]]

    # Net position cost/credit per unit
    net_premium: float            # positive = debit, negative = credit

    # Payoff at expiry
    payoff_curve: list[dict[str, float]]   # [{spot, pnl}, ...]
    breakevens: list[float]

    # Risk/reward
    max_profit: float | None       # None = unlimited
    max_loss: float | None         # None = unlimited

    # Stats
    probability_of_profit: float   # 0–1
    expected_value: float

    # Aggregate Greeks (sum across legs)
    delta: float
    gamma: float
    theta: float
    vega: float

    # Leg-level fair values
    leg_fair_values: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_type": self.strategy_type,
            "legs": self.legs,
            "net_premium": self.net_premium,
            "payoff_curve": self.payoff_curve,
            "breakevens": self.breakevens,
            "max_profit": self.max_profit,
            "max_loss": self.max_loss,
            "probability_of_profit": self.probability_of_profit,
            "expected_value": self.expected_value,
            "greeks": {
                "delta": self.delta,
                "gamma": self.gamma,
                "theta": self.theta,
                "vega": self.vega,
            },
            "leg_fair_values": self.leg_fair_values,
        }


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------

_PAYOFF_POINTS = 61  # number of spot price points in payoff curve


def _option_payoff_at_expiry(option_type: str, strike: float, spot: float) -> float:
    """Intrinsic value at expiry for a single option (per unit, long)."""
    if option_type == "call":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def _lognormal_cdf(x: float, mu: float, sigma: float) -> float:
    """CDF of lognormal distribution at x."""
    if x <= 0 or sigma <= 0:
        return 0.0
    z = (math.log(x) - mu) / (sigma * math.sqrt(2))
    return 0.5 * (1.0 + math.erf(z))


def _lognormal_pdf(x: float, mu: float, sigma: float) -> float:
    """PDF of lognormal distribution at x."""
    if x <= 0 or sigma <= 0:
        return 0.0
    ln_x = math.log(x)
    return math.exp(-((ln_x - mu) ** 2) / (2 * sigma ** 2)) / (x * sigma * math.sqrt(2 * math.pi))


def evaluate_builder_strategy(
    legs: list[BuilderLegInput],
    strategy_type: str = "custom",
    spot_range_pct: float = 0.30,
    risk_free_rate: float = 0.05,
) -> BuilderEvaluationResult:
    """Evaluate a multi-leg options strategy.

    Parameters
    ----------
    legs:
        List of :class:`BuilderLegInput` describing each leg.
    strategy_type:
        Name used for labelling (e.g. ``"iron_condor"``).
    spot_range_pct:
        How far above/below spot to extend the payoff curve (default 30%).
    risk_free_rate:
        Default risk-free rate if not set per leg.

    Returns
    -------
    :class:`BuilderEvaluationResult`
    """
    if not legs:
        raise ValueError("At least one leg is required")

    spot = legs[0].spot
    now = datetime.now(UTC)

    # -----------------------------------------------------------------------
    # 1. Price each leg with Black-76 / Black-Scholes
    # -----------------------------------------------------------------------
    leg_fair_values: list[dict[str, Any]] = []
    net_premium = 0.0

    delta_sum = gamma_sum = theta_sum = vega_sum = 0.0

    for leg in legs:
        req = FairValueRequest(
            option_type=leg.option_type,
            strike=leg.strike,
            expiry=leg.expiry,
            valuation_time=now,
            iv=leg.iv,
            risk_free_rate=leg.risk_free_rate or risk_free_rate,
            spot=leg.spot,
        )
        try:
            result = price_fair_value(req)
            fair_price = result.fair_price
            d = result.delta * leg.position * leg.quantity
            g = result.gamma * abs(leg.position) * leg.quantity
            t = result.theta * leg.position * leg.quantity
            v = result.vega * leg.position * leg.quantity
        except Exception:
            # Fallback to mid price if pricing fails
            fair_price = leg.mid_price
            d = g = t = v = 0.0

        delta_sum += d
        gamma_sum += g
        theta_sum += t
        vega_sum += v

        # Net premium: debit positive (long pays), credit negative (short receives)
        net_premium += leg.mid_price * leg.position * leg.quantity

        leg_fair_values.append({
            "symbol": leg.symbol,
            "option_type": leg.option_type,
            "strike": leg.strike,
            "position": leg.position,
            "quantity": leg.quantity,
            "mid_price": leg.mid_price,
            "fair_price": fair_price,
            "delta": d,
            "gamma": g,
            "theta": t,
            "vega": v,
        })

    # -----------------------------------------------------------------------
    # 2. Payoff curve at expiry
    # -----------------------------------------------------------------------
    spot_low = spot * (1.0 - spot_range_pct)
    spot_high = spot * (1.0 + spot_range_pct)
    spot_points = [
        spot_low + (spot_high - spot_low) * i / (_PAYOFF_POINTS - 1)
        for i in range(_PAYOFF_POINTS)
    ]

    payoff_curve: list[dict[str, float]] = []
    for s in spot_points:
        pnl = -net_premium  # start with credit received or debit paid
        for leg in legs:
            intrinsic = _option_payoff_at_expiry(leg.option_type, leg.strike, s)
            pnl += intrinsic * leg.position * leg.quantity
        payoff_curve.append({"spot": round(s, 2), "pnl": round(pnl, 6)})

    # -----------------------------------------------------------------------
    # 3. Breakevens (sign changes in payoff curve)
    # -----------------------------------------------------------------------
    breakevens: list[float] = []
    pnls = [p["pnl"] for p in payoff_curve]
    spots = [p["spot"] for p in payoff_curve]
    for i in range(len(pnls) - 1):
        if pnls[i] * pnls[i + 1] < 0:
            # Linear interpolation
            be = spots[i] - pnls[i] * (spots[i + 1] - spots[i]) / (pnls[i + 1] - pnls[i])
            breakevens.append(round(be, 2))

    # -----------------------------------------------------------------------
    # 4. Max profit / max loss from payoff curve
    # -----------------------------------------------------------------------
    max_profit_candidate = max(pnls)
    min_pnl_candidate = min(pnls)

    # Asymptotic slope as spot -> infinity:
    # Each call has slope +1 per position*quantity; puts expire worthless (slope 0).
    call_slope_high = sum(
        leg.position * leg.quantity
        for leg in legs
        if leg.option_type == "call"
    )

    max_profit: float | None = max_profit_candidate
    max_loss: float | None = min_pnl_candidate

    if call_slope_high > 0:
        max_profit = None  # unlimited upside profit (e.g. long call)
    elif call_slope_high < 0:
        max_loss = None   # unlimited upside loss (e.g. short call)

    # -----------------------------------------------------------------------
    # 5. Probability of profit & Expected Value (lognormal model)
    # -----------------------------------------------------------------------
    # Use average IV across legs for the distribution estimate
    avg_iv = sum(leg.iv for leg in legs) / len(legs) if legs else 0.10
    # Time to closest expiry
    min_tte_years = min(
        max((leg.expiry - now).total_seconds() / (365 * 86400), 0.001)
        for leg in legs
    )
    sigma = avg_iv * math.sqrt(min_tte_years)
    mu = math.log(spot) + (risk_free_rate - 0.5 * avg_iv ** 2) * min_tte_years

    # Numerical integration for PoP and EV using payoff curve
    # We resample at finer intervals
    n_ev = 200
    ev_low = spot * 0.01
    ev_high = spot * 3.0
    ev_step = (ev_high - ev_low) / n_ev

    pop_acc = 0.0
    ev_acc = 0.0
    norm_acc = 0.0

    for i in range(n_ev):
        s_lo = ev_low + i * ev_step
        s_mid = s_lo + ev_step / 2
        pdf = _lognormal_pdf(s_mid, mu, sigma)
        pnl = -net_premium
        for leg in legs:
            pnl += _option_payoff_at_expiry(leg.option_type, leg.strike, s_mid) * leg.position * leg.quantity
        weight = pdf * ev_step
        norm_acc += weight
        ev_acc += pnl * weight
        if pnl > 0:
            pop_acc += weight

    probability_of_profit = pop_acc / norm_acc if norm_acc > 0 else 0.5
    expected_value = ev_acc / norm_acc if norm_acc > 0 else 0.0

    # -----------------------------------------------------------------------
    # Build result
    # -----------------------------------------------------------------------
    return BuilderEvaluationResult(
        strategy_type=strategy_type,
        legs=[
            {
                "option_type": leg.option_type,
                "strike": leg.strike,
                "expiry": leg.expiry.isoformat(),
                "iv": leg.iv,
                "spot": leg.spot,
                "position": leg.position,
                "quantity": leg.quantity,
                "mid_price": leg.mid_price,
                "symbol": leg.symbol,
            }
            for leg in legs
        ],
        net_premium=round(net_premium, 6),
        payoff_curve=payoff_curve,
        breakevens=breakevens,
        max_profit=round(max_profit, 6) if max_profit is not None else None,
        max_loss=round(max_loss, 6) if max_loss is not None else None,
        probability_of_profit=round(probability_of_profit, 4),
        expected_value=round(expected_value, 6),
        delta=round(delta_sum, 6),
        gamma=round(gamma_sum, 6),
        theta=round(theta_sum, 6),
        vega=round(vega_sum, 6),
        leg_fair_values=leg_fair_values,
    )


# ---------------------------------------------------------------------------
# Template-to-chain auto-population
# ---------------------------------------------------------------------------

def build_template_legs_from_chain(
    strategy_type: str,
    spot: float,
    contracts: list[dict[str, Any]],
    expiry_filter: str | None = None,
    risk_free_rate: float = 0.05,
) -> list[BuilderLegInput]:
    """Auto-select legs from live chain data for a named strategy template.

    Parameters
    ----------
    strategy_type:
        One of the keys in :data:`STRATEGY_TEMPLATES`.
    spot:
        Current spot price of the underlying.
    contracts:
        List of contract dicts from the options chain, each with keys:
        ``symbol``, ``option_type``, ``strike``, ``expiry`` (ISO string),
        ``iv``, ``bid``, ``ask``.
    expiry_filter:
        Optional ISO date string to filter contracts by expiry.
    risk_free_rate:
        Risk-free rate for pricing.

    Returns
    -------
    list of :class:`BuilderLegInput`
    """
    template = STRATEGY_TEMPLATES.get(strategy_type)
    if template is None:
        raise ValueError(f"Unknown strategy type: {strategy_type!r}")

    # Filter by expiry if requested
    if expiry_filter:
        filtered = [c for c in contracts if c.get("expiry", "").startswith(expiry_filter[:10])]
        if filtered:
            contracts = filtered

    # Group by expiry — pick nearest expiry with sufficient contracts
    by_expiry: dict[str, list[dict[str, Any]]] = {}
    for c in contracts:
        exp = c.get("expiry", "")[:10]
        by_expiry.setdefault(exp, []).append(c)

    # Sort expiries and pick the first with enough contracts
    sorted_expiries = sorted(by_expiry.keys())
    chain = []
    for exp in sorted_expiries:
        if len(by_expiry[exp]) >= len(template["legs"]):
            chain = by_expiry[exp]
            break
    if not chain:
        chain = contracts  # fallback to all

    # Sort by strike distance from spot
    calls = sorted([c for c in chain if c.get("option_type") == "call"], key=lambda c: abs(c["strike"] - spot))
    puts = sorted([c for c in chain if c.get("option_type") == "put"], key=lambda c: abs(c["strike"] - spot))

    def _nearest_call(rank: int = 0) -> dict[str, Any] | None:
        return calls[rank] if rank < len(calls) else None

    def _nearest_put(rank: int = 0) -> dict[str, Any] | None:
        return puts[rank] if rank < len(puts) else None

    def _to_leg(c: dict[str, Any], position: int) -> BuilderLegInput:
        bid = float(c.get("bid", 0) or 0)
        ask = float(c.get("ask", 0) or 0)
        mid = (bid + ask) / 2 if (bid + ask) > 0 else float(c.get("mark_price", 0) or 0)
        expiry_str = c.get("expiry", "")
        try:
            if "T" in expiry_str:
                expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            else:
                expiry_dt = datetime.fromisoformat(f"{expiry_str}T08:00:00+00:00")
        except ValueError:
            expiry_dt = datetime.now(UTC)
        return BuilderLegInput(
            option_type=c["option_type"],
            strike=float(c["strike"]),
            expiry=expiry_dt,
            iv=float(c.get("iv", 0.80) or 0.80),
            spot=spot,
            position=position,
            mid_price=mid,
            bid=bid,
            ask=ask,
            risk_free_rate=risk_free_rate,
            symbol=c.get("symbol", ""),
        )

    # Strategy-specific leg selection logic
    strategy_leg_selector: dict[str, list[BuilderLegInput]] = {
        "long_call": lambda: [_to_leg(c, 1) for c in [_nearest_call(1)] if c],
        "long_put": lambda: [_to_leg(c, 1) for c in [_nearest_put(1)] if c],
        "covered_call": lambda: [_to_leg(c, -1) for c in [_nearest_call(1)] if c],
        "protective_put": lambda: [_to_leg(c, 1) for c in [_nearest_put(1)] if c],
        "bull_call_vertical": lambda: [
            _to_leg(c, pos) for c, pos in [(_nearest_call(0), 1), (_nearest_call(1), -1)] if c
        ],
        "bear_put_vertical": lambda: [
            _to_leg(c, pos) for c, pos in [(_nearest_put(0), 1), (_nearest_put(1), -1)] if c
        ],
        "bear_call_vertical": lambda: [
            _to_leg(c, pos) for c, pos in [(_nearest_call(0), -1), (_nearest_call(1), 1)] if c
        ],
        "bull_put_vertical": lambda: [
            _to_leg(c, pos) for c, pos in [(_nearest_put(0), -1), (_nearest_put(1), 1)] if c
        ],
        "iron_condor": lambda: [
            _to_leg(c, pos)
            for c, pos in [
                (_nearest_put(2), 1), (_nearest_put(1), -1),
                (_nearest_call(1), -1), (_nearest_call(2), 1),
            ] if c
        ],
        "iron_butterfly": lambda: [
            _to_leg(c, pos)
            for c, pos in [
                (_nearest_put(1), 1), (_nearest_put(0), -1),
                (_nearest_call(0), -1), (_nearest_call(1), 1),
            ] if c
        ],
        "long_straddle": lambda: [
            _to_leg(c, 1)
            for c in [_nearest_call(0), _nearest_put(0)] if c
        ],
        "long_strangle": lambda: [
            _to_leg(c, 1)
            for c in [_nearest_put(1), _nearest_call(1)] if c
        ],
        "short_straddle": lambda: [
            _to_leg(c, -1)
            for c in [_nearest_call(0), _nearest_put(0)] if c
        ],
        "short_strangle": lambda: [
            _to_leg(c, -1)
            for c in [_nearest_call(1), _nearest_put(1)] if c
        ],
        "butterfly": lambda: [
            _to_leg(c, pos)
            for c, pos in [
                (_nearest_call(1), 1), (_nearest_call(0), -2), (_nearest_call(2), 1)
            ] if c
        ],
        "calendar_spread": lambda: [],  # requires different expiries — not auto-populated
        "broken_wing_butterfly": lambda: [
            _to_leg(c, pos)
            for c, pos in [
                (_nearest_call(0), 1), (_nearest_call(1), -2), (_nearest_call(3), 1)
            ] if c
        ],
    }

    selector = strategy_leg_selector.get(strategy_type)
    if selector is None:
        # Generic fallback: one ATM call long
        atm = _nearest_call(0)
        return [_to_leg(atm, 1)] if atm else []

    return selector()


__all__ = [
    "STRATEGY_TEMPLATES",
    "BuilderLegInput",
    "BuilderEvaluationResult",
    "evaluate_builder_strategy",
    "build_template_legs_from_chain",
]

