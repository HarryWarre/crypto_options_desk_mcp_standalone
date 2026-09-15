from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from bybit_api.options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionAssetCatalog,
    OptionDataQualityIssue,
)
from options_app.api import create_app
from options_lib.opportunity_scanner import ScanResult

VALUATION_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
DATA_TIME = datetime(2026, 9, 15, 11, 59, 30, tzinfo=UTC)


class FakeAdapter:
    def __init__(self, *, catalog: OptionAssetCatalog | None = None) -> None:
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
            contracts=(),
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
            "risk_free_rate": 0.05,
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
    assert scan_calls[0][1].risk_free_rate == pytest.approx(0.05)


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
