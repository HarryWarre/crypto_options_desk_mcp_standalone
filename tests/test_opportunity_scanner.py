from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionContract,
    OptionDataQualityIssue,
)
from options_lib.historical_volatility import (
    HistoricalVolatilityContext,
    HistoricalVolatilityContexts,
)
from options_lib.opportunity_scanner import (
    ScanRequest,
    scan_opportunities,
    scan_opportunities_with_historical_context,
)

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
EXPIRY = VALUATION_TIME + timedelta(days=10)


def _contract(
    asset: str,
    strike: float,
    *,
    option_type: str = "Call",
    mark_iv: float = 0.20,
    ask: float = 0.60,
    bid: float = 0.50,
    delta: float = 0.50,
    volume: float = 100.0,
    open_interest: float = 100.0,
) -> OptionContract:
    symbol = f"{asset}-{strike:g}-{option_type[0].upper()}"
    return OptionContract(
        asset=asset,
        symbol=symbol,
        option_type=option_type,
        strike=strike,
        expiry_at=EXPIRY,
        expiry_code="25SEP26",
        spot_price=100.0,
        mark_price=(bid + ask) / 2,
        mark_iv=mark_iv,
        bid_price=bid,
        ask_price=ask,
        bid_iv=mark_iv,
        ask_iv=mark_iv,
        delta=delta,
        gamma=0.01,
        theta=-0.1,
        vega=0.2,
        volume_24h=volume,
        open_interest=open_interest,
        quote_currency="USD",
        settle_currency="USDC",
        quote_timestamp=VALUATION_TIME,
    )


def _universe(*contracts: OptionContract, issues=()) -> NormalizedOptionUniverse:
    assets = tuple(
        OptionAsset(asset, "Trading", sum(contract.asset == asset for contract in contracts))
        for asset in sorted({contract.asset for contract in contracts})
    )
    return NormalizedOptionUniverse(
        assets=assets,
        contracts=contracts,
        issues=tuple(issues),
        valuation_time=VALUATION_TIME,
    )


def _surface_fixture() -> NormalizedOptionUniverse:
    contracts = []
    for asset in ("ETH", "BTC"):
        contracts.extend(
            (
                _contract(asset, 90, mark_iv=0.30, ask=2.0, bid=1.8, delta=0.80),
                _contract(asset, 100, mark_iv=0.15, ask=0.60, bid=0.50, delta=0.50),
                _contract(asset, 110, mark_iv=0.30, ask=2.0, bid=1.8, delta=0.20),
            )
        )
    return _universe(*contracts)


def _vertical_surface_fixture() -> NormalizedOptionUniverse:
    contracts = [
        # Outer strikes keep every tested leg inside the fitted-surface range
        # after the pair itself is excluded from the quote.
        _contract("BTC", 80, option_type="Call", ask=0.6, bid=0.5),
        _contract("BTC", 90, option_type="Call", ask=8.0, bid=7.5),
        _contract("BTC", 100, option_type="Call", ask=3.0, bid=2.5),
        _contract("BTC", 110, option_type="Call", ask=0.8, bid=0.6),
        _contract("BTC", 120, option_type="Call", ask=0.1, bid=0.05),
        _contract("BTC", 130, option_type="Call", ask=0.6, bid=0.5),
        _contract("BTC", 80, option_type="Put", ask=0.6, bid=0.5),
        _contract("BTC", 90, option_type="Put", ask=0.1, bid=0.05),
        _contract("BTC", 100, option_type="Put", ask=2.0, bid=1.5),
        _contract("BTC", 110, option_type="Put", ask=8.0, bid=7.5),
        _contract("BTC", 120, option_type="Put", ask=14.0, bid=13.5),
        _contract("BTC", 130, option_type="Put", ask=0.6, bid=0.5),
    ]
    return _universe(*contracts)


def _iron_surface_fixture() -> NormalizedOptionUniverse:
    contracts = []
    for strike, put_ask, put_bid, call_ask, call_bid in (
        (70, 0.2, 0.1, 30.0, 29.0),
        (80, 0.5, 0.4, 20.0, 19.0),
        (90, 2.0, 1.8, 12.0, 11.0),
        (100, 5.0, 4.5, 5.0, 4.5),
        (110, 12.0, 11.0, 2.0, 1.8),
        (120, 20.0, 19.0, 0.5, 0.4),
        (130, 30.0, 29.0, 0.2, 0.1),
    ):
        contracts.extend(
            (
                _contract("BTC", strike, option_type="Put", ask=put_ask, bid=put_bid),
                _contract("BTC", strike, option_type="Call", ask=call_ask, bid=call_bid),
            )
        )
    return _universe(*contracts)


def _new_strategy_fixture() -> NormalizedOptionUniverse:
    universe = _iron_surface_fixture()
    contracts = []
    for contract in universe.contracts:
        if (contract.strike, contract.option_type.lower()) in {
            (90, "put"),
            (100, "call"),
            (100, "put"),
            (110, "call"),
        }:
            ask = (
                0.001
                if (contract.strike, contract.option_type.lower()) in {(90, "put"), (110, "call")}
                else 1.0
            )
            bid = ask * 0.8
            contracts.append(
                replace(
                    contract,
                    bid_price=bid,
                    ask_price=ask,
                    mark_price=(bid + ask) / 2,
                )
            )
        else:
            contracts.append(contract)
    return _universe(*contracts)


def test_scan_supports_multiple_assets_and_ranks_after_costs() -> None:
    result = scan_opportunities(
        _surface_fixture(),
        ScanRequest(
            assets=("ETH", "BTC"),
            risk_free_rate=0.0,
            strategies=("long_call",),
            min_iv_edge=0.05,
            fee_per_contract=0.05,
            slippage_bps=100.0,
        ),
    )

    assert [candidate.asset for candidate in result.opportunities] == ["BTC", "ETH"]
    candidate = result.opportunities[0]
    assert candidate.strategy == "long_call"
    assert candidate.surface_status == "interpolated"
    assert candidate.fair_iv == pytest.approx(0.30)
    assert candidate.iv_edge == pytest.approx(0.15)
    assert candidate.executable_entry == pytest.approx(0.60)
    assert candidate.slippage_cost == pytest.approx(0.006)
    assert candidate.edge_after_costs == pytest.approx(
        candidate.fair_price - candidate.executable_entry - candidate.total_cost
    )
    assert candidate.max_loss == pytest.approx(0.656)
    assert candidate.evidence_status == "insufficient_evidence"
    assert candidate.expected_value_status == "model_estimate"
    assert candidate.payoff_metrics_status == "estimated"
    assert candidate.expected_value is not None
    assert 0.0 <= candidate.win_probability <= 1.0
    assert candidate.payoff_curve
    assert candidate.payoff_metrics_assumptions is not None
    assert candidate.payoff_metrics_assumptions.historical_outcomes_used is False
    assert candidate.execution_allowed is False
    assert candidate.exit_fee == pytest.approx(0.05)
    assert candidate.exit_slippage_cost == pytest.approx(0.005)
    assert candidate.quote_timestamp == VALUATION_TIME
    assert result.data_timestamp == VALUATION_TIME


def test_multi_leg_surface_excludes_every_candidate_leg() -> None:
    universe = _universe(
        _contract("BTC", 80, mark_iv=0.10),
        _contract("BTC", 90, mark_iv=0.20),
        _contract("BTC", 100, mark_iv=1.00),
        _contract("BTC", 110, mark_iv=0.20),
        _contract("BTC", 120, mark_iv=0.10),
    )
    result = scan_opportunities(
        universe,
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("bull_call_vertical",),
        ),
    )

    candidate = next(
        item
        for item in result.opportunities
        if item.long_symbol == "BTC-90-C" and item.short_symbol == "BTC-100-C"
    )
    # The 90/100 legs are excluded, so both fitted values come from the
    # remaining 80/110/120 points rather than using the 100-strike 100% IV.
    assert candidate.legs[0].fair_iv == pytest.approx(0.14524385, abs=1e-7)
    assert candidate.legs[1].fair_iv == pytest.approx(0.17612860, abs=1e-7)


def test_theoretical_mode_values_missing_quote_without_executable_claims() -> None:
    target = replace(
        _contract("BTC", 100, mark_iv=0.15, ask=0.60, bid=0.50),
        bid_price=None,
        ask_price=0.0,
        mark_price=0.60,
    )
    universe = _universe(
        _contract("BTC", 90, mark_iv=0.30, ask=2.0, bid=1.8),
        target,
        _contract("BTC", 110, mark_iv=0.30, ask=2.0, bid=1.8),
    )

    result = scan_opportunities(
        universe,
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("long_call",),
            valuation_mode="theoretical",
            max_spread_pct=0.0,
            min_edge_after_costs=1_000_000.0,
            max_loss=0.0,
        ),
    )

    candidate = next(item for item in result.opportunities if item.symbol == target.symbol)
    assert result.valuation_mode == "theoretical"
    assert candidate.valuation_mode == "theoretical"
    assert candidate.fair_price > 0
    assert candidate.fair_iv > 0
    assert candidate.mark_price == pytest.approx(0.60)
    assert candidate.bid_price is None
    assert candidate.ask_price == 0.0
    assert candidate.executable_entry is None
    assert candidate.edge_after_costs is None
    assert candidate.edge_pct is None
    assert candidate.max_loss is not None
    assert candidate.max_profit is not None
    assert candidate.payoff_curve
    assert candidate.expected_value is not None
    assert candidate.win_probability is not None
    assert candidate.risk_reward is not None
    assert candidate.execution_allowed is False
    assert candidate.edge_source == "theoretical_fair_value_only"
    assert candidate.legs[0].mark_price == pytest.approx(0.60)
    assert result.ignored_filters == ("max_spread_pct", "min_edge_after_costs", "max_loss")


def test_theoretical_vertical_calculates_model_payoff_metrics_from_fair_values() -> None:
    result = scan_opportunities(
        _vertical_surface_fixture(),
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("bull_call_vertical",),
            valuation_mode="theoretical",
        ),
    )

    candidate = result.opportunities[0]
    assert candidate.payoff_curve
    assert candidate.expected_value is not None
    assert candidate.win_probability is not None
    assert candidate.risk_reward is not None
    assert candidate.max_loss is not None
    assert candidate.max_profit is not None
    assert candidate.breakevens
    assert candidate.payoff_metrics_assumptions is not None
    assert candidate.payoff_metrics_assumptions.entry_price_source == "theoretical_fair_value"


def test_synthetic_mode_builds_full_estimated_quote_metrics() -> None:
    target = replace(
        _contract("BTC", 100, mark_iv=0.15, ask=0.60, bid=0.50),
        bid_price=None,
        ask_price=0.0,
        mark_price=0.10,
    )
    universe = _universe(
        _contract("BTC", 90, mark_iv=0.30, ask=2.0, bid=1.8),
        target,
        _contract("BTC", 110, mark_iv=0.30, ask=2.0, bid=1.8),
    )

    result = scan_opportunities(
        universe,
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("long_call",),
            valuation_mode="synthetic",
            assumed_spread_bps=100.0,
        ),
    )

    candidate = next(item for item in result.opportunities if item.symbol == target.symbol)
    assert result.valuation_mode == "synthetic"
    assert result.ignored_filters == ()
    assert candidate.quote_source == "synthetic_mark_or_fair_value"
    assert candidate.bid_price == pytest.approx(0.0995)
    assert candidate.ask_price == pytest.approx(0.1005)
    assert candidate.estimated_entry == pytest.approx(candidate.ask_price)
    assert candidate.executable_entry is None
    assert candidate.edge_after_costs is not None
    assert candidate.edge_after_costs > 0
    assert candidate.expected_value is not None
    assert candidate.max_loss is not None
    assert candidate.payoff_metrics_assumptions is not None
    assert candidate.payoff_metrics_assumptions.entry_price_source == "synthetic_bid_ask"
    assert any("synthesized" in item for item in candidate.payoff_metrics_limitations)


def test_theoretical_single_leg_keeps_fair_value_per_contract() -> None:
    target = replace(
        _contract("BTC", 100, mark_iv=0.15),
        bid_price=None,
        ask_price=0.0,
    )
    universe = _universe(
        _contract("BTC", 90, mark_iv=0.30, ask=2.0, bid=1.8),
        target,
        _contract("BTC", 110, mark_iv=0.30, ask=2.0, bid=1.8),
    )
    base_request = ScanRequest(
        risk_free_rate=0.0,
        assets=("BTC",),
        strategies=("long_call",),
        valuation_mode="theoretical",
    )
    scaled_request = replace(base_request, quantity=2.0, contract_multiplier=10.0)

    base_candidate = next(
        item for item in scan_opportunities(universe, base_request).opportunities
        if item.symbol == target.symbol
    )
    scaled_candidate = next(
        item for item in scan_opportunities(universe, scaled_request).opportunities
        if item.symbol == target.symbol
    )

    assert scaled_candidate.fair_price == pytest.approx(base_candidate.fair_price)
    assert scaled_candidate.delta == pytest.approx(base_candidate.delta)


def test_theoretical_multi_leg_preserves_mark_price_on_each_leg() -> None:
    result = scan_opportunities(
        _vertical_surface_fixture(),
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("bull_call_vertical",),
            valuation_mode="theoretical",
        ),
    )

    candidate = result.opportunities[0]
    assert all(leg.mark_price is not None for leg in candidate.legs)


def test_scan_request_rejects_unknown_valuation_mode() -> None:
    with pytest.raises(ValueError, match="valuation_mode"):
        ScanRequest(risk_free_rate=0.0, valuation_mode="unknown")  # type: ignore[arg-type]


def test_executable_surface_excludes_unquoted_contracts() -> None:
    base = _surface_fixture()
    noisy = replace(
        _contract("BTC", 95, mark_iv=0.95, ask=1.0, bid=0.9),
        bid_price=None,
        ask_price=0.0,
    )
    noisy_universe = _universe(*base.contracts, noisy)
    request = ScanRequest(
        risk_free_rate=0.0,
        assets=("BTC",),
        strategies=("long_call",),
    )

    base_candidate = next(
        item for item in scan_opportunities(base, request).opportunities
        if item.symbol == "BTC-100-C"
    )
    noisy_candidate = next(
        item for item in scan_opportunities(noisy_universe, request).opportunities
        if item.symbol == "BTC-100-C"
    )

    assert noisy_candidate.fair_iv == pytest.approx(base_candidate.fair_iv)


def test_theoretical_mode_reports_evidence_rejection_without_crashing() -> None:
    result = scan_opportunities(
        _vertical_surface_fixture(),
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("bull_call_vertical",),
            valuation_mode="theoretical",
            include_unvalidated=False,
        ),
    )

    assert not result.opportunities
    assert any("evidence_not_validated" in item.reasons for item in result.rejections)


def test_executable_mode_remains_conservative_for_missing_or_zero_quotes() -> None:
    target = replace(
        _contract("BTC", 100),
        bid_price=None,
        ask_price=0.0,
    )
    result = scan_opportunities(
        _universe(
            _contract("BTC", 90, mark_iv=0.30, ask=2.0, bid=1.8),
            target,
            _contract("BTC", 110, mark_iv=0.30, ask=2.0, bid=1.8),
        ),
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("long_call",),
        ),
    )

    assert all(item.symbol != target.symbol for item in result.opportunities)
    rejection = next(item for item in result.rejections if item.symbol == target.symbol)
    assert "invalid_market_data" in rejection.reasons


def test_candidate_is_excluded_from_its_fitted_surface_quote() -> None:
    universe = _universe(
        _contract("BTC", 90, mark_iv=0.40, ask=2.0, bid=1.8),
        _contract("BTC", 100, mark_iv=0.10, ask=0.5, bid=0.4),
        _contract("BTC", 110, mark_iv=0.40, ask=2.0, bid=1.8),
    )

    result = scan_opportunities(
        universe,
        ScanRequest(risk_free_rate=0.0, strategies=("long_call",), min_iv_edge=0.1),
    )

    candidate = next(item for item in result.opportunities if item.strike == 100)
    assert candidate.fair_iv == pytest.approx(0.40)
    assert candidate.fair_iv != candidate.market_iv
    assert candidate.surface_status == "interpolated"


def test_opportunity_delta_uses_model_valued_greeks() -> None:
    result = scan_opportunities(
        _surface_fixture(),
        ScanRequest(risk_free_rate=0.0, assets=("BTC",), strategies=("long_call",)),
    )

    candidate = next(item for item in result.opportunities if item.strike == 100)

    # The market candidate delta is 0.50, while the fitted 30% IV model gives
    # the ATM call a delta of approximately 0.509904.
    assert candidate.delta == pytest.approx(0.509904, abs=1e-6)
    assert candidate.legs[0].delta == pytest.approx(candidate.delta)
    assert candidate.delta != pytest.approx(0.50)


def test_filters_produce_explicit_rejections_and_no_qualified_result() -> None:
    universe = _universe(
        _contract("BTC", 90, delta=0.90, ask=2.0, bid=1.0, volume=1.0),
        _contract("BTC", 100, mark_iv=0.20, ask=3.0, bid=2.6, volume=100.0),
        _contract("BTC", 110, delta=0.20, ask=0.6, bid=0.1, volume=100.0),
    )

    result = scan_opportunities(
        universe,
        ScanRequest(
            risk_free_rate=0.0,
            strategies=("long_call",),
            min_delta=0.30,
            max_delta=0.70,
            min_volume_24h=10.0,
            max_spread_pct=0.20,
            max_loss=1.0,
            min_iv_edge=0.05,
        ),
    )

    assert not result.opportunities
    rejection_by_strike = {item.strike: set(item.reasons) for item in result.rejections}
    assert "delta_out_of_range" in rejection_by_strike[90]
    assert "volume_below_minimum" in rejection_by_strike[90]
    assert "edge_after_costs_below_minimum" in rejection_by_strike[100]
    assert "max_loss_exceeded" in rejection_by_strike[100]
    assert "spread_above_maximum" in rejection_by_strike[110]


def test_partial_asset_failure_does_not_discard_successful_assets() -> None:
    issue = OptionDataQualityIssue(
        code="asset_fetch_failed",
        message="ticker request timed out",
        asset="ETH",
    )
    universe = _universe(
        _contract("BTC", 90, mark_iv=0.30, ask=2.0, bid=1.8),
        _contract("BTC", 100, mark_iv=0.15, ask=0.6, bid=0.5),
        _contract("BTC", 110, mark_iv=0.30, ask=2.0, bid=1.8),
        issues=(issue,),
    )
    universe = NormalizedOptionUniverse(
        assets=(OptionAsset("BTC", "Trading", 3), OptionAsset("ETH", "Trading", 0)),
        contracts=universe.contracts,
        issues=universe.issues,
        valuation_time=universe.valuation_time,
    )

    result = scan_opportunities(
        universe,
        ScanRequest(risk_free_rate=0.0, assets=("BTC", "ETH"), strategies=("long_call",)),
    )

    assert [candidate.asset for candidate in result.opportunities] == ["BTC"]
    assert result.asset_failures[0].asset == "ETH"
    assert result.asset_failures[0].code == "asset_fetch_failed"


def test_strategy_filter_rejects_unsupported_or_unselected_direction() -> None:
    result = scan_opportunities(
        _surface_fixture(),
        ScanRequest(risk_free_rate=0.0, strategies=("long_put",)),
    )

    assert not result.opportunities
    assert result.rejections
    assert all("strategy_not_allowed" in item.reasons for item in result.rejections)


def test_deterministic_ordering_and_empty_result_are_stable() -> None:
    universe = _surface_fixture()
    request = ScanRequest(
        risk_free_rate=0.0,
        assets=("BTC", "ETH"),
        strategies=("long_call",),
        min_iv_edge=0.05,
    )

    first = scan_opportunities(universe, request)
    reversed_universe = NormalizedOptionUniverse(
        assets=tuple(reversed(universe.assets)),
        contracts=tuple(reversed(universe.contracts)),
        issues=universe.issues,
        valuation_time=universe.valuation_time,
    )
    second = scan_opportunities(reversed_universe, request)

    assert first == second
    empty = scan_opportunities(
        universe,
        ScanRequest(risk_free_rate=0.0, assets=("SOL",), strategies=("long_call",)),
    )
    assert empty.opportunities == ()
    assert empty.rejections == ()
    assert empty.asset_failures[0].asset == "SOL"
    assert empty.asset_failures[0].code == "asset_not_available"


def test_strict_evidence_gate_returns_rejection_instead_of_unvalidated_signal() -> None:
    result = scan_opportunities(
        _surface_fixture(),
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("long_call",),
            min_iv_edge=0.05,
            include_unvalidated=False,
        ),
    )

    assert not result.opportunities
    assert result.evidence_gate_status == "blocked_unvalidated"
    assert any("evidence_not_validated" in item.reasons for item in result.rejections)


def test_costs_and_max_loss_scale_by_quantity_and_contract_multiplier() -> None:
    result = scan_opportunities(
        _surface_fixture(),
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("long_call",),
            min_iv_edge=0.05,
            fee_per_contract=0.05,
            slippage_bps=100.0,
            quantity=2.0,
            contract_multiplier=10.0,
        ),
    )

    candidate = result.opportunities[0]
    assert candidate.executable_entry == pytest.approx(12.0)
    assert candidate.max_loss == pytest.approx(13.12)
    assert candidate.fee == pytest.approx(1.0)
    assert candidate.total_cost == pytest.approx(
        candidate.entry_fee
        + candidate.exit_fee
        + candidate.entry_slippage_cost
        + candidate.exit_slippage_cost
    )


@pytest.mark.parametrize(
    "strategy",
    (
        "bull_call_vertical",
        "bear_call_vertical",
        "bull_put_vertical",
        "bear_put_vertical",
    ),
)
def test_vertical_strategies_pair_executable_legs_and_bound_risk(strategy: str) -> None:
    result = scan_opportunities(
        _vertical_surface_fixture(),
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=(strategy,),
        ),
    )

    assert result.opportunities
    candidate = result.opportunities[0]
    assert candidate.strategy == strategy
    assert candidate.long_symbol is not None
    assert candidate.short_symbol is not None
    assert [leg.position for leg in candidate.legs] == [1, -1]
    assert [leg.symbol for leg in candidate.legs] == [candidate.long_symbol, candidate.short_symbol]
    assert all(leg.fair_iv > 0 for leg in candidate.legs)
    assert candidate.long_strike != candidate.short_strike
    assert candidate.symbol == f"{candidate.long_symbol}/{candidate.short_symbol}"
    assert candidate.executable_entry == pytest.approx(candidate.ask_price)
    assert candidate.max_loss >= 0
    assert candidate.max_profit >= 0
    assert candidate.edge_after_costs == pytest.approx(
        candidate.fair_price - candidate.executable_entry - candidate.total_cost
    )
    assert candidate.payoff_metrics_status == "estimated"
    assert candidate.expected_value_status == "model_estimate"
    assert candidate.payoff_curve
    assert candidate.expected_value is not None
    assert candidate.win_probability is not None
    assert candidate.risk_reward is not None
    assert candidate.execution_allowed is False


def test_vertical_costs_and_bounds_use_both_executable_legs() -> None:
    universe = _vertical_surface_fixture()
    result = scan_opportunities(
        universe,
        ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=("bull_call_vertical",),
            fee_per_contract=0.05,
            slippage_bps=100.0,
            quantity=2.0,
            contract_multiplier=10.0,
        ),
    )

    candidate = next(
        item
        for item in result.opportunities
        if item.long_symbol == "BTC-90-C" and item.short_symbol == "BTC-100-C"
    )
    by_symbol = {contract.symbol: contract for contract in universe.contracts}
    long_leg = by_symbol[candidate.long_symbol]
    short_leg = by_symbol[candidate.short_symbol]
    scale = 20.0
    entry = (long_leg.ask_price - short_leg.bid_price) * scale
    entry_fee = 2.0 * 0.05 * scale
    entry_slippage = (long_leg.ask_price + short_leg.bid_price) * 100.0 / 10_000.0 * scale
    width = (short_leg.strike - long_leg.strike) * scale

    assert candidate.executable_entry == pytest.approx(entry)
    assert candidate.entry_fee == pytest.approx(entry_fee)
    assert candidate.entry_slippage_cost == pytest.approx(entry_slippage)
    assert candidate.max_loss == pytest.approx(entry + entry_fee + entry_slippage)
    assert candidate.max_profit == pytest.approx(width - candidate.max_loss)
    assert candidate.delta == pytest.approx(
        (0.9993110527 - 0.5066030381) * scale,
        abs=1e-6,
    )
    assert candidate.delta == pytest.approx(
        candidate.legs[0].delta - candidate.legs[1].delta,
        abs=1e-9,
    )
    assert candidate.delta != pytest.approx(long_leg.delta - short_leg.delta)


def test_vertical_rejects_missing_and_invalid_legs_explicitly() -> None:
    missing_puts = _universe(
        _contract("BTC", 90, option_type="Call", ask=8.0, bid=7.5),
        _contract("BTC", 100, option_type="Call", ask=3.0, bid=2.5),
    )
    missing_result = scan_opportunities(
        missing_puts,
        ScanRequest(risk_free_rate=0.0, strategies=("bull_put_vertical",)),
    )
    assert not missing_result.opportunities
    assert any(
        {"missing_long_leg", "missing_short_leg"}.issubset(item.reasons)
        and "missing_option_type" in item.reasons
        for item in missing_result.rejections
    )

    invalid_leg = _universe(
        _contract("BTC", 90, option_type="Call", ask=0.0, bid=0.0),
        _contract("BTC", 100, option_type="Call", ask=3.0, bid=2.5),
        _contract("BTC", 90, option_type="Put", ask=0.1, bid=0.05),
        _contract("BTC", 100, option_type="Put", ask=2.0, bid=1.5),
    )
    invalid_result = scan_opportunities(
        invalid_leg,
        ScanRequest(risk_free_rate=0.0, strategies=("bull_call_vertical",)),
    )
    assert any(
        "invalid_long_leg" in item.reasons and "invalid_market_data" in item.reasons
        for item in invalid_result.rejections
    )


@pytest.mark.parametrize("strategy", ("iron_condor", "iron_butterfly"))
def test_iron_strategies_scan_four_legs_and_return_bounded_metrics(strategy: str) -> None:
    result = scan_opportunities(
        _iron_surface_fixture(),
        ScanRequest(risk_free_rate=0.0, assets=("BTC",), strategies=(strategy,)),
    )

    assert result.opportunities
    candidate = result.opportunities[0]
    assert candidate.strategy == strategy
    assert len(candidate.legs) == 4
    assert [leg.position for leg in candidate.legs] == [1, -1, -1, 1]
    assert len(candidate.breakevens) == 2
    assert candidate.max_loss >= 0
    assert candidate.max_profit >= 0
    assert candidate.edge_after_costs == pytest.approx(
        candidate.fair_price - candidate.executable_entry - candidate.total_cost
    )
    assert candidate.payoff_metrics_status == "estimated"
    assert candidate.payoff_curve
    assert candidate.risk_reward is not None
    assert candidate.execution_allowed is False


def test_iron_strategy_rejects_a_chain_without_protective_wings() -> None:
    result = scan_opportunities(
        _universe(
            _contract("BTC", 90, option_type="Put", ask=2.0, bid=1.8),
            _contract("BTC", 100, option_type="Put", ask=5.0, bid=4.5),
            _contract("BTC", 100, option_type="Call", ask=5.0, bid=4.5),
            _contract("BTC", 110, option_type="Call", ask=2.0, bid=1.8),
        ),
        ScanRequest(risk_free_rate=0.0, strategies=("iron_condor",)),
    )

    assert not result.opportunities
    assert any("missing_put_wing" in item.reasons for item in result.rejections)


@pytest.mark.parametrize(
    "strategy",
    (
        "long_straddle",
        "long_strangle",
        "butterfly",
        "broken_wing_butterfly",
        "protective_put",
        "covered_call",
    ),
)
def test_new_same_expiry_and_overlay_strategies_return_typed_opportunities(strategy: str) -> None:
    result = scan_opportunities(
        _new_strategy_fixture(),
        ScanRequest(risk_free_rate=0.0, assets=("BTC",), strategies=(strategy,)),
    )

    assert result.opportunities
    candidate = result.opportunities[0]
    assert candidate.strategy == strategy
    assert candidate.legs
    if strategy in {"protective_put", "covered_call"}:
        assert candidate.requires_underlying_position is True
        assert candidate.risk_note
        assert candidate.market_iv > 0
        assert candidate.fair_iv > 0
        assert candidate.payoff_metrics_status == "unavailable"
        assert candidate.expected_value is None
    else:
        assert len(candidate.legs) in {2, 4}
        assert candidate.payoff_metrics_status == "estimated"
        assert candidate.payoff_curve


def test_calendar_spread_pairs_same_strike_across_expiries() -> None:
    base = _new_strategy_fixture()
    far_expiry = EXPIRY + timedelta(days=30)
    far_contracts = tuple(
        replace(
            contract,
            symbol=f"{contract.symbol}-FAR",
            expiry_at=far_expiry,
            expiry_code="25OCT26",
        )
        for contract in base.contracts
    )
    universe = _universe(*base.contracts, *far_contracts)

    result = scan_opportunities(
        universe,
        ScanRequest(risk_free_rate=0.0, assets=("BTC",), strategies=("calendar_spread",)),
    )

    assert result.opportunities
    candidate = result.opportunities[0]
    assert candidate.strategy == "calendar_spread"
    assert len(candidate.legs) == 2
    assert candidate.legs[0].strike == candidate.legs[1].strike
    assert candidate.legs[0].expiry_at < candidate.legs[1].expiry_at
    assert [leg.position for leg in candidate.legs] == [-1, 1]
    assert candidate.max_loss >= 0


@pytest.mark.parametrize(
    "strategy",
    (
        "long_straddle",
        "long_strangle",
        "protective_put",
        "covered_call",
        "calendar_spread",
        "butterfly",
        "broken_wing_butterfly",
    ),
)
def test_new_strategy_families_are_accepted_by_scan_request(strategy: str) -> None:
    request = ScanRequest(risk_free_rate=0.0, strategies=(strategy,))

    assert request.strategies == (strategy,)


@pytest.mark.parametrize(
    "field,value",
    [("min_dte", -0.1), ("max_dte", -0.1), ("min_delta", -0.1), ("max_delta", 1.1)],
)
def test_scan_request_rejects_invalid_filters(field: str, value: float) -> None:
    kwargs = {field: value, "risk_free_rate": 0.0}
    with pytest.raises(ValueError):
        ScanRequest(**kwargs)


def test_iron_condor_rejects_itm_short_puts_when_spot_below_strike() -> None:
    # User's case: Spot is 0.07, strikes are 0.08, 0.09, 0.10, 0.12.
    # Short put at 0.09 is ITM! Must not generate an iron condor.
    contracts = [
        replace(_contract("DOGE", 0.08, option_type="Put", ask=0.015, bid=0.014), spot_price=0.07),
        replace(_contract("DOGE", 0.09, option_type="Put", ask=0.022, bid=0.020), spot_price=0.07),
        replace(_contract("DOGE", 0.10, option_type="Call", ask=0.005, bid=0.004), spot_price=0.07),
        replace(_contract("DOGE", 0.12, option_type="Call", ask=0.002, bid=0.001), spot_price=0.07),
    ]
    result = scan_opportunities(
        _universe(*contracts),
        ScanRequest(risk_free_rate=0.0, strategies=("iron_condor",)),
    )
    assert not result.opportunities
    assert any("missing_put_wing" in item.reasons for item in result.rejections)


def test_credit_verticals_reject_itm_short_leg() -> None:
    # Bull put with short put at 110 when spot is 100 is ITM
    contracts = [
        _contract("BTC", 90, option_type="Put", ask=1.0, bid=0.9),
        _contract("BTC", 110, option_type="Put", ask=12.0, bid=11.0),
        _contract("BTC", 90, option_type="Call", ask=12.0, bid=11.0),
        _contract("BTC", 110, option_type="Call", ask=1.0, bid=0.9),
    ]
    bull_put_result = scan_opportunities(
        _universe(*contracts),
        ScanRequest(risk_free_rate=0.0, strategies=("bull_put_vertical",)),
    )
    assert not bull_put_result.opportunities
    assert any("short_leg_itm" in item.reasons for item in bull_put_result.rejections)

    bear_call_result = scan_opportunities(
        _universe(*contracts),
        ScanRequest(risk_free_rate=0.0, strategies=("bear_call_vertical",)),
    )
    assert not bear_call_result.opportunities
    assert any("short_leg_itm" in item.reasons for item in bear_call_result.rejections)


def test_scan_request_validates_moneyness_bounds() -> None:
    with pytest.raises(ValueError, match="min_moneyness cannot exceed max_moneyness"):
        ScanRequest(risk_free_rate=0.0, min_moneyness=1.2, max_moneyness=0.8)

    with pytest.raises(ValueError, match="min_moneyness cannot be negative"):
        ScanRequest(risk_free_rate=0.0, min_moneyness=-0.1)


def test_scanner_filters_deep_otm_strikes_by_moneyness() -> None:
    # Spot is 100.
    # Strike 50 -> moneyness = 0.50 (e.g. HYPE Put K50 when spot is ~91)
    # Strike 90 -> moneyness = 0.90
    # Strike 110 -> moneyness = 1.10
    # Strike 160 -> moneyness = 1.60
    contracts = [
        _contract("HYPE", 50, option_type="Put", ask=0.05, bid=0.01),
        _contract("HYPE", 90, option_type="Put", ask=2.0, bid=1.8),
        _contract("HYPE", 110, option_type="Call", ask=2.0, bid=1.8),
        _contract("HYPE", 160, option_type="Call", ask=0.05, bid=0.01),
    ]
    # Set spot_price to 100 for all
    contracts = [replace(c, spot_price=100.0) for c in contracts]

    result = scan_opportunities(
        _universe(*contracts),
        ScanRequest(
            assets=("HYPE",),
            risk_free_rate=0.0,
            strategies=("long_put", "long_call"),
            min_moneyness=0.70,
            max_moneyness=1.30,
            valuation_mode="synthetic",
        ),
    )

    rejection_reasons_by_strike = {
        item.strike: item.reasons for item in result.rejections
    }
    assert "moneyness_below_minimum" in rejection_reasons_by_strike.get(50, ())
    assert "moneyness_above_maximum" in rejection_reasons_by_strike.get(160, ())


def test_multi_leg_long_strangle_excludes_deep_otm_strikes_with_moneyness_bounds() -> None:
    # Spot is 100.
    # Put 50 (deep OTM), Put 90 (near ATM OTM), Call 110 (near ATM OTM), Call 160 (deep OTM)
    contracts = [
        replace(_contract("HYPE", 50, option_type="Put", ask=0.05, bid=0.01), spot_price=100.0),
        replace(_contract("HYPE", 90, option_type="Put", ask=2.0, bid=1.8), spot_price=100.0),
        replace(_contract("HYPE", 110, option_type="Call", ask=2.0, bid=1.8), spot_price=100.0),
        replace(_contract("HYPE", 160, option_type="Call", ask=0.05, bid=0.01), spot_price=100.0),
    ]

    result = scan_opportunities(
        _universe(*contracts),
        ScanRequest(
            assets=("HYPE",),
            risk_free_rate=0.0,
            strategies=("long_strangle",),
            min_moneyness=0.70,
            max_moneyness=1.30,
            valuation_mode="synthetic",
        ),
    )

    # Any resulting opportunities or valid multi-leg sets must not contain K50 or K160
    for opp in result.opportunities:
        strikes = [leg.strike for leg in opp.legs]
        assert 50 not in strikes, f"Strike 50 should be excluded by moneyness: {strikes}"
        assert 160 not in strikes, f"Strike 160 should be excluded by moneyness: {strikes}"


def test_iron_condor_prioritizes_bot_target_deltas() -> None:
    # Build universe with multiple OTM strikes and deltas:
    # Outer boundaries to support surface fitting: K60, K140
    # Puts: K70 (-0.03 delta), K80 (-0.08 delta), K90 (-0.15 delta), K95 (-0.30 delta)
    # Calls: K105 (+0.30 delta), K110 (+0.15 delta), K120 (+0.08 delta), K130 (+0.03 delta)
    contracts = [
        # Boundary strikes (ensures surface covers [60, 140])
        replace(_contract("BTC", 60, option_type="Put", ask=0.10, bid=0.08, delta=-0.01), spot_price=100.0),
        replace(_contract("BTC", 140, option_type="Call", ask=0.10, bid=0.08, delta=0.01), spot_price=100.0),
        # Puts (spot=100.0)
        replace(_contract("BTC", 70, option_type="Put", ask=0.20, bid=0.15, delta=-0.03), spot_price=100.0),
        replace(_contract("BTC", 80, option_type="Put", ask=0.60, bid=0.50, delta=-0.08), spot_price=100.0),
        replace(_contract("BTC", 90, option_type="Put", ask=1.50, bid=1.40, delta=-0.15), spot_price=100.0),
        replace(_contract("BTC", 95, option_type="Put", ask=3.00, bid=2.80, delta=-0.30), spot_price=100.0),
        # Calls (spot=100.0)
        replace(_contract("BTC", 105, option_type="Call", ask=3.00, bid=2.80, delta=0.30), spot_price=100.0),
        replace(_contract("BTC", 110, option_type="Call", ask=1.50, bid=1.40, delta=0.15), spot_price=100.0),
        replace(_contract("BTC", 120, option_type="Call", ask=0.60, bid=0.50, delta=0.08), spot_price=100.0),
        replace(_contract("BTC", 130, option_type="Call", ask=0.20, bid=0.15, delta=0.03), spot_price=100.0),
    ]

    result = scan_opportunities(
        _universe(*contracts),
        ScanRequest(
            assets=("BTC",),
            risk_free_rate=0.0,
            strategies=("iron_condor",),
            ic_target_short_delta=0.15,
            ic_target_wing_delta=0.03,
            valuation_mode="synthetic",
        ),
    )

    assert result.opportunities, "Expected at least one iron condor opportunity"
    top_candidate = result.opportunities[0]
    strikes = tuple(leg.strike for leg in top_candidate.legs)
    # The top candidate should precisely select: Put Wing=70, Short Put=90, Short Call=110, Call Wing=130
    assert strikes == (70.0, 90.0, 110.0, 130.0), f"Expected bot strikes (70, 90, 110, 130), got {strikes}"
    assert top_candidate.short_delta == pytest.approx(0.15, abs=0.01)
    assert top_candidate.wing_delta == pytest.approx(0.03, abs=0.01)
    assert top_candidate.net_credit is not None
    assert top_candidate.max_loss is not None


def test_iron_condor_iv_rv_regime_filtering() -> None:
    # Spot 100, market_iv = 0.50
    contracts = [
        # Boundary strikes to cover interpolation range
        replace(_contract("BTC", 60, option_type="Put", ask=0.10, bid=0.08, delta=-0.01, mark_iv=0.50), spot_price=100.0),
        replace(_contract("BTC", 140, option_type="Call", ask=0.10, bid=0.08, delta=0.01, mark_iv=0.50), spot_price=100.0),
        # Intermediary strikes for surface observations
        replace(_contract("BTC", 80, option_type="Put", ask=0.60, bid=0.50, delta=-0.08, mark_iv=0.50), spot_price=100.0),
        replace(_contract("BTC", 120, option_type="Call", ask=0.60, bid=0.50, delta=0.08, mark_iv=0.50), spot_price=100.0),
        # Candidate condor legs
        replace(_contract("BTC", 70, option_type="Put", ask=0.20, bid=0.15, delta=-0.03, mark_iv=0.50), spot_price=100.0),
        replace(_contract("BTC", 90, option_type="Put", ask=1.50, bid=1.40, delta=-0.15, mark_iv=0.50), spot_price=100.0),
        replace(_contract("BTC", 110, option_type="Call", ask=1.50, bid=1.40, delta=0.15, mark_iv=0.50), spot_price=100.0),
        replace(_contract("BTC", 130, option_type="Call", ask=0.20, bid=0.15, delta=0.03, mark_iv=0.50), spot_price=100.0),
    ]

    universe = _universe(*contracts)
    request = ScanRequest(
        assets=("BTC",),
        risk_free_rate=0.0,
        strategies=("iron_condor",),
        ic_min_iv_rv_spread=6.0,  # Min 6.0 vol points
        valuation_mode="synthetic",
    )

    # 1. When RV is 0.40: IV (0.50) - RV (0.40) = 10.0 vol points >= 6.0 threshold -> Accepted
    ctx_high_spread = HistoricalVolatilityContext(
        asset="BTC",
        period_days=30,
        available=True,
        status="available",
        historical_volatility=0.40,
        as_of=VALUATION_TIME,
        requested_at=VALUATION_TIME,
        retrieved_at=VALUATION_TIME,
    )
    result_high = scan_opportunities_with_historical_context(
        universe, request, HistoricalVolatilityContexts((ctx_high_spread,))
    )
    assert len(result_high.scan.opportunities) >= 1, "Expected candidates to pass regime filter"

    # 2. When RV is 0.48: IV (0.50) - RV (0.48) = 2.0 vol points < 6.0 threshold -> Rejected
    ctx_low_spread = HistoricalVolatilityContext(
        asset="BTC",
        period_days=30,
        available=True,
        status="available",
        historical_volatility=0.48,
        as_of=VALUATION_TIME,
        requested_at=VALUATION_TIME,
        retrieved_at=VALUATION_TIME,
    )
    result_low = scan_opportunities_with_historical_context(
        universe, request, HistoricalVolatilityContexts((ctx_low_spread,))
    )
    assert len(result_low.scan.opportunities) == 0, "Expected candidate to be rejected by regime filter"
    assert any("iv_rv_spread_below_minimum" in r.reasons for r in result_low.scan.rejections)



