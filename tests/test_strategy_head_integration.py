from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionContract,
)
from options_app.api import create_app
from options_lib.opportunity_scanner import ScanRequest, ScanResult

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
QUOTE_TIME = datetime(2026, 9, 15, 11, 59, 30, tzinfo=UTC)


def option_contract(
    *,
    symbol: str = "BTC-25SEP26-100-C",
    option_type: str = "call",
    strike: float = 100.0,
    expiry_at: datetime = datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
) -> OptionContract:
    return OptionContract(
        asset="BTC",
        symbol=symbol,
        option_type=option_type,
        strike=strike,
        expiry_at=expiry_at,
        expiry_code="25SEP26",
        spot_price=100.0,
        mark_price=5.0,
        mark_iv=0.5,
        bid_price=4.0,
        ask_price=6.0,
        bid_iv=0.49,
        ask_iv=0.51,
        delta=0.4,
        gamma=0.01,
        theta=-0.01,
        vega=0.2,
        volume_24h=10.0,
        open_interest=20.0,
        quote_currency="USDC",
        settle_currency="USDC",
        quote_timestamp=QUOTE_TIME,
    )


class FakeAdapter:
    def __init__(self, contracts: tuple[OptionContract, ...] = ()) -> None:
        self.universe = NormalizedOptionUniverse(
            assets=(OptionAsset("BTC", "Trading", len(contracts)),),
            contracts=contracts,
            issues=(),
            valuation_time=VALUATION_TIME,
            source="fake-market",
        )

    async def discover_assets(self) -> Any:
        return self.universe.assets

    async def load_universe(
        self,
        assets: tuple[str, ...] | None = None,
        *,
        valuation_time: datetime | None = None,
    ) -> NormalizedOptionUniverse:
        return self.universe


class FakeHead:
    model_version = "fake-head-v1"

    def __init__(self, prediction: object) -> None:
        self.prediction = prediction
        self.features: dict[str, object] | None = None

    def predict(self, features: dict[str, object]) -> object:
        self.features = dict(features)
        return self.prediction


async def request(app: Any, payload: dict[str, Any]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/opportunities/scan", json=payload)


def empty_scan(
    universe: NormalizedOptionUniverse,
    scan_request: ScanRequest,
) -> ScanResult:
    return ScanResult(
        timestamp=universe.valuation_time,
        data_timestamp=QUOTE_TIME,
        opportunities=(),
        rejections=(),
        asset_failures=(),
        issues=universe.issues,
        valuation_mode=scan_request.valuation_mode,
    )


@pytest.mark.asyncio
async def test_default_scan_stays_manual_and_does_not_call_head() -> None:
    calls: list[ScanRequest] = []

    class MustNotRunHead:
        def predict(self, _features: dict[str, object]) -> object:
            raise AssertionError("manual mode must bypass the head")

    def scanner(universe: NormalizedOptionUniverse, scan_request: ScanRequest) -> ScanResult:
        calls.append(scan_request)
        return empty_scan(universe, scan_request)

    response = await request(
        create_app(
            adapter=FakeAdapter(),
            scanner=scanner,
            strategy_head=MustNotRunHead(),
        ),
        {"assets": ["BTC"], "strategies": ["long_put"]},
    )

    assert response.status_code == 200
    assert calls[0].strategies == ("long_put",)
    provenance = response.json()["head_provenance"]
    assert provenance["source"] == "manual"
    assert provenance["action"] == "select_strategies"
    assert provenance["selected_strategy_families"] == ["long_put"]
    assert provenance["execution_status"] == "not_executed"


@pytest.mark.asyncio
async def test_automatic_head_receives_point_in_time_features_and_limits_scanner() -> None:
    calls: list[ScanRequest] = []
    head = FakeHead(
        {
            "decision": "SELECT",
            "selected_strategies": ["long_put"],
            "scores": [
                {"strategy": "long_put", "score": 2.5},
                {"strategy": "long_call", "score": -1.0},
            ],
        }
    )

    def scanner(universe: NormalizedOptionUniverse, scan_request: ScanRequest) -> ScanResult:
        calls.append(scan_request)
        return empty_scan(universe, scan_request)

    response = await request(
        create_app(
            adapter=FakeAdapter(
                (
                    option_contract(),
                    option_contract(
                        symbol="BTC-05OCT26-100-P",
                        option_type="put",
                        expiry_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
                    ),
                )
            ),
            scanner=scanner,
            strategy_head=head,
        ),
        {
            "assets": ["BTC"],
            "strategies": ["long_call", "long_put"],
            "head_mode": "automatic",
        },
    )

    assert response.status_code == 200
    assert calls[0].strategies == ("long_put",)
    assert head.features is not None
    assert set(head.features) == {
        "underlying_price",
        "quote_count",
        "complete_quote_count",
        "executable_quote_count",
        "expiry_count",
        "mean_mark_iv",
        "mean_abs_delta",
        "mean_volume_24h",
        "mean_open_interest",
        "mean_spread_pct",
        "mean_dte_days",
        "min_dte_days",
        "max_dte_days",
    }
    assert head.features["underlying_price"] == pytest.approx(100.0)
    assert head.features["quote_count"] == pytest.approx(2.0)
    assert head.features["complete_quote_count"] == pytest.approx(2.0)
    assert head.features["executable_quote_count"] == pytest.approx(2.0)
    assert head.features["mean_dte_days"] == pytest.approx(15.0)
    assert head.features["min_dte_days"] == pytest.approx(10.0)
    assert head.features["max_dte_days"] == pytest.approx(20.0)
    provenance = response.json()["head_provenance"]
    assert provenance["source"] == "lightgbm"
    assert provenance["model_version"] == "fake-head-v1"
    assert provenance["ranked_strategies"][0] == {
        "strategy_family": "long_put",
        "rank": 1,
        "ranking_score": 2.5,
    }
    json.dumps(response.json(), allow_nan=False)


@pytest.mark.asyncio
async def test_no_trade_skips_scanner_and_returns_provenance() -> None:
    scanner_calls: list[bool] = []
    head = FakeHead({"action": "no_trade", "reason_codes": ["test_no_trade"]})

    def scanner(universe: NormalizedOptionUniverse, scan_request: ScanRequest) -> ScanResult:
        scanner_calls.append(True)
        return empty_scan(universe, scan_request)

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=scanner, strategy_head=head),
        {"assets": ["BTC"], "head_mode": "automatic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert scanner_calls == []
    assert body["opportunities"] == []
    assert body["head_provenance"]["action"] == "no_trade"
    assert body["head_provenance"]["selected_strategy_families"] == []
    assert body["head_provenance"]["execution_status"] == "not_executed"


@pytest.mark.asyncio
async def test_missing_model_path_uses_safe_fallback_without_crashing() -> None:
    calls: list[ScanRequest] = []

    def scanner(universe: NormalizedOptionUniverse, scan_request: ScanRequest) -> ScanResult:
        calls.append(scan_request)
        return empty_scan(universe, scan_request)

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=scanner),
        {
            "assets": ["BTC"],
            "strategies": ["long_call", "long_put"],
            "head_mode": "automatic",
            "head_model_path": "/tmp/does-not-exist-strategy-head.json",
        },
    )

    assert response.status_code == 200
    assert calls[0].strategies == ("long_call", "long_put")
    provenance = response.json()["head_provenance"]
    assert provenance["source"] == "fallback"
    assert "head_unavailable" in provenance["reason_codes"]
    assert "model_load_failed" in provenance["reason_codes"]


@pytest.mark.asyncio
async def test_signal_payload_is_json_safe_and_never_allows_order_placement() -> None:
    head = FakeHead(
        {
            "action": "select_strategies",
            "selected_strategy_families": ["long_call"],
            "ranked_strategies": [
                {"strategy_family": "long_call", "rank": 1, "ranking_score": 1.25}
            ],
        }
    )

    response = await request(
        create_app(adapter=FakeAdapter(), strategy_head=head),
        {"assets": ["BTC"], "head_mode": "automatic"},
    )

    assert response.status_code == 200
    body = response.json()
    json.dumps(body, allow_nan=False)
    assert body["execution_allowed"] is False
    assert body["head_provenance"]["execution_status"] == "not_executed"
    assert body["head_provenance"]["profit_guarantee"] is False
    assert "not an executed order" in body["head_provenance"]["disclaimer"]
