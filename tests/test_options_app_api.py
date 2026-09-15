from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionAssetCatalog,
    OptionContract,
    OptionDataQualityIssue,
)
from options_app.api import ScenarioRequest, create_app
from options_lib.opportunity_scanner import Opportunity, ScanResult

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
DATA_TIME = datetime(2026, 9, 15, 11, 59, 30, tzinfo=UTC)

SCENARIO_LEG = {
    "symbol": "BTC-30DEC26-78000-C",
    "option_type": "call",
    "strike": 78000,
    "expiry": "2026-12-30T12:00:00Z",
    "valuation_time": "2026-09-15T12:00:00Z",
    "spot": 78400,
    "iv": 0.31,
    "risk_free_rate": 0.05,
    "bid": 4200,
    "ask": 4300,
    "position": 1,
}
SCENARIO_SHORT_CALL_LEG = {
    **SCENARIO_LEG,
    "symbol": "BTC-30DEC26-80000-C",
    "strike": 80000,
    "bid": 1800,
    "ask": 1900,
    "position": -1,
}
SCENARIO_LONG_PUT_LEG = {
    **SCENARIO_LEG,
    "symbol": "BTC-30DEC26-80000-P",
    "option_type": "put",
    "strike": 80000,
    "bid": 5100,
    "ask": 5200,
}
SCENARIO_SHORT_PUT_LEG = {
    **SCENARIO_LEG,
    "symbol": "BTC-30DEC26-78000-P",
    "option_type": "put",
    "strike": 78000,
    "bid": 3500,
    "ask": 3600,
    "position": -1,
}


def scenario_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "strategy_type": "long_call",
        "legs": [SCENARIO_LEG],
        "scenarios": [
            {
                "name": "flat",
                "underlying_move_pct": 0,
                "iv_move": 0,
                "elapsed_days": 5,
            }
        ],
        "execution": {
            "fee_per_contract": 1.5,
            "slippage_bps": 5,
            "contract_multiplier": 1,
            "exit_price_source": "model",
        },
    }
    payload.update(overrides)
    return payload


class FakeAdapter:
    def __init__(
        self,
        *,
        catalog: OptionAssetCatalog | None = None,
        contracts: tuple[OptionContract, ...] = (),
    ) -> None:
        self.contracts = contracts
        self.catalog = catalog or OptionAssetCatalog(
            assets=(OptionAsset("BTC", "Trading", 2), OptionAsset("ETH", "Trading", 1)),
            issues=(
                OptionDataQualityIssue(
                    code="stale_quote",
                    message="quote is older than the configured limit",
                    asset="ETH",
                ),
            ),
            fetched_at=DATA_TIME,
        )
        self.load_calls: list[tuple[tuple[str, ...] | None, datetime | None]] = []

    async def discover_assets(self) -> OptionAssetCatalog:
        return self.catalog

    async def load_universe(
        self,
        assets: tuple[str, ...] | None = None,
        *,
        valuation_time: datetime | None = None,
    ) -> NormalizedOptionUniverse:
        self.load_calls.append((assets, valuation_time))
        return NormalizedOptionUniverse(
            assets=self.catalog.assets,
            contracts=self.contracts,
            issues=self.catalog.issues,
            valuation_time=VALUATION_TIME,
            source="fake-bybit",
        )


class FailingAdapter:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def discover_assets(self) -> OptionAssetCatalog:
        raise self.error

    async def load_universe(self, *args: Any, **kwargs: Any) -> NormalizedOptionUniverse:
        raise self.error


async def request(app, method: str, path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_health_and_root_are_read_only_service_endpoints() -> None:
    app = create_app(adapter=FakeAdapter())

    health = await request(app, "GET", "/api/v1/health")
    root = await request(app, "GET", "/")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "options-scanner-api"}
    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert "Crypto Options Scanner" in root.text


@pytest.mark.asyncio
async def test_cors_allows_local_frontend_preflight() -> None:
    response = await request(
        create_app(),
        "OPTIONS",
        "/api/v1/opportunities/scan",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.asyncio
async def test_assets_serializes_dataclasses_issues_and_fetched_timestamp() -> None:
    app = create_app(adapter=FakeAdapter())

    response = await request(app, "GET", "/api/v1/assets")

    assert response.status_code == 200
    assert response.json() == {
        "assets": [
            {"base_coin": "BTC", "status": "Trading", "contract_count": 2},
            {"base_coin": "ETH", "status": "Trading", "contract_count": 1},
        ],
        "issues": [
            {
                "code": "stale_quote",
                "message": "quote is older than the configured limit",
                "symbol": None,
                "asset": "ETH",
                "field": None,
            }
        ],
        "fetched_at": "2026-09-15T11:59:30Z",
    }


@pytest.mark.asyncio
async def test_surface_summary_returns_quality_checked_slices() -> None:
    expiry = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    contracts = tuple(
        OptionContract(
            asset="BTC",
            symbol=f"BTC-{strike}-{'C' if strike == 78000 else 'P'}",
            option_type="call" if strike == 78000 else "put",
            strike=strike,
            expiry_at=expiry,
            expiry_code="15OCT26",
            spot_price=78400,
            mark_price=1000,
            mark_iv=0.30 if strike == 78000 else 0.35,
            bid_price=900,
            ask_price=1100,
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
            quote_timestamp=DATA_TIME,
        )
        for strike in (78000, 80000)
    )
    app = create_app(adapter=FakeAdapter(contracts=contracts))

    response = await request(app, "GET", "/api/v1/surfaces/btc")

    assert response.status_code == 200
    body = response.json()
    assert body["asset"] == "BTC"
    assert body["is_valuation_ready"] is True
    assert body["observed_points"] == 2
    assert body["expiry_slices"][0]["expiry"] == "2026-10-15T12:00:00Z"


@pytest.mark.asyncio
async def test_surface_summary_returns_404_for_asset_without_quotes() -> None:
    response = await request(create_app(adapter=FakeAdapter()), "GET", "/api/v1/surfaces/sol")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "asset_not_available",
            "message": "No option quotes are available for this asset",
        }
    }


@pytest.mark.asyncio
async def test_scan_builds_typed_request_and_preserves_result_metadata() -> None:
    adapter = FakeAdapter()
    scan_calls: list[tuple[NormalizedOptionUniverse, Any]] = []

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        scan_calls.append((universe, scan_request))
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
            evidence_status="insufficient_evidence",
            evidence_gate_status="blocked_unvalidated",
            execution_allowed=False,
        )

    app = create_app(adapter=adapter, scanner=fake_scanner)
    response = await request(
        app,
        "POST",
        "/api/v1/opportunities/scan",
        json={
            "risk_free_rate": 0.075,
            "assets": ["btc", "ETH"],
            "min_dte": 2,
            "max_dte": 30,
            "strategies": ["long_put"],
            "include_unvalidated": False,
            "max_results": 10,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "timestamp": "2026-09-15T12:00:00Z",
        "data_timestamp": "2026-09-15T11:59:30Z",
        "opportunities": [],
        "rejections": [],
        "asset_failures": [],
        "issues": [
            {
                "code": "stale_quote",
                "message": "quote is older than the configured limit",
                "symbol": None,
                "asset": "ETH",
                "field": None,
            }
        ],
        "evidence_status": "insufficient_evidence",
        "evidence_gate_status": "blocked_unvalidated",
        "execution_allowed": False,
    }
    assert adapter.load_calls == [(('BTC', 'ETH'), None)]
    assert scan_calls[0][1].assets == ("BTC", "ETH")
    assert scan_calls[0][1].strategies == ("long_put",)
    assert scan_calls[0][1].risk_free_rate == pytest.approx(0.075)


@pytest.mark.asyncio
async def test_scan_uses_safe_default_rate_when_request_omits_risk_free_rate() -> None:
    scan_requests: list[Any] = []

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        scan_requests.append(scan_request)
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan",
        json={"assets": ["BTC"], "strategies": ["long_call"]},
    )

    assert response.status_code == 200
    assert scan_requests[0].risk_free_rate == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_scan_accepts_simple_market_view_and_horizon_request() -> None:
    scan_requests: list[Any] = []

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        scan_requests.append(scan_request)
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan",
        json={
            "assets": ["BTC"],
            "market_view": "up",
            "time_horizon": "7_30",
            "max_loss": 120,
            "strategy_preference": "long_call",
        },
    )

    assert response.status_code == 200
    assert scan_requests[0].assets == ("BTC",)
    assert scan_requests[0].strategies == ("long_call",)
    assert scan_requests[0].min_dte == pytest.approx(7)
    assert scan_requests[0].max_dte == pytest.approx(30)
    assert scan_requests[0].max_loss == pytest.approx(120)
    context = response.json()["scan_context"]
    assert context["market_view"] == "up"
    assert context["time_horizon"] == "7_30"
    assert context["max_loss"] == 120.0
    assert context["strategies"] == ["long_call"]
    assert context["assumptions"] == {
        "risk_free_rate": 0.05,
        "fee_per_contract": 0.0,
        "slippage_bps": 0.0,
        "quantity": 1.0,
        "contract_multiplier": 1.0,
        "include_unvalidated": True,
    }
    assert context["applied_filters"]["min_dte"] == 7.0
    assert context["applied_filters"]["max_dte"] == 30.0
    assert "lỗ tối đa 120" in context["summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("market_view", "strategies"),
    [
        ("down", ("long_put", "bear_put_vertical")),
        ("sideways", ("iron_condor", "iron_butterfly")),
    ],
)
async def test_scan_simple_market_views_resolve_bounded_risk_presets(
    market_view: str,
    strategies: tuple[str, ...],
) -> None:
    scan_requests: list[Any] = []

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        scan_requests.append(scan_request)
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan",
        json={
            "assets": ["BTC"],
            "market_view": market_view,
            "time_horizon": "30_90",
            "max_loss": 120,
        },
    )

    assert response.status_code == 200
    assert scan_requests[0].strategies == strategies
    assert scan_requests[0].min_dte == pytest.approx(30)
    assert scan_requests[0].max_dte == pytest.approx(90)


@pytest.mark.asyncio
async def test_scan_custom_view_preserves_multiple_selected_strategies() -> None:
    scan_requests: list[Any] = []

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        scan_requests.append(scan_request)
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan",
        json={
            "assets": ["BTC"],
            "market_view": "custom",
            "time_horizon": "7_30",
            "max_loss": 100,
            "strategies": ["long_straddle", "calendar_spread"],
        },
    )

    assert response.status_code == 200
    assert scan_requests[0].strategies == ("long_straddle", "calendar_spread")
    assert response.json()["scan_context"]["market_view"] == "custom"
    assert response.json()["scan_context"]["strategies"] == ["long_straddle", "calendar_spread"]


@pytest.mark.asyncio
async def test_scan_rejects_partial_simple_context() -> None:
    response = await request(
        create_app(adapter=FakeAdapter()),
        "POST",
        "/api/v1/opportunities/scan",
        json={"assets": ["BTC"], "market_view": "up"},
    )

    assert response.status_code == 422
    assert (
        "market_view and time_horizon must be provided together"
        in response.json()["error"]["details"][0]["message"]
    )


@pytest.mark.asyncio
async def test_scan_rejects_simple_request_without_max_loss() -> None:
    response = await request(
        create_app(adapter=FakeAdapter()),
        "POST",
        "/api/v1/opportunities/scan",
        json={"assets": ["BTC"], "market_view": "up", "time_horizon": "7_30"},
    )

    assert response.status_code == 422
    assert "max_loss is required for a simple scan" in str(response.json())


@pytest.mark.asyncio
async def test_scan_logs_progress_milestones(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan",
        json={"risk_free_rate": 0.05, "assets": ["BTC"], "strategies": ["long_call"]},
    )

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records]
    assert any("scan started" in message for message in messages)
    assert any("market data loaded" in message for message in messages)
    assert any("running opportunity scanner" in message for message in messages)
    assert any("scan completed" in message for message in messages)


@pytest.mark.asyncio
async def test_scan_stream_emits_progress_and_result_events() -> None:
    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan/stream",
        json={"risk_free_rate": 0.05, "assets": ["BTC"], "strategies": ["long_call"]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    messages = [event["message"] for event in events if event["type"] == "log"]
    assert any("scan started" in message for message in messages)
    assert any("market data loaded" in message for message in messages)
    assert events[-1]["type"] == "result"
    assert events[-1]["payload"]["opportunities"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "strategy",
    [
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
    ],
)
async def test_scan_endpoint_accepts_supported_multi_leg_strategy_identifiers(strategy: str) -> None:
    scan_requests: list[Any] = []

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        scan_requests.append(scan_request)
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan",
        json={"risk_free_rate": 0.05, "strategies": [strategy]},
    )

    assert response.status_code == 200
    assert scan_requests[0].strategies == (strategy,)


@pytest.mark.asyncio
async def test_scan_rejects_unsupported_strategy_with_structured_422() -> None:
    app = create_app(adapter=FakeAdapter())

    response = await request(
        app,
        "POST",
        "/api/v1/opportunities/scan",
        json={"risk_free_rate": 0.05, "strategies": ["short_call"]},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["body", "strategies"]
    assert "unsupported strategy: short_call" in body["error"]["details"][0]["message"]


@pytest.mark.asyncio
async def test_scan_serializes_multi_leg_opportunities_recursively() -> None:
    multi_leg = Opportunity(
        asset="BTC",
        symbol="BTC-30DEC26-78000-C",
        strategy="bull_call_vertical",
        option_type="call",
        strike=78000,
        expiry_at=datetime(2026, 12, 30, 12, 0, tzinfo=UTC),
        dte=106,
        spot_price=78400,
        bid_price=4200,
        ask_price=4300,
        market_mid=4250,
        market_iv=0.31,
        fair_iv=0.28,
        iv_edge=-0.03,
        surface_status="observed",
        fair_price=4000,
        executable_entry=2500,
        fee=2,
        slippage_cost=1,
        edge_after_costs=1497,
        edge_pct=0.5988,
        max_loss=2502,
        delta=0.5,
        volume_24h=10,
        open_interest=10,
        quote_timestamp=DATA_TIME,
        evidence_status="insufficient_evidence",
        max_profit=17498,
        long_symbol="BTC-30DEC26-78000-C",
        short_symbol="BTC-30DEC26-80000-C",
        long_strike=78000,
        short_strike=80000,
    )

    def fake_scanner(universe: NormalizedOptionUniverse, scan_request: Any) -> ScanResult:
        return ScanResult(
            timestamp=VALUATION_TIME,
            data_timestamp=DATA_TIME,
            opportunities=(multi_leg,),
            rejections=(),
            asset_failures=(),
            issues=universe.issues,
        )

    response = await request(
        create_app(adapter=FakeAdapter(), scanner=fake_scanner),
        "POST",
        "/api/v1/opportunities/scan",
        json={"risk_free_rate": 0.05, "strategies": ["long_call"]},
    )

    assert response.status_code == 200
    serialized = response.json()["opportunities"][0]
    assert serialized["strategy"] == "bull_call_vertical"
    assert serialized["max_profit"] == 17498
    assert serialized["long_symbol"] == "BTC-30DEC26-78000-C"
    assert serialized["short_symbol"] == "BTC-30DEC26-80000-C"
    assert serialized["long_strike"] == 78000
    assert serialized["short_strike"] == 80000


@pytest.mark.parametrize("strategy_type", ["iron_condor", "iron_butterfly"])
def test_scenario_request_preserves_iron_strategy_identifier(strategy_type: str) -> None:
    request_model = ScenarioRequest.model_validate(
        scenario_payload(strategy_type=strategy_type, legs=[SCENARIO_LEG])
    )

    strategy, _scenario_set = request_model.to_domain()

    assert strategy.strategy_type == strategy_type


@pytest.mark.asyncio
async def test_invalid_filters_return_structured_422() -> None:
    app = create_app(adapter=FakeAdapter())

    response = await request(
        app,
        "POST",
        "/api/v1/opportunities/scan",
        json={"risk_free_rate": 0.05, "min_dte": 30, "max_dte": 2},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed"
    assert body["error"]["details"]


@pytest.mark.asyncio
async def test_invalid_numeric_type_returns_structured_422_instead_of_500() -> None:
    app = create_app(adapter=FakeAdapter())

    response = await request(
        app,
        "POST",
        "/api/v1/opportunities/scan",
        json={"risk_free_rate": 0, "min_dte": {}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_scenario_endpoint_returns_serialized_report() -> None:
    app = create_app(adapter=FakeAdapter())

    response = await request(app, "POST", "/api/v1/scenarios", json=scenario_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "model_only"
    assert body["max_profit"] is None
    assert body["scenarios"][0]["name"] == "flat"
    assert body["scenarios"][0]["elapsed_days"] == 5
    assert "delta" in body["scenarios"][0]["greeks"]
    assert {warning["code"] for warning in body["warnings"]} >= {
        "model_only",
        "execution_costs",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy_type", "legs"),
    [
        ("call_vertical", [SCENARIO_LEG, SCENARIO_SHORT_CALL_LEG]),
        ("put_vertical", [SCENARIO_LONG_PUT_LEG, SCENARIO_SHORT_PUT_LEG]),
        ("bear_call_vertical", [{**SCENARIO_SHORT_CALL_LEG, "position": 1}, {**SCENARIO_LEG, "position": -1}]),
        ("bull_put_vertical", [{**SCENARIO_SHORT_PUT_LEG, "position": 1}, {**SCENARIO_LONG_PUT_LEG, "position": -1}]),
    ],
)
async def test_scenario_vertical_request_identifiers_remain_stable(
    strategy_type: str,
    legs: list[dict[str, Any]],
) -> None:
    app = create_app(adapter=FakeAdapter())

    response = await request(
        app,
        "POST",
        "/api/v1/scenarios",
        json=scenario_payload(strategy_type=strategy_type, legs=legs),
    )

    assert response.status_code == 200
    assert response.json()["scenarios"][0]["name"] == "flat"


@pytest.mark.asyncio
async def test_scenario_invalid_strategy_returns_structured_validation_422() -> None:
    app = create_app(adapter=FakeAdapter())
    payload = scenario_payload(strategy_type="short_call")

    response = await request(app, "POST", "/api/v1/scenarios", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"expiry": "not-a-datetime"},
        {"spot": "not-a-number"},
        {"iv": "NaN"},
    ],
)
async def test_scenario_invalid_datetime_or_numeric_returns_structured_422(
    change: dict[str, Any],
) -> None:
    app = create_app(adapter=FakeAdapter())
    leg = {**SCENARIO_LEG, **change}

    response = await request(
        app,
        "POST",
        "/api/v1/scenarios",
        json=scenario_payload(legs=[leg]),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed"
    assert body["error"]["details"]


@pytest.mark.asyncio
async def test_scenario_domain_error_returns_stable_422() -> None:
    app = create_app(adapter=FakeAdapter())
    leg = {**SCENARIO_LEG, "position": -1}

    response = await request(
        app,
        "POST",
        "/api/v1/scenarios",
        json=scenario_payload(legs=[leg]),
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "scenario_invalid",
            "message": "single-leg strategy must contain one long leg",
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (TimeoutError("Bybit timed out"), 504, "upstream_timeout"),
        (RuntimeError("Bybit unavailable"), 502, "upstream_unavailable"),
    ],
)
async def test_adapter_failures_have_stable_gateway_errors(
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    app = create_app(adapter=FailingAdapter(error))

    path = "/api/v1/assets" if code == "upstream_unavailable" else "/api/v1/opportunities/scan"
    kwargs = {} if path.endswith("assets") else {"json": {"risk_free_rate": 0.05}}
    response = await request(app, "GET" if path.endswith("assets") else "POST", path, **kwargs)

    assert response.status_code == status_code
    assert response.json() == {
        "error": {
            "code": code,
            "message": "Upstream market data request failed",
        }
    }
