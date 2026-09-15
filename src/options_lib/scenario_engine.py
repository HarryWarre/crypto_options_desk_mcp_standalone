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
    strategy_type: Literal["long_call", "long_put", "call_vertical", "put_vertical"]
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
    """Evaluate a single leg or defined-risk vertical over supplied scenarios."""

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
        if leg.surface is not None:
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
            status="extrapolated" if any(w.code == "surface_extrapolated" for w in warnings) else "ok",
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
    entry_cost = sum(
        (leg.ask if leg.position > 0 else -leg.bid) * scale for leg in legs
    )
    entry_fees = sum(
        execution.fee_per_contract * execution.contract_multiplier for _ in legs
    )
    entry_slippage = sum(
        abs(leg.ask if leg.position > 0 else leg.bid)
        * execution.slippage_bps
        / 10_000.0
        * scale
        for leg in legs
    )
    net_debit = entry_cost + entry_fees + entry_slippage

    if strategy.strategy_type in {"call_vertical", "put_vertical"}:
        long_leg = next(leg for leg in legs if leg.position > 0)
        short_leg = next(leg for leg in legs if leg.position < 0)
        width = abs(long_leg.strike - short_leg.strike) * scale
        if execution.fee_per_contract == 0 and execution.slippage_bps == 0:
            max_loss = max(0.0, entry_cost)
        else:
            # Conservative operational bound: a long leg may be paid in full
            # while the short-leg credit is unavailable during a stressed exit.
            max_loss = long_leg.ask * scale + entry_fees + entry_slippage
        max_profit = max(0.0, width - net_debit)
        debit_per_unit = net_debit / scale
        if strategy.strategy_type == "call_vertical":
            breakevens = (long_leg.strike + debit_per_unit,)
        else:
            breakevens = (long_leg.strike - debit_per_unit,)
        return max_loss, max_profit, breakevens

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
    if strategy.strategy_type not in {"call_vertical", "put_vertical"} or len(strategy.legs) != 2:
        raise ScenarioValidationError("only long single legs and defined-risk verticals are supported")
    long_leg = tuple(leg for leg in strategy.legs if leg.position > 0)
    short_leg = tuple(leg for leg in strategy.legs if leg.position < 0)
    if len(long_leg) != 1 or len(short_leg) != 1:
        raise ScenarioValidationError("vertical must contain one long and one short leg")
    long_leg, short_leg = long_leg[0], short_leg[0]
    expected = "call" if strategy.strategy_type == "call_vertical" else "put"
    if any(leg.option_type.lower() not in {expected, expected[0]} for leg in strategy.legs):
        raise ScenarioValidationError("vertical option type does not match its name")
    if long_leg.expiry != short_leg.expiry:
        raise ScenarioValidationError("vertical legs must share an expiry")
    if strategy.strategy_type == "call_vertical" and not long_leg.strike < short_leg.strike:
        raise ScenarioValidationError("call vertical needs long lower strike and short higher strike")
    if strategy.strategy_type == "put_vertical" and not long_leg.strike > short_leg.strike:
        raise ScenarioValidationError("put vertical needs long higher strike and short lower strike")


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
    if not isinstance(leg.position, int) or isinstance(leg.position, bool) or leg.position not in {-1, 1}:
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
    return execution.fee_per_contract * execution.contract_multiplier + abs(
        leg.ask if leg.position > 0 else leg.bid
    ) * execution.slippage_bps / 10_000.0 * execution.contract_multiplier


def _exit_cost(leg: OptionLeg, price: float, execution: ExecutionAssumptions) -> float:
    return execution.fee_per_contract * execution.contract_multiplier + abs(price) * execution.slippage_bps / 10_000.0 * execution.contract_multiplier


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
