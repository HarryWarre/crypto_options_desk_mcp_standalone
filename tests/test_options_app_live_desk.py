from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionContract,
)
from options_app.api import create_app
from options_app.live_desk import LiveDeskSnapshot
from options_lib.opportunity_scanner import RejectedCandidate, ScanResult

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
DATA_TIME = datetime(2026, 9, 15, 11, 59, 30, tzinfo=UTC)
EXPIRY = datetime(2026, 12, 30, 12, 0, tzinfo=UTC)


def contract(
    symbol: str,
    *,
    asset: str = "BTC",
    spot: float = 100_000,
    bid: float | None = 100,
    ask: float | None = 110,
    quote_timestamp: datetime = DATA_TIME,
) -> OptionContract:
    return OptionContract(
        asset=asset,
        symbol=symbol,
        option_type="Call",
        strike=100_000,
        expiry_at=EXPIRY,
        expiry_code="30DEC26",
        spot_price=spot,
        mark_price=105,
        mark_iv=0.5,
        bid_price=bid,
        ask_price=ask,
        bid_iv=None,
        ask_iv=None,
        delta=0.5,
        gamma=0.01,
        theta=-1,
        vega=2,
        volume_24h=10,
        open_interest=10,
        quote_currency="USDT",
        settle_currency="USDC",
        quote_timestamp=quote_timestamp,
    )


def market_universe() -> NormalizedOptionUniverse:
    return NormalizedOptionUniverse(
        assets=(
            OptionAsset("BTC", "Trading", 2),
            OptionAsset("ETH", "Trading", 1),
        ),
        contracts=(
            contract("BTC-30DEC26-100000-C"),
            contract("BTC-30DEC26-101000-C", bid=None),
        ),
        issues=(),
        valuation_time=VALUATION_TIME,
        source="fake-bybit-live",
    )


def rejected(symbol: str, reasons: tuple[str, ...]) -> RejectedCandidate:
    return RejectedCandidate(
        asset="BTC",
        symbol=symbol,
        option_type="Call",
        strike=100_000,
        expiry_at=EXPIRY,
        reasons=reasons,
        messages=tuple(reasons),
        quote_timestamp=DATA_TIME,
    )


def empty_scan(universe: NormalizedOptionUniverse) -> ScanResult:
    return ScanResult(
        timestamp=VALUATION_TIME,
        data_timestamp=DATA_TIME,
        opportunities=(),
        rejections=(
            rejected("BTC-30DEC26-100000-C", ("spread_above_maximum",)),
            rejected("BTC-30DEC26-101000-C", ("spread_above_maximum", "low_liquidity")),
        ),
        asset_failures=(),
        issues=universe.issues,
    )


def test_live_desk_snapshot_preserves_market_state_without_opportunities() -> None:
    universe = market_universe()
    snapshot = LiveDeskSnapshot.from_scan(
        universe,
        empty_scan(universe),
        selected_assets=("btc",),
    )

    assert snapshot.selected_assets == ("BTC",)
    assert snapshot.observed_assets == (snapshot.observed_assets[0],)
    assert snapshot.observed_assets[0].asset == "BTC"
    assert snapshot.observed_assets[0].spot == 100_000
    assert snapshot.observed_assets[0].contract_count == 2
    assert snapshot.observed_assets[0].valid_quote_count == 1
    assert snapshot.option_quotes[0].symbol == "BTC-30DEC26-100000-C"
    assert snapshot.option_quotes[0].bid_price == 100
    assert snapshot.option_quotes[0].ask_price == 110
    assert snapshot.timestamp == VALUATION_TIME
    assert snapshot.data_timestamp == DATA_TIME
    assert snapshot.source == "fake-bybit-live"
    assert snapshot.rejection_reasons == {
        "low_liquidity": 1,
        "spread_above_maximum": 2,
    }
    assert snapshot.execution_allowed is False


class FakeLiveAdapter:
    async def load_universe(self, assets=None, *, valuation_time=None):
        return market_universe()


def test_live_websocket_payload_contains_live_desk_market_state() -> None:
    universe = market_universe()

    def scanner(_universe, _request):
        return empty_scan(universe)

    with (
        TestClient(
            create_app(
                adapter=FakeLiveAdapter(),
                scanner=scanner,
                live_scan_interval_seconds=0,
            )
        ) as client,
        client.websocket_connect("/api/v1/opportunities/stream") as websocket,
    ):
        websocket.send_json(
            {
                "assets": ["BTC"],
                "strategies": ["long_call"],
                "market_view": "custom",
                "time_horizon": "7_30",
                "max_loss": 100,
            }
        )
        assert websocket.receive_json()["status"] == "starting"
        while True:
            event = websocket.receive_json()
            if event["type"] == "snapshot":
                break

    assert event["execution_allowed"] is False
    assert event["payload"]["opportunities"] == []
    assert event["payload"]["rejections"] == []
    assert event["payload"]["rejection_count"] == 2
    assert event["payload"]["issue_count"] == 0
    assert event["payload"]["live_desk"] == {
        "selected_assets": ["BTC"],
        "observed_assets": [
            {
                "asset": "BTC",
                "spot": 100_000,
                "contract_count": 2,
                "valid_quote_count": 1,
            }
        ],
        "option_quotes": [
            {
                "asset": "BTC",
                "symbol": "BTC-30DEC26-100000-C",
                "option_type": "Call",
                "strike": 100_000,
                "expiry_at": "2026-12-30T12:00:00Z",
                "spot_price": 100_000,
                "mark_price": 105,
                "mark_iv": 0.5,
                "bid_price": 100,
                "ask_price": 110,
                "delta": 0.5,
                "volume_24h": 10,
                "open_interest": 10,
                "quote_timestamp": "2026-09-15T11:59:30Z",
            },
            {
                "asset": "BTC",
                "symbol": "BTC-30DEC26-101000-C",
                "option_type": "Call",
                "strike": 100_000,
                "expiry_at": "2026-12-30T12:00:00Z",
                "spot_price": 100_000,
                "mark_price": 105,
                "mark_iv": 0.5,
                "bid_price": None,
                "ask_price": 110,
                "delta": 0.5,
                "volume_24h": 10,
                "open_interest": 10,
                "quote_timestamp": "2026-09-15T11:59:30Z",
            },
        ],
        "timestamp": "2026-09-15T12:00:00Z",
        "data_timestamp": "2026-09-15T11:59:30Z",
        "source": "fake-bybit-live",
        "rejection_reasons": {
            "low_liquidity": 1,
            "spread_above_maximum": 2,
        },
        "execution_allowed": False,
    }
