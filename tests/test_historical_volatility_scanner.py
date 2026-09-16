from datetime import UTC, datetime, timedelta

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionContract,
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

VALUATION_TIME = datetime(2026, 9, 16, 8, tzinfo=UTC)
EXPIRY = VALUATION_TIME + timedelta(days=10)


def _contract(strike: float, mark_iv: float, ask: float, bid: float) -> OptionContract:
    return OptionContract(
        asset="BTC",
        symbol=f"BTC-26SEP26-{strike:g}-C",
        option_type="Call",
        strike=strike,
        expiry_at=EXPIRY,
        expiry_code="26SEP26",
        spot_price=100.0,
        mark_price=(bid + ask) / 2,
        mark_iv=mark_iv,
        bid_price=bid,
        ask_price=ask,
        bid_iv=mark_iv,
        ask_iv=mark_iv,
        delta=0.5,
        gamma=0.01,
        theta=-0.1,
        vega=0.2,
        volume_24h=100.0,
        open_interest=100.0,
        quote_currency="USD",
        settle_currency="USDC",
        quote_timestamp=VALUATION_TIME,
    )


def _universe() -> NormalizedOptionUniverse:
    contracts = (
        _contract(90, 0.30, 2.0, 1.8),
        _contract(100, 0.15, 0.60, 0.50),
        _contract(110, 0.30, 2.0, 1.8),
    )
    return NormalizedOptionUniverse(
        assets=(OptionAsset("BTC", "Trading", len(contracts)),),
        contracts=contracts,
        issues=(),
        valuation_time=VALUATION_TIME,
    )


def test_scanner_reports_history_context_without_changing_fair_iv() -> None:
    request = ScanRequest(risk_free_rate=0.0, strategies=("long_call",))
    without_history = scan_opportunities(_universe(), request)
    context = HistoricalVolatilityContext(
        asset="BTC",
        period_days=30,
        available=True,
        status="available",
        historical_volatility=0.42,
        as_of=VALUATION_TIME - timedelta(hours=1),
        requested_at=VALUATION_TIME,
        retrieved_at=VALUATION_TIME,
    )

    with_history = scan_opportunities_with_historical_context(
        _universe(),
        request,
        HistoricalVolatilityContexts((context,)),
    )

    assert with_history.historical_volatility_contexts == (context,)
    assert [(item.symbol, item.fair_iv) for item in with_history.scan.opportunities] == [
        (item.symbol, item.fair_iv) for item in without_history.opportunities
    ]


def test_scanner_marks_unloaded_history_explicitly() -> None:
    result = scan_opportunities_with_historical_context(
        _universe(),
        ScanRequest(risk_free_rate=0.0, strategies=("long_call",)),
        HistoricalVolatilityContexts(),
    )

    assert len(result.historical_volatility_contexts) == 1
    context = result.historical_volatility_contexts[0]
    assert context.asset == "BTC"
    assert context.available is False
    assert context.status == "not_loaded"
    assert context.as_of is None
    assert context.historical_volatility is None
