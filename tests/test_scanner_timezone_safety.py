from datetime import UTC, datetime

import pytest

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionContract,
)
from options_app.api import (
    ScanFilters,
    _execute_scan,
    _market_context_from_universe,
)
from options_lib.opportunity_scanner import scan_opportunities


def make_test_universe(*, naive_valuation: bool = True) -> NormalizedOptionUniverse:
    """Return a universe with contracts having aware UTC expiries and either naive or aware valuation_time."""
    valuation_time = (
        datetime(2026, 9, 18, 1, 0, 0)  # noqa: DTZ001
        if naive_valuation
        else datetime(2026, 9, 18, 1, 0, 0, tzinfo=UTC)
    )
    quote_time = datetime(2026, 9, 18, 0, 59, 30, tzinfo=UTC)
    contract = OptionContract(
        asset="BTC",
        symbol="BTC-25SEP26-80000-C",
        option_type="call",
        strike=80000.0,
        expiry_at=datetime(2026, 9, 25, 8, 0, 0, tzinfo=UTC),
        expiry_code="25SEP26",
        spot_price=80000.0,
        mark_price=2000.0,
        mark_iv=0.5,
        bid_price=1900.0,
        ask_price=2100.0,
        bid_iv=0.49,
        ask_iv=0.51,
        delta=0.5,
        gamma=0.0001,
        theta=-10.0,
        vega=50.0,
        volume_24h=100.0,
        open_interest=500.0,
        quote_currency="USD",
        settle_currency="USDC",
        quote_timestamp=quote_time,
    )
    return NormalizedOptionUniverse(
        assets=(OptionAsset("BTC", "Trading", 1),),
        contracts=(contract,),
        issues=(),
        valuation_time=valuation_time,
    )


def test_market_context_from_universe_handles_naive_and_aware_valuation_time():
    """Verify _market_context_from_universe does not crash when universe.valuation_time is naive."""
    naive_universe = make_test_universe(naive_valuation=True)
    context = _market_context_from_universe(naive_universe)
    assert context.observed_at.tzinfo is not None
    assert context.features["quote_count"] == 1.0
    assert context.features["min_dte_days"] > 0.0

    aware_universe = make_test_universe(naive_valuation=False)
    context_aware = _market_context_from_universe(aware_universe)
    assert context_aware.observed_at.tzinfo is not None
    assert context_aware.features["quote_count"] == 1.0


class DummyMarketAdapter:
    def __init__(self, universe: NormalizedOptionUniverse) -> None:
        self.universe = universe

    async def discover_assets(self):
        return self.universe.assets

    async def load_universe(self, *args, **kwargs):
        return self.universe


class DummyHistoryLoader:
    async def get_historical_volatility(self, *args, **kwargs):
        return None

    async def load(self, assets, *, as_of=None):
        from options_lib.historical_volatility import (
            HistoricalVolatilityContext,
            HistoricalVolatilityContexts,
        )

        return HistoricalVolatilityContexts((HistoricalVolatilityContext(asset="BTC", available=False),))


@pytest.mark.asyncio
async def test_execute_scan_completes_with_naive_universe_valuation_time():
    """Verify _execute_scan handles naive universe.valuation_time through all steps without TypeError or ValueError."""
    naive_universe = make_test_universe(naive_valuation=True)
    adapter = DummyMarketAdapter(naive_universe)
    history_loader = DummyHistoryLoader()

    filters = ScanFilters(
        assets=["BTC"],
        strategies=["long_call"],
        valuation_mode="synthetic",
        include_unvalidated=True,
    )
    scan_request = filters.to_scan_request()

    progress_messages = []
    async def on_progress(msg: str) -> None:
        progress_messages.append(msg)

    result = await _execute_scan(
        scan_request,
        adapter,
        scan_opportunities,
        historical_volatility_loader=history_loader,
        on_progress=on_progress,
    )

    assert result is not None
    assert any("[STEP 6/6]" in msg for msg in progress_messages)


@pytest.mark.asyncio
async def test_adapter_load_universe_ensures_aware_valuation_time():
    """Verify BybitOptionMarketDataAdapter.load_universe creates a timezone-aware valuation_time."""
    from bybit_api.options_market_data import BybitOptionMarketDataAdapter

    async def fake_request(endpoint, params):
        if endpoint == "/v5/market/instruments-info":
            return {"retCode": 0, "result": {"list": [], "nextPageCursor": ""}}
        return {"retCode": 0, "result": {"list": []}}

    adapter = BybitOptionMarketDataAdapter(request=fake_request)
    universe = await adapter.load_universe()
    assert universe.valuation_time.tzinfo is not None
    assert universe.valuation_time.tzinfo == UTC
