from datetime import UTC, datetime, timedelta

import pytest

from bybit_api.options_market_data import (
    BybitOptionMarketDataAdapter,
    NormalizedOptionUniverse,
)
from bybit_api.utils import datetime_to_ms

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def _instrument(
    symbol,
    *,
    base_coin=None,
    option_type=None,
    strike="78000",
    expiry="2026-09-25T08:00:00Z",
    status="Trading",
):
    expiry_ms = datetime_to_ms(datetime.fromisoformat(expiry))
    return {
        "symbol": symbol,
        "baseCoin": base_coin or symbol.split("-")[0],
        "quoteCoin": "USD",
        "settleCoin": "USDC",
        "optionsType": option_type or ("Call" if symbol.split("-")[3] == "C" else "Put"),
        "strikePrice": strike,
        "status": status,
        "launchTime": str(expiry_ms - 30 * 24 * 60 * 60 * 1000),
        "deliveryTime": str(expiry_ms),
    }


def _ticker(symbol, *, timestamp=None, **overrides):
    result = {
        "symbol": symbol,
        "underlyingPrice": "80000",
        "markPrice": "1400",
        "markIv": "0.42",
        "bid1Price": "1350",
        "ask1Price": "1450",
        "bid1Iv": "0.41",
        "ask1Iv": "0.43",
        "delta": "0.52",
        "gamma": "0.00002",
        "theta": "-12.5",
        "vega": "95",
        "totalVolume": "12.5",
        "openInterest": "125",
    }
    result.update(overrides)
    return result


class FixturePublicRequest:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def __call__(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        if endpoint == "/v5/market/instruments-info":
            page = params.get("cursor", "first")
            return self.responses["instruments"][page]

        if endpoint == "/v5/market/tickers":
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                return self.responses["tickers"][params["baseCoin"]]
            finally:
                self.active -= 1

        raise AssertionError(f"unexpected endpoint: {endpoint}")


def _adapter(request, **kwargs):
    return BybitOptionMarketDataAdapter(
        request=request,
        valuation_time=VALUATION_TIME,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_discover_assets_follows_cursor_filters_trading_and_deduplicates_symbols():
    btc_sep = "BTC-25SEP26-78000-C"
    eth_sep = "ETH-25SEP26-3000-C"
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [
                        _instrument(btc_sep),
                        _instrument(eth_sep, base_coin="ETH", strike="3000"),
                        _instrument("SOL-25SEP26-100-P", base_coin="SOL", status="PreLaunch"),
                        _instrument(btc_sep),
                    ],
                    "nextPageCursor": "page-2",
                },
            },
            "page-2": {
                "retCode": 0,
                "result": {
                    "list": [_instrument("BTC-25SEP26-79000-P", option_type="Put")],
                    "nextPageCursor": "",
                },
            },
        },
        "tickers": {},
    }

    request = FixturePublicRequest(responses)
    catalog = await _adapter(request).discover_assets()

    assert [asset.base_coin for asset in catalog.assets] == ["BTC", "ETH"]
    assert {asset.base_coin: asset.contract_count for asset in catalog.assets} == {
        "BTC": 2,
        "ETH": 1,
    }
    instrument_calls = [call for call in request.calls if call[0].endswith("instruments-info")]
    assert len(instrument_calls) == 2
    assert instrument_calls[0][1]["baseCoin"] == "All"
    assert instrument_calls[0][1]["status"] == "Trading"
    assert instrument_calls[1][1]["cursor"] == "page-2"
    assert any(issue.code == "duplicate_instrument" for issue in catalog.issues)


@pytest.mark.asyncio
async def test_load_universe_normalizes_contracts_and_sorts_real_expiry_dates():
    jun_27 = "BTC-25JUN27-80000-P"
    sep_26 = "BTC-25SEP26-78000-C"
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [_instrument(jun_27, option_type="Put", strike="80000", expiry="2027-06-25T08:00:00Z"),
                              _instrument(sep_26)],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {
            "BTC": {
                "retCode": 0,
                "time": datetime_to_ms(VALUATION_TIME - timedelta(seconds=20)),
                "result": {
                    "list": [
                        _ticker(jun_27, delta="-0.48"),
                        _ticker(sep_26),
                    ]
                },
            }
        },
    }

    universe = await _adapter(FixturePublicRequest(responses)).load_universe()

    assert isinstance(universe, NormalizedOptionUniverse)
    assert [contract.symbol for contract in universe.contracts] == [sep_26, jun_27]
    contract = universe.contracts[0]
    assert contract.asset == "BTC"
    assert contract.option_type == "Call"
    assert contract.strike == 78000.0
    assert contract.expiry_at == datetime(2026, 9, 25, 8, 0, 0, tzinfo=UTC)
    assert contract.expiry_at.tzinfo is UTC
    assert contract.spot_price == 80000.0
    assert contract.mark_iv == 0.42
    assert contract.delta == 0.52
    assert contract.bid_price == 1350.0
    assert contract.ask_price == 1450.0
    assert contract.volume_24h == 12.5
    assert contract.open_interest == 125.0
    assert contract.quote_currency == "USD"
    assert contract.settle_currency == "USDC"
    assert not universe.issues


def test_normalize_instrument_falls_back_to_bybit_delivery_time_when_missing():
    adapter = _adapter(FixturePublicRequest({}))
    symbol = "BTC-25SEP26-78000-C"
    raw = _instrument(symbol)
    raw.pop("deliveryTime")

    record, issues = adapter._normalize_instrument(raw)

    assert record is not None
    assert record.expiry_at == datetime(2026, 9, 25, 8, 0, 0, tzinfo=UTC)
    assert record.expiry_at.tzinfo is UTC
    assert [issue.code for issue in issues] == ["missing_delivery_time"]


def test_normalize_instrument_preserves_delivery_time_as_aware_utc():
    adapter = _adapter(FixturePublicRequest({}))
    symbol = "BTC-25SEP26-78000-C"
    raw = _instrument(symbol, expiry="2026-09-25T08:00:00+00:00")

    record, issues = adapter._normalize_instrument(raw)

    assert record is not None
    assert record.expiry_at == datetime(2026, 9, 25, 8, 0, 0, tzinfo=UTC)
    assert record.expiry_at.tzinfo is UTC
    assert not issues


@pytest.mark.asyncio
async def test_live_scan_does_not_reject_ticker_as_future_quote():
    """Live valuation time must be sampled after the ticker request starts."""

    symbol = "BTC-25SEP26-78000-C"
    response_time = datetime(2026, 9, 15, 12, 0, 1, tzinfo=UTC)
    clock_values = iter(
        [
            datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC),
            datetime(2026, 9, 15, 12, 0, 1, 500000, tzinfo=UTC),
            datetime(2026, 9, 15, 12, 0, 2, tzinfo=UTC),
        ]
    )
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [_instrument(symbol)],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {
            "BTC": {
                "retCode": 0,
                "time": datetime_to_ms(response_time),
                "result": {"list": [_ticker(symbol)]},
            }
        },
    }

    adapter = BybitOptionMarketDataAdapter(
        request=FixturePublicRequest(responses),
        now_fn=lambda: next(clock_values),
    )

    universe = await adapter.load_universe(assets=("BTC",))

    assert [contract.symbol for contract in universe.contracts] == [symbol]
    assert not any(issue.code == "future_quote" for issue in universe.issues)


@pytest.mark.asyncio
async def test_load_universe_accepts_current_bybit_symbol_with_settlement_suffix():
    symbol = "BTC-25SEP26-78000-C-USDT"
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [_instrument(symbol, expiry="2026-09-25T08:00:00Z")],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {
            "BTC": {
                "retCode": 0,
                "time": datetime_to_ms(VALUATION_TIME),
                "result": {"list": [_ticker(symbol)]},
            }
        },
    }

    universe = await _adapter(FixturePublicRequest(responses)).load_universe()

    assert [contract.symbol for contract in universe.contracts] == [symbol]
    assert universe.contracts[0].settle_currency == "USDC"


@pytest.mark.asyncio
async def test_load_universe_rejects_missing_result_and_non_positive_prices():
    missing_result = "BTC-25SEP26-78000-C"
    zero_prices = "ETH-25SEP26-3000-C"
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [
                        _instrument(missing_result),
                        _instrument(zero_prices, base_coin="ETH", strike="3000"),
                    ],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {
            "BTC": {"retCode": 0, "time": datetime_to_ms(VALUATION_TIME)},
            "ETH": {
                "retCode": 0,
                "time": datetime_to_ms(VALUATION_TIME),
                "result": {
                    "list": [_ticker(zero_prices, underlyingPrice="0", markPrice="0")]
                },
            },
        },
    }

    universe = await _adapter(FixturePublicRequest(responses)).load_universe()

    assert not universe.contracts
    assert any(issue.code == "asset_fetch_failed" and issue.asset == "BTC" for issue in universe.issues)
    assert {issue.code for issue in universe.issues} >= {
        "non_positive_spot_price",
        "non_positive_mark_price",
    }


@pytest.mark.asyncio
async def test_load_universe_keeps_model_valid_contract_without_bid_or_ask() -> None:
    symbol = "MNT-25SEP26-1-C"
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [_instrument(symbol, base_coin="MNT", strike="1")],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {
            "MNT": {
                "retCode": 0,
                "time": datetime_to_ms(VALUATION_TIME),
                "result": {
                    "list": [_ticker(symbol, bid1Price="", ask1Price="0")]
                },
            }
        },
    }

    universe = await _adapter(FixturePublicRequest(responses)).load_universe()

    assert len(universe.contracts) == 1
    contract = universe.contracts[0]
    assert contract.bid_price is None
    assert contract.ask_price == 0.0
    assert contract.mark_price > 0
    assert contract.mark_iv > 0
    assert "missing_bid_price" in {issue.code for issue in universe.issues}


@pytest.mark.asyncio
async def test_discovery_rejects_metadata_that_disagrees_with_symbol():
    asset_mismatch = "BTC-25SEP26-78000-C"
    type_mismatch = "ETH-25SEP26-3000-P"
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [
                        _instrument(asset_mismatch, base_coin="ETH"),
                        _instrument(type_mismatch, base_coin="ETH", option_type="Call", strike="3000"),
                    ],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {},
    }

    catalog = await _adapter(FixturePublicRequest(responses)).discover_assets()

    assert not catalog.assets
    assert {issue.code for issue in catalog.issues} == {
        "asset_symbol_mismatch",
        "option_type_mismatch",
    }


@pytest.mark.asyncio
async def test_load_universe_excludes_bad_quotes_with_explicit_quality_reasons():
    good = "BTC-25SEP26-78000-C"
    malformed = "BTC-BAD-78000-C"
    stale = "ETH-25SEP26-3000-P"
    incomplete = "SOL-25SEP26-100-C"
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [
                        _instrument(good),
                        _instrument(malformed),
                        _instrument(stale, base_coin="ETH", option_type="Put", strike="3000"),
                        _instrument(incomplete, base_coin="SOL", strike="100"),
                    ],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {
            "BTC": {
                "retCode": 0,
                "time": datetime_to_ms(VALUATION_TIME),
                "result": {
                    "list": [
                        _ticker(good),
                    ]
                },
            },
            "ETH": {
                "retCode": 0,
                "time": datetime_to_ms(VALUATION_TIME - timedelta(minutes=10)),
                "result": {"list": [_ticker(stale, bid1Price="0", ask1Price="0")]},
            },
            "SOL": {
                "retCode": 0,
                "time": datetime_to_ms(VALUATION_TIME),
                "result": {
                    "list": [
                        _ticker(incomplete, markIv="", delta=None, bid1Price="0", ask1Price="0")
                    ]
                },
            },
        },
    }

    universe = await _adapter(FixturePublicRequest(responses), max_quote_age_seconds=300).load_universe()

    assert [contract.symbol for contract in universe.contracts] == [good]
    issue_codes = {issue.code for issue in universe.issues}
    assert {
        "invalid_expiry_code",
        "stale_quote",
        "non_positive_bid_ask",
        "missing_mark_iv",
        "missing_delta",
    } <= issue_codes


@pytest.mark.asyncio
async def test_load_universe_deduplicates_tickers_and_limits_asset_requests():
    symbols = [
        "BTC-25SEP26-78000-C",
        "ETH-25SEP26-3000-C",
        "SOL-25SEP26-100-C",
    ]
    responses = {
        "instruments": {
            "first": {
                "retCode": 0,
                "result": {
                    "list": [
                        _instrument(symbols[0]),
                        _instrument(symbols[1], base_coin="ETH", strike="3000"),
                        _instrument(symbols[2], base_coin="SOL", strike="100"),
                    ],
                    "nextPageCursor": "",
                },
            }
        },
        "tickers": {
            "BTC": {"retCode": 0, "time": datetime_to_ms(VALUATION_TIME), "result": {"list": [_ticker(symbols[0]), _ticker(symbols[0], markPrice="1500")]}},
            "ETH": {"retCode": 0, "time": datetime_to_ms(VALUATION_TIME), "result": {"list": [_ticker(symbols[1])]}},
            "SOL": {"retCode": 0, "time": datetime_to_ms(VALUATION_TIME), "result": {"list": [_ticker(symbols[2])]}},
        },
    }

    request = FixturePublicRequest(responses)
    universe = await _adapter(request, max_concurrent_requests=2).load_universe()

    assert len(universe.contracts) == 3
    assert request.max_active <= 2
    assert len([call for call in request.calls if call[0].endswith("instruments-info")]) == 1
    assert sum(issue.code == "duplicate_ticker" for issue in universe.issues) == 1
