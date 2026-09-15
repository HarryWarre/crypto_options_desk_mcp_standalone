from datetime import UTC, datetime, timedelta

import pytest

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionContract,
    OptionDataQualityIssue,
)
from options_lib.opportunity_scanner import (
    ScanRequest,
    scan_opportunities,
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
        candidate.fair_price
        - candidate.executable_entry
        - candidate.total_cost
    )
    assert candidate.max_loss == pytest.approx(0.656)
    assert candidate.evidence_status == "insufficient_evidence"
    assert candidate.expected_value_status == "not_validated"
    assert candidate.execution_allowed is False
    assert candidate.exit_fee == pytest.approx(0.05)
    assert candidate.exit_slippage_cost == pytest.approx(0.005)
    assert candidate.quote_timestamp == VALUATION_TIME
    assert result.data_timestamp == VALUATION_TIME


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
    "field,value",
    [("min_dte", -0.1), ("max_dte", -0.1), ("min_delta", -0.1), ("max_delta", 1.1)],
)
def test_scan_request_rejects_invalid_filters(field: str, value: float) -> None:
    kwargs = {field: value, "risk_free_rate": 0.0}
    with pytest.raises(ValueError):
        ScanRequest(**kwargs)
