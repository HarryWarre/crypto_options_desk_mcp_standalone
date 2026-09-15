"""Read-only HTTP API for the multi-asset options opportunity scanner."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bybit_api.options_market_data import (
    BybitOptionMarketDataAdapter,
    NormalizedOptionUniverse,
    OptionAssetCatalog,
)
from options_lib.opportunity_scanner import ScanRequest, ScanResult, scan_opportunities
from options_lib.scenario_engine import (
    ExecutionAssumptions,
    MarketScenario,
    OptionLeg,
    ScenarioSet,
    ScenarioValidationError,
    StrategyDefinition,
    evaluate_scenarios,
)
from options_lib.volatility_surface import VolatilityObservation, build_volatility_surface


class ScannerAdapter(Protocol):
    async def discover_assets(self) -> OptionAssetCatalog: ...

    async def load_universe(
        self,
        assets: tuple[str, ...] | None = None,
        *,
        valuation_time: datetime | None = None,
    ) -> NormalizedOptionUniverse: ...


class ScanFilters(BaseModel):
    """Validated JSON filters accepted by the scan endpoint."""

    model_config = ConfigDict(extra="forbid")

    risk_free_rate: float
    assets: list[str] = Field(default_factory=list)
    min_dte: float | None = Field(default=None, ge=0)
    max_dte: float | None = Field(default=None, ge=0)
    min_delta: float | None = Field(default=None, ge=0, le=1)
    max_delta: float | None = Field(default=None, ge=0, le=1)
    min_volume_24h: float = Field(default=0, ge=0)
    min_open_interest: float = Field(default=0, ge=0)
    max_spread_pct: float | None = Field(default=None, ge=0, le=1)
    min_iv_edge: float = 0
    min_edge_after_costs: float = 0
    max_loss: float | None = Field(default=None, ge=0)
    fee_per_contract: float = Field(default=0, ge=0)
    slippage_bps: float = Field(default=0, ge=0)
    quantity: float = Field(default=1, gt=0)
    contract_multiplier: float = Field(default=1, gt=0)
    include_unvalidated: bool = True
    strategies: list[str] = Field(default_factory=lambda: ["long_call", "long_put"])
    max_results: int | None = Field(default=None, ge=1)

    @field_validator(
        "risk_free_rate",
        "min_dte",
        "max_dte",
        "min_delta",
        "max_delta",
        "min_volume_24h",
        "min_open_interest",
        "max_spread_pct",
        "min_iv_edge",
        "min_edge_after_costs",
        "max_loss",
        "fee_per_contract",
        "slippage_bps",
        "quantity",
        "contract_multiplier",
        mode="before",
    )
    @classmethod
    def finite_number(cls, value: Any) -> Any:
        if value is not None:
            try:
                finite = math.isfinite(float(value))
            except (TypeError, ValueError):
                finite = False
            if isinstance(value, bool) or not finite:
                raise ValueError("must be a finite number")
        return value

    @field_validator("assets")
    @classmethod
    def normalize_assets(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            asset = value.strip().upper()
            if not asset:
                raise ValueError("asset names cannot be empty")
            normalized.append(asset)
        return list(dict.fromkeys(normalized))

    @field_validator("strategies")
    @classmethod
    def validate_strategies(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip().lower() for value in values))
        allowed = {"long_call", "long_put"}
        unsupported = sorted(set(normalized) - allowed)
        if unsupported:
            raise ValueError(f"unsupported strategy: {', '.join(unsupported)}")
        if not normalized:
            raise ValueError("at least one strategy is required")
        return normalized

    @model_validator(mode="after")
    def validate_ranges(self) -> ScanFilters:
        if self.min_dte is not None and self.max_dte is not None and self.min_dte > self.max_dte:
            raise ValueError("min_dte cannot exceed max_dte")
        if self.min_delta is not None and self.max_delta is not None and self.min_delta > self.max_delta:
            raise ValueError("min_delta cannot exceed max_delta")
        return self

    def to_scan_request(self) -> ScanRequest:
        values = self.model_dump()
        values["assets"] = tuple(values["assets"])
        values["strategies"] = tuple(values["strategies"])
        return ScanRequest(**values)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class ScenarioLegRequest(BaseModel):
    """JSON representation of :class:`options_lib.scenario_engine.OptionLeg`."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    option_type: str = Field(min_length=1)
    strike: float = Field(gt=0)
    expiry: datetime
    valuation_time: datetime
    spot: float = Field(gt=0)
    iv: float = Field(gt=0)
    risk_free_rate: float
    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    position: int = 1
    surface: Any | None = None

    @field_validator(
        "strike",
        "spot",
        "iv",
        "risk_free_rate",
        "bid",
        "ask",
        mode="before",
    )
    @classmethod
    def finite_number(cls, value: Any) -> Any:
        if value is not None:
            try:
                finite = math.isfinite(float(value))
            except (TypeError, ValueError):
                finite = False
            if isinstance(value, bool) or not finite:
                raise ValueError("must be a finite number")
        return value

    @field_validator("surface")
    @classmethod
    def reject_json_surface(cls, value: Any) -> Any:
        if value is not None:
            raise ValueError("surface must be omitted or null in the HTTP request")
        return value

    def to_domain(self) -> OptionLeg:
        return OptionLeg(**self.model_dump())


class MarketScenarioRequest(BaseModel):
    """JSON representation of :class:`MarketScenario`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    underlying_move_pct: float = 0.0
    iv_move: float = 0.0
    elapsed_days: float = Field(default=0.0, ge=0)

    @field_validator("underlying_move_pct", "iv_move", "elapsed_days", mode="before")
    @classmethod
    def finite_number(cls, value: Any) -> Any:
        if value is not None:
            try:
                finite = math.isfinite(float(value))
            except (TypeError, ValueError):
                finite = False
            if isinstance(value, bool) or not finite:
                raise ValueError("must be a finite number")
        return value

    def to_domain(self) -> MarketScenario:
        return MarketScenario(**self.model_dump())


class ExecutionAssumptionsRequest(BaseModel):
    """JSON representation of :class:`ExecutionAssumptions`."""

    model_config = ConfigDict(extra="forbid")

    fee_per_contract: float = Field(default=0, ge=0)
    slippage_bps: float = Field(default=0, ge=0)
    contract_multiplier: float = Field(default=1, gt=0)
    exit_price_source: Literal["model", "bid_ask"] = "model"

    @field_validator(
        "fee_per_contract",
        "slippage_bps",
        "contract_multiplier",
        mode="before",
    )
    @classmethod
    def finite_number(cls, value: Any) -> Any:
        if value is not None:
            try:
                finite = math.isfinite(float(value))
            except (TypeError, ValueError):
                finite = False
            if isinstance(value, bool) or not finite:
                raise ValueError("must be a finite number")
        return value

    def to_domain(self) -> ExecutionAssumptions:
        return ExecutionAssumptions(**self.model_dump())


class ScenarioRequest(BaseModel):
    """Validated payload for one strategy scenario report."""

    model_config = ConfigDict(extra="forbid")

    strategy_type: Literal["long_call", "long_put", "call_vertical", "put_vertical"]
    legs: list[ScenarioLegRequest] = Field(min_length=1)
    scenarios: list[MarketScenarioRequest] = Field(min_length=1)
    execution: ExecutionAssumptionsRequest = Field(default_factory=ExecutionAssumptionsRequest)

    def to_domain(self) -> tuple[StrategyDefinition, ScenarioSet]:
        strategy = StrategyDefinition(
            strategy_type=self.strategy_type,
            legs=tuple(leg.to_domain() for leg in self.legs),
        )
        scenario_set = ScenarioSet(
            scenarios=tuple(scenario.to_domain() for scenario in self.scenarios),
            execution=self.execution.to_domain(),
        )
        return strategy, scenario_set


def create_app(
    adapter: ScannerAdapter | None = None,
    scanner: Callable[[NormalizedOptionUniverse, ScanRequest], ScanResult] = scan_opportunities,
) -> FastAPI:
    """Create the read-only scanner application with injectable boundaries."""

    market_adapter = adapter or BybitOptionMarketDataAdapter()
    app = FastAPI(title="Crypto Options Scanner API", version="0.1.0")
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "loc": list(error.get("loc", ())),
                "type": error.get("type", "validation_error"),
                "message": error.get("msg", "Invalid request"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "options-scanner-api"}

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return (static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/api/v1/assets")
    async def assets() -> JSONResponse:
        try:
            catalog = await _maybe_await(market_adapter.discover_assets())
        except Exception as exc:
            raise _upstream_error(exc) from exc
        return JSONResponse(content=_serialize(catalog))

    @app.post("/api/v1/opportunities/scan")
    async def scan(filters: ScanFilters) -> JSONResponse:
        scan_request = filters.to_scan_request()
        try:
            universe = await _maybe_await(
                market_adapter.load_universe(assets=scan_request.assets or None)
            )
        except Exception as exc:
            raise _upstream_error(exc) from exc
        try:
            result = await _maybe_await(scanner(universe, scan_request))
        except Exception as exc:
            raise ApiError(500, "scanner_failed", "Opportunity scan failed") from exc
        return JSONResponse(content=_serialize(result))

    @app.get("/api/v1/surfaces/{asset}")
    async def surface_summary(asset: str) -> JSONResponse:
        normalized_asset = asset.strip().upper()
        if not normalized_asset:
            raise ApiError(422, "validation_error", "asset cannot be empty")
        try:
            universe = await _maybe_await(
                market_adapter.load_universe(assets=(normalized_asset,))
            )
        except Exception as exc:
            raise _upstream_error(exc) from exc
        contracts = universe.contracts_by_asset.get(normalized_asset, ())
        if not contracts:
            raise ApiError(404, "asset_not_available", "No option quotes are available for this asset")
        observations = tuple(
            VolatilityObservation(
                asset=contract.asset,
                expiry=contract.expiry_at,
                strike=contract.strike,
                spot=contract.spot_price,
                iv=contract.mark_iv,
                bid=contract.bid_price,
                ask=contract.ask_price,
                liquidity=max(contract.volume_24h, contract.open_interest),
            )
            for contract in contracts
        )
        try:
            surface = build_volatility_surface(
                observations,
                valuation_time=universe.valuation_time,
            ).surface_for(normalized_asset)
        except (KeyError, ValueError) as exc:
            raise ApiError(422, "surface_invalid", str(exc)) from exc
        return JSONResponse(
            content=_serialize(
                {
                    "asset": normalized_asset,
                    "source": universe.source,
                    "valuation_time": universe.valuation_time,
                    "is_valuation_ready": surface.is_valuation_ready,
                    "front_expiry": surface.front_expiry,
                    "back_expiry": surface.back_expiry,
                    "observed_points": len(surface.observed_points),
                    "expiry_slices": surface.slices,
                    "warnings": surface.warnings,
                    "issues": tuple(issue for issue in universe.issues if issue.asset == normalized_asset),
                }
            )
        )

    @app.post("/api/v1/scenarios")
    async def scenario_report(request: ScenarioRequest) -> JSONResponse:
        strategy, scenario_set = request.to_domain()
        try:
            report = evaluate_scenarios(strategy, scenario_set)
        except ScenarioValidationError as exc:
            raise ApiError(422, "scenario_invalid", str(exc)) from exc
        return JSONResponse(content=_serialize(report))

    return app


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _upstream_error(exc: Exception) -> ApiError:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        return ApiError(504, "upstream_timeout", "Upstream market data request failed")
    return ApiError(502, "upstream_unavailable", "Upstream market data request failed")


def _serialize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _serialize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        # JSON has no representation for +/-Infinity or NaN.  ``null`` keeps
        # the report valid while preserving the fact that the bound is not a
        # finite number (for example, a long call's max profit).
        return None
    return value


__all__ = [
    "ExecutionAssumptionsRequest",
    "MarketScenarioRequest",
    "ScanFilters",
    "ScenarioLegRequest",
    "ScenarioRequest",
    "create_app",
]
