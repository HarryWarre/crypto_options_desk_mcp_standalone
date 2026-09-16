"""Defined-risk option strategy scenario and P&L evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from .pricing import FairValueRequest, PricingValidationError, price_fair_value


class ScenarioValidationError(ValueError):
    """Raised when a strategy or scenario cannot be valued safely."""


@dataclass(frozen=True)
class OptionLeg:
    symbol: str
    option_type: str
    strike: float
    expiry: datetime
    valuation_time: datetime
    spot: float
    iv: float
    risk_free_rate: float
    bid: float
    ask: float
    position: int = 1
    surface: Any | None = None


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_type: Literal[
        "long_call",
        "long_put",
        "call_vertical",
        "put_vertical",
        "bull_call_vertical",
        "bear_call_vertical",
        "bull_put_vertical",
        "bear_put_vertical",
        "iron_condor",
        "iron_butterfly",
        "long_straddle",
        "long_strangle",
        "protective_put",
        "covered_call",
        "calendar_spread",
        "butterfly",
        "broken_wing_butterfly",
    ]
    legs: tuple[OptionLeg, ...]


@dataclass(frozen=True)
class MarketScenario:
    name: str
    underlying_move_pct: float = 0.0
    iv_move: float = 0.0
    elapsed_days: float = 0.0


@dataclass(frozen=True)
class ExecutionAssumptions:
    fee_per_contract: float = 0.0
    slippage_bps: float = 0.0
    contract_multiplier: float = 1.0
    exit_price_source: Literal["model", "bid_ask"] = "model"


@dataclass(frozen=True)
class ScenarioSet:
    scenarios: tuple[MarketScenario, ...]
    execution: ExecutionAssumptions = ExecutionAssumptions()


@dataclass(frozen=True)
class ScenarioWarning:
    code: str
    message: str
    symbol: str | None = None


@dataclass(frozen=True)
class ScenarioGreeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    underlying_price: float
    implied_volatility: float
    elapsed_days: float
    pnl: float
    greeks: ScenarioGreeks
    status: str
    warnings: tuple[ScenarioWarning, ...]


@dataclass(frozen=True)
class ScenarioReport:
    status: str
    scenarios: tuple[ScenarioResult, ...]
    aggregate_greeks: ScenarioGreeks
    max_loss: float
    max_profit: float
    breakevens: tuple[float, ...]
    warnings: tuple[ScenarioWarning, ...]


def evaluate_scenarios(
    strategy: StrategyDefinition,
    scenario_set: ScenarioSet,
) -> ScenarioReport:
    """Evaluate a supported option strategy over the supplied market scenarios."""

    _validate_execution(scenario_set.execution)
    _validate_strategy(strategy)
    if not scenario_set.scenarios:
        raise ScenarioValidationError("at least one market scenario is required")

    warnings: list[ScenarioWarning] = []
    for leg in strategy.legs:
        if leg.surface is None:
            warnings.append(
                ScenarioWarning("model_only", "No volatility surface was supplied", leg.symbol)
            )
    if scenario_set.execution.fee_per_contract or scenario_set.execution.slippage_bps:
        warnings.append(
            ScenarioWarning(
                "execution_costs",
                "P&L includes fees and bid-ask slippage assumptions",
            )
        )

    max_loss, max_profit, breakevens = _payoff_bounds(strategy, scenario_set.execution)
    results: list[ScenarioResult] = []
    for scenario in scenario_set.scenarios:
        result, scenario_warnings = _evaluate_one(strategy, scenario, scenario_set.execution)
        results.append(result)
        warnings.extend(scenario_warnings)

    if any(warning.code == "surface_extrapolated" for warning in warnings):
        status = "extrapolated"
    elif any(warning.code == "model_only" for warning in warnings):
        status = "model_only"
    else:
        status = "ok"
    aggregate = results[0].greeks
    return ScenarioReport(
        status=status,
        scenarios=tuple(results),
        aggregate_greeks=aggregate,
        max_loss=max_loss,
        max_profit=max_profit,
        breakevens=breakevens,
        warnings=tuple(_dedupe_warnings(warnings)),
    )


def _evaluate_one(
    strategy: StrategyDefinition,
    scenario: MarketScenario,
    execution: ExecutionAssumptions,
) -> tuple[ScenarioResult, list[ScenarioWarning]]:
    _finite_non_negative("elapsed_days", scenario.elapsed_days)
    _finite("underlying_move_pct", scenario.underlying_move_pct)
    _finite("iv_move", scenario.iv_move)
    if scenario.elapsed_days < 0:
        raise ScenarioValidationError("elapsed_days cannot be negative")

    warnings: list[ScenarioWarning] = []
    pnl = 0.0
    delta = gamma = theta = vega = rho = 0.0
    first_spot = strategy.legs[0].spot * (1.0 + scenario.underlying_move_pct / 100.0)
    if first_spot <= 0:
        raise ScenarioValidationError("scenario produces a non-positive underlying price")
    first_iv = strategy.legs[0].iv + scenario.iv_move
    if first_iv <= 0:
        raise ScenarioValidationError("scenario produces a non-positive implied volatility")

    for leg in strategy.legs:
        spot = leg.spot * (1.0 + scenario.underlying_move_pct / 100.0)
        iv = leg.iv + scenario.iv_move
        if spot <= 0 or iv <= 0:
            raise ScenarioValidationError("scenario produces invalid spot or implied volatility")
        valuation_time = leg.valuation_time + timedelta(days=scenario.elapsed_days)
        fair_iv = iv
        leg_warnings: list[ScenarioWarning] = []
        if leg.surface is not None and leg.expiry > valuation_time:
            try:
                point = leg.surface.quote(
                    expiry=leg.expiry,
                    strike=leg.strike,
                    forward=spot,
                    allow_extrapolation=True,
                )
                fair_iv = point.iv + scenario.iv_move
                if point.status == "extrapolated":
                    warning = ScenarioWarning(
                        "surface_extrapolated",
                        "Scenario uses an IV outside the observed surface range",
                        leg.symbol,
                    )
                    leg_warnings.append(warning)
            except Exception as exc:  # surface errors become explicit scenario warnings
                raise ScenarioValidationError(
                    f"unable to value {leg.symbol} from surface: {exc}"
                ) from exc
        elif leg.surface is not None:
            leg_warnings.append(
                ScenarioWarning(
                    "surface_not_used_expired",
                    "Expired scenario uses intrinsic value; volatility surface is not queried",
                    leg.symbol,
                )
            )
        request = FairValueRequest(
            option_type=leg.option_type,
            strike=leg.strike,
            expiry=leg.expiry,
            valuation_time=valuation_time,
            spot=spot,
            iv=fair_iv,
            risk_free_rate=leg.risk_free_rate,
        )
        try:
            valued = price_fair_value(request)
        except PricingValidationError as exc:
            raise ScenarioValidationError(str(exc)) from exc
        entry = leg.ask if leg.position > 0 else leg.bid
        entry_cost = _entry_cost(leg, execution)
        exit_price = valued.fair_price
        if execution.exit_price_source == "bid_ask":
            exit_price = leg.bid if leg.position > 0 else leg.ask
        exit_cost = _exit_cost(leg, exit_price, execution)
        pnl += leg.position * (exit_price - entry) * execution.contract_multiplier
        pnl -= entry_cost + exit_cost
        delta += leg.position * valued.delta * execution.contract_multiplier
        gamma += leg.position * valued.gamma * execution.contract_multiplier
        theta += leg.position * valued.theta * execution.contract_multiplier
        vega += leg.position * valued.vega * execution.contract_multiplier
        rho += leg.position * valued.rho * execution.contract_multiplier
        warnings.extend(leg_warnings)

    return (
        ScenarioResult(
            name=scenario.name,
            underlying_price=first_spot,
            implied_volatility=first_iv,
            elapsed_days=scenario.elapsed_days,
            pnl=pnl,
            greeks=ScenarioGreeks(delta, gamma, theta, vega, rho),
            status="extrapolated"
            if any(w.code == "surface_extrapolated" for w in warnings)
            else "ok",
            warnings=tuple(warnings),
        ),
        warnings,
    )


def _payoff_bounds(
    strategy: StrategyDefinition,
    execution: ExecutionAssumptions,
) -> tuple[float, float, tuple[float, ...]]:
    scale = execution.contract_multiplier
    legs = strategy.legs
    entry_cost = sum((leg.ask if leg.position > 0 else -leg.bid) * scale for leg in legs)
    entry_fees = sum(execution.fee_per_contract * execution.contract_multiplier for _ in legs)
    entry_slippage = sum(
        abs(leg.ask if leg.position > 0 else leg.bid) * execution.slippage_bps / 10_000.0 * scale
        for leg in legs
    )
    net_debit = entry_cost + entry_fees + entry_slippage

    if strategy.strategy_type in {
        "call_vertical",
        "put_vertical",
        "bull_call_vertical",
        "bear_call_vertical",
        "bull_put_vertical",
        "bear_put_vertical",
    }:
        long_leg = next(leg for leg in legs if leg.position > 0)
        short_leg = next(leg for leg in legs if leg.position < 0)
        width = abs(long_leg.strike - short_leg.strike) * scale
        is_call_vertical = "call" in strategy.strategy_type
        if is_call_vertical:
            debit_orientation = strategy.strategy_type in {
                "call_vertical",
                "bull_call_vertical",
            }
            is_debit_vertical = (
                long_leg.strike < short_leg.strike
                if debit_orientation
                else long_leg.strike > short_leg.strike
            )
        else:
            debit_orientation = strategy.strategy_type in {
                "put_vertical",
                "bear_put_vertical",
            }
            is_debit_vertical = (
                long_leg.strike > short_leg.strike
                if debit_orientation
                else long_leg.strike < short_leg.strike
            )
        if is_debit_vertical:
            if execution.fee_per_contract == 0 and execution.slippage_bps == 0:
                max_loss = max(0.0, entry_cost)
            else:
                # Conservative operational bound: a long leg may be paid in full
                # while the short-leg credit is unavailable during a stressed exit.
                max_loss = long_leg.ask * scale + entry_fees + entry_slippage
            max_profit = max(0.0, width - net_debit)
        else:
            # Reverse-orientation verticals are credit spreads. Their loss is the
            # strike width less the opening credit, while the credit is the
            # maximum profit after opening costs.
            max_loss = max(0.0, width + net_debit)
            max_profit = max(0.0, -net_debit)

        if is_call_vertical:
            if long_leg.strike < short_leg.strike:
                breakeven = long_leg.strike + net_debit / scale
            else:
                breakeven = short_leg.strike - net_debit / scale
        else:
            if long_leg.strike > short_leg.strike:
                breakeven = long_leg.strike - net_debit / scale
            else:
                breakeven = short_leg.strike + net_debit / scale
        breakevens = (breakeven,)
        return max_loss, max_profit, breakevens

    if strategy.strategy_type in {"long_straddle", "long_strangle"}:
        premium = net_debit / scale
        put_leg = next(leg for leg in legs if leg.option_type.lower() in {"put", "p"})
        call_leg = next(leg for leg in legs if leg.option_type.lower() in {"call", "c"})
        return (
            max(0.0, net_debit),
            math.inf,
            (put_leg.strike - premium, call_leg.strike + premium),
        )

    if strategy.strategy_type == "calendar_spread":
        return max(0.0, net_debit), math.inf, ()

    if strategy.strategy_type in {"protective_put", "covered_call"}:
        # The underlying position is implicit for overlay strategies.  The
        # scenario engine therefore reports the option overlay's entry risk
        # and does not invent a stock cost basis or quantity.
        if strategy.strategy_type == "protective_put":
            return max(0.0, net_debit), math.inf, ()
        return math.inf, max(0.0, -net_debit), ()

    if strategy.strategy_type in {
        "iron_condor",
        "iron_butterfly",
        "butterfly",
        "broken_wing_butterfly",
    }:
        return _multi_leg_payoff_bounds(strategy, execution)

    leg = legs[0]
    max_loss = max(0.0, net_debit)
    premium = net_debit / scale
    if leg.option_type.lower() in {"call", "c"}:
        max_profit = math.inf
        breakevens = (leg.strike + premium,)
    else:
        max_profit = max(0.0, leg.strike - premium) * scale
        breakevens = (leg.strike - premium,)
    return max_loss, max_profit, breakevens


def _validate_strategy(strategy: StrategyDefinition) -> None:
    if not strategy.legs:
        raise ScenarioValidationError("strategy must contain at least one leg")
    for leg in strategy.legs:
        _validate_leg(leg)
    if strategy.strategy_type in {"long_call", "long_put"}:
        if len(strategy.legs) != 1 or strategy.legs[0].position != 1:
            raise ScenarioValidationError("single-leg strategy must contain one long leg")
        expected = "call" if strategy.strategy_type == "long_call" else "put"
        if strategy.legs[0].option_type.lower() not in {expected, expected[0]}:
            raise ScenarioValidationError("strategy option type does not match its name")
        return
    if strategy.strategy_type in {"long_straddle", "long_strangle"}:
        _validate_long_volatility_strategy(strategy)
        return
    if strategy.strategy_type in {"protective_put", "covered_call"}:
        _validate_overlay_strategy(strategy)
        return
    if strategy.strategy_type == "calendar_spread":
        _validate_calendar_spread(strategy)
        return
    if strategy.strategy_type in {"butterfly", "broken_wing_butterfly"}:
        _validate_butterfly(strategy)
        return
    vertical_strategies = {
        "call_vertical",
        "put_vertical",
        "bull_call_vertical",
        "bear_call_vertical",
        "bull_put_vertical",
        "bear_put_vertical",
    }
    if strategy.strategy_type not in vertical_strategies or len(strategy.legs) != 2:
        if strategy.strategy_type in {"iron_condor", "iron_butterfly"}:
            _validate_iron_strategy(strategy)
            return
        raise ScenarioValidationError(
            "only long single legs and defined-risk verticals are supported"
        )
    long_leg = tuple(leg for leg in strategy.legs if leg.position > 0)
    short_leg = tuple(leg for leg in strategy.legs if leg.position < 0)
    if len(long_leg) != 1 or len(short_leg) != 1:
        raise ScenarioValidationError("vertical must contain one long and one short leg")
    long_leg, short_leg = long_leg[0], short_leg[0]
    expected = "call" if "call" in strategy.strategy_type else "put"
    if any(leg.option_type.lower() not in {expected, expected[0]} for leg in strategy.legs):
        raise ScenarioValidationError("vertical option type does not match its name")
    if long_leg.expiry != short_leg.expiry:
        raise ScenarioValidationError("vertical legs must share an expiry")
    if long_leg.strike == short_leg.strike:
        raise ScenarioValidationError("vertical legs must use distinct strikes")
    # The generic API identifiers are intentionally orientation-neutral so a
    # caller can model either a debit or a credit spread.  Directional
    # identifiers below retain their stricter strike orientation checks.
    if strategy.strategy_type in {"call_vertical", "put_vertical"}:
        return
    debit_orientation = strategy.strategy_type in {
        "call_vertical",
        "bull_call_vertical",
        "put_vertical",
        "bear_put_vertical",
    }
    if "call" in strategy.strategy_type:
        expected_orientation = (
            long_leg.strike < short_leg.strike
            if debit_orientation
            else long_leg.strike > short_leg.strike
        )
        if not expected_orientation:
            raise ScenarioValidationError("call vertical legs have the wrong strike orientation")
    else:
        expected_orientation = (
            long_leg.strike > short_leg.strike
            if debit_orientation
            else long_leg.strike < short_leg.strike
        )
        if not expected_orientation:
            raise ScenarioValidationError("put vertical legs have the wrong strike orientation")


def _validate_long_volatility_strategy(strategy: StrategyDefinition) -> None:
    if len(strategy.legs) != 2 or any(leg.position != 1 for leg in strategy.legs):
        raise ScenarioValidationError("long volatility strategy must contain two long legs")
    puts = tuple(leg for leg in strategy.legs if leg.option_type.lower() in {"put", "p"})
    calls = tuple(leg for leg in strategy.legs if leg.option_type.lower() in {"call", "c"})
    if len(puts) != 1 or len(calls) != 1:
        raise ScenarioValidationError("long volatility strategy must contain one put and one call")
    put_leg, call_leg = puts[0], calls[0]
    if put_leg.expiry != call_leg.expiry:
        raise ScenarioValidationError("long volatility legs must share an expiry")
    if strategy.strategy_type == "long_straddle" and put_leg.strike != call_leg.strike:
        raise ScenarioValidationError("straddle legs must share a strike")
    if strategy.strategy_type == "long_strangle" and put_leg.strike >= call_leg.strike:
        raise ScenarioValidationError("strangle put strike must be below call strike")


def _validate_overlay_strategy(strategy: StrategyDefinition) -> None:
    if len(strategy.legs) != 1:
        raise ScenarioValidationError("overlay strategy must contain one option leg")
    leg = strategy.legs[0]
    expected_type = "put" if strategy.strategy_type == "protective_put" else "call"
    expected_position = 1 if strategy.strategy_type == "protective_put" else -1
    if leg.position != expected_position:
        position_name = "long" if expected_position > 0 else "short"
        raise ScenarioValidationError(
            f"{strategy.strategy_type} must contain one {position_name} {expected_type} leg"
        )
    if leg.option_type.lower().strip() not in {expected_type, expected_type[0]}:
        raise ScenarioValidationError("overlay strategy option type does not match its name")


def _validate_calendar_spread(strategy: StrategyDefinition) -> None:
    if len(strategy.legs) != 2:
        raise ScenarioValidationError("calendar spread must contain two legs")
    long_legs = tuple(leg for leg in strategy.legs if leg.position == 1)
    short_legs = tuple(leg for leg in strategy.legs if leg.position == -1)
    if len(long_legs) != 1 or len(short_legs) != 1:
        raise ScenarioValidationError("calendar spread must contain one long and one short leg")
    long_leg, short_leg = long_legs[0], short_legs[0]
    if long_leg.option_type.lower() != short_leg.option_type.lower():
        raise ScenarioValidationError("calendar spread legs must use the same option type")
    if long_leg.strike != short_leg.strike:
        raise ScenarioValidationError("calendar spread legs must use the same strike")
    if long_leg.expiry <= short_leg.expiry:
        raise ScenarioValidationError("calendar spread long leg must have the later expiry")


def _validate_butterfly(strategy: StrategyDefinition) -> None:
    if len(strategy.legs) != 4:
        raise ScenarioValidationError("butterfly must contain four legs")
    if any(leg.expiry != strategy.legs[0].expiry for leg in strategy.legs):
        raise ScenarioValidationError("butterfly legs must share an expiry")
    if len({leg.option_type.lower() for leg in strategy.legs}) != 1:
        raise ScenarioValidationError("butterfly legs must use the same option type")
    long_legs = tuple(leg for leg in strategy.legs if leg.position == 1)
    short_legs = tuple(leg for leg in strategy.legs if leg.position == -1)
    if len(long_legs) != 2 or len(short_legs) != 2:
        raise ScenarioValidationError("butterfly must contain two long and two short legs")
    body_strikes = {leg.strike for leg in short_legs}
    wing_strikes = sorted(leg.strike for leg in long_legs)
    if len(body_strikes) != 1 or len(wing_strikes) != 2:
        raise ScenarioValidationError("butterfly must have two distinct wings and one body")
    body_strike = next(iter(body_strikes))
    lower_wing, upper_wing = wing_strikes
    if not lower_wing < body_strike < upper_wing:
        raise ScenarioValidationError("butterfly wings must surround the body strike")
    if (
        strategy.strategy_type == "butterfly"
        and body_strike - lower_wing != upper_wing - body_strike
    ):
        raise ScenarioValidationError("butterfly wings must be equally spaced")
    if (
        strategy.strategy_type == "broken_wing_butterfly"
        and body_strike - lower_wing == upper_wing - body_strike
    ):
        raise ScenarioValidationError("broken-wing butterfly wings must be unevenly spaced")


def _validate_iron_strategy(strategy: StrategyDefinition) -> None:
    if len(strategy.legs) != 4:
        raise ScenarioValidationError("iron strategy must contain four legs")
    long_legs = tuple(leg for leg in strategy.legs if leg.position > 0)
    short_legs = tuple(leg for leg in strategy.legs if leg.position < 0)
    if len(long_legs) != 2 or len(short_legs) != 2:
        raise ScenarioValidationError("iron strategy must contain two long and two short legs")
    if any(leg.expiry != strategy.legs[0].expiry for leg in strategy.legs):
        raise ScenarioValidationError("iron strategy legs must share an expiry")
    puts = tuple(leg for leg in strategy.legs if leg.option_type.lower() in {"put", "p"})
    calls = tuple(leg for leg in strategy.legs if leg.option_type.lower() in {"call", "c"})
    if len(puts) != 2 or len(calls) != 2:
        raise ScenarioValidationError("iron strategy must contain two puts and two calls")
    if strategy.strategy_type == "iron_condor":
        ordered = tuple(sorted(strategy.legs, key=lambda leg: (leg.strike, leg.option_type)))
        if not (
            ordered[0].option_type.lower() in {"put", "p"}
            and ordered[1].option_type.lower() in {"put", "p"}
            and ordered[2].option_type.lower() in {"call", "c"}
            and ordered[3].option_type.lower() in {"call", "c"}
            and ordered[0].position == 1
            and ordered[1].position == -1
            and ordered[2].position == -1
            and ordered[3].position == 1
            and ordered[0].strike < ordered[1].strike < ordered[2].strike < ordered[3].strike
        ):
            raise ScenarioValidationError(
                "iron condor legs must be ordered wing/short put/short call/wing"
            )
        return
    body_strikes = {leg.strike for leg in strategy.legs if leg.position < 0}
    if len(body_strikes) != 1:
        raise ScenarioValidationError("iron butterfly short bodies must share a strike")
    body_strike = next(iter(body_strikes))
    lower_wing = next((leg for leg in long_legs if leg.option_type.lower() in {"put", "p"}), None)
    upper_wing = next((leg for leg in long_legs if leg.option_type.lower() in {"call", "c"}), None)
    if (
        lower_wing is None
        or upper_wing is None
        or lower_wing.strike >= body_strike
        or upper_wing.strike <= body_strike
    ):
        raise ScenarioValidationError("iron butterfly needs a lower put wing and upper call wing")


def _multi_leg_payoff_bounds(
    strategy: StrategyDefinition,
    execution: ExecutionAssumptions,
) -> tuple[float, float, tuple[float, ...]]:
    scale = execution.contract_multiplier
    legs = strategy.legs
    entry_cost = sum((leg.ask if leg.position > 0 else -leg.bid) * scale for leg in legs)
    entry_fees = execution.fee_per_contract * len(legs) * scale
    entry_slippage = sum(
        abs(leg.ask if leg.position > 0 else leg.bid) * execution.slippage_bps / 10_000.0 * scale
        for leg in legs
    )
    net_debit = entry_cost + entry_fees + entry_slippage
    strikes = sorted({leg.strike for leg in legs})
    width = max(strikes[-1] - strikes[0], 1.0)
    points = [0.0, *strikes, strikes[-1] + width * 2.0]
    values = tuple(_multi_leg_expiry_pnl(price, legs, net_debit, scale) for price in points)
    breakevens: list[float] = []
    for left, right, left_value, right_value in zip(points, points[1:], values, values[1:]):
        if left_value == 0:
            breakevens.append(left)
        if left_value * right_value < 0 and right_value != left_value:
            breakevens.append(left - left_value * (right - left) / (right_value - left_value))
    unique_breakevens = tuple(sorted({round(value, 12) for value in breakevens}))
    return max(0.0, -min(values)), max(0.0, max(values)), unique_breakevens


def _multi_leg_expiry_pnl(
    price: float,
    legs: tuple[OptionLeg, ...],
    net_debit: float,
    scale: float,
) -> float:
    intrinsic = 0.0
    for leg in legs:
        option_type = leg.option_type.lower()
        if option_type in {"call", "c"}:
            intrinsic += leg.position * max(price - leg.strike, 0.0)
        else:
            intrinsic += leg.position * max(leg.strike - price, 0.0)
    return intrinsic * scale - net_debit


def _validate_execution(execution: ExecutionAssumptions) -> None:
    for name, value in (
        ("fee_per_contract", execution.fee_per_contract),
        ("slippage_bps", execution.slippage_bps),
        ("contract_multiplier", execution.contract_multiplier),
    ):
        _finite(name, value)
        if value < 0 or (name == "contract_multiplier" and value <= 0):
            raise ScenarioValidationError(f"{name} is invalid")
    if execution.exit_price_source not in {"model", "bid_ask"}:
        raise ScenarioValidationError("unsupported exit price source")


def _validate_leg(leg: OptionLeg) -> None:
    option_type = leg.option_type.lower().strip()
    if option_type not in {"call", "put", "c", "p"}:
        raise ScenarioValidationError(f"unsupported option type for {leg.symbol}")
    if (
        not isinstance(leg.position, int)
        or isinstance(leg.position, bool)
        or leg.position not in {-1, 1}
    ):
        raise ScenarioValidationError("each leg position must be exactly +1 or -1")
    for name, value in (
        ("strike", leg.strike),
        ("spot", leg.spot),
        ("iv", leg.iv),
        ("risk_free_rate", leg.risk_free_rate),
        ("bid", leg.bid),
        ("ask", leg.ask),
    ):
        _finite(name, value)
    if leg.strike <= 0 or leg.spot <= 0 or leg.iv <= 0:
        raise ScenarioValidationError(f"{leg.symbol} has invalid pricing inputs")
    if leg.bid < 0 or leg.ask < 0 or leg.ask < leg.bid:
        raise ScenarioValidationError(f"{leg.symbol} has invalid bid/ask")
    if leg.expiry < leg.valuation_time:
        raise ScenarioValidationError(f"{leg.symbol} expires before valuation time")


def _entry_cost(leg: OptionLeg, execution: ExecutionAssumptions) -> float:
    return (
        execution.fee_per_contract * execution.contract_multiplier
        + abs(leg.ask if leg.position > 0 else leg.bid)
        * execution.slippage_bps
        / 10_000.0
        * execution.contract_multiplier
    )


def _exit_cost(leg: OptionLeg, price: float, execution: ExecutionAssumptions) -> float:
    return (
        execution.fee_per_contract * execution.contract_multiplier
        + abs(price) * execution.slippage_bps / 10_000.0 * execution.contract_multiplier
    )


def _finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ScenarioValidationError(f"{name} must be finite")


def _finite_non_negative(name: str, value: float) -> None:
    _finite(name, value)
    if value < 0:
        raise ScenarioValidationError(f"{name} cannot be negative")


def _dedupe_warnings(warnings: list[ScenarioWarning]) -> list[ScenarioWarning]:
    seen: set[tuple[str, str, str | None]] = set()
    result = []
    for warning in warnings:
        key = (warning.code, warning.message, warning.symbol)
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return result


__all__ = [
    "ExecutionAssumptions",
    "MarketScenario",
    "OptionLeg",
    "ScenarioGreeks",
    "ScenarioReport",
    "ScenarioResult",
    "ScenarioSet",
    "ScenarioValidationError",
    "StrategyDefinition",
    "evaluate_scenarios",
]
