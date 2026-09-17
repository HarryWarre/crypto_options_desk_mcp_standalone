"""Read-only HTTP API for the multi-asset options opportunity scanner."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bybit_api.option_history import JsonlOptionSnapshotArchive
from bybit_api.option_volatility_history import BybitHistoricalVolatilityContextLoader
from bybit_api.options_market_data import (
    BybitOptionMarketDataAdapter,
    NormalizedOptionUniverse,
    OptionAssetCatalog,
)
from bybit_api.public import BybitPublicClient
from options_lib.backtest_engine import (
    BacktestDataUnavailable,
    BacktestResult,
    BacktestRunConfig,
    ExitPolicy,
    run_snapshot_backtest,
)
from options_lib.ev_validation import ValidationConfig
from options_lib.historical_volatility import (
    HistoricalVolatilityContext,
    HistoricalVolatilityContexts,
)
from options_lib.opportunity_scanner import (
    HistoricalContextScanResult,
    ScanRequest,
    ScanResult,
    scan_opportunities,
)
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
from position_monitoring.models import ExitPolicy as PositionExitPolicy

logger = logging.getLogger("uvicorn.error")

_VERTICAL_SCAN_STRATEGIES = frozenset(
    {
        "bull_call_vertical",
        "bear_call_vertical",
        "bull_put_vertical",
        "bear_put_vertical",
    }
)
_STRUCTURED_SCAN_STRATEGIES = frozenset(
    {
        "long_straddle",
        "long_strangle",
        "protective_put",
        "covered_call",
        "calendar_spread",
        "butterfly",
        "broken_wing_butterfly",
    }
)
_SUPPORTED_SCAN_STRATEGIES = (
    frozenset({"long_call", "long_put", "iron_condor", "iron_butterfly"})
    | _VERTICAL_SCAN_STRATEGIES
    | _STRUCTURED_SCAN_STRATEGIES
)
_SIMPLE_VIEW_STRATEGIES = {
    "up": ("long_call", "bull_call_vertical"),
    "down": ("long_put", "bear_put_vertical"),
    "sideways": ("iron_condor", "iron_butterfly"),
}
_SIMPLE_HORIZONS = {
    "0_7": (0.0, 7.0),
    "7_30": (7.0, 30.0),
    "30_90": (30.0, 90.0),
}
_LOCAL_FRONTEND_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
_CORS_ORIGINS_ENV = "OPTIONS_APP_CORS_ORIGINS"
_BACKTEST_ARCHIVE_ENV = "OPTIONS_BACKTEST_ARCHIVE"
_DEFAULT_SCAN_RISK_FREE_RATE = 0.05
_DEFAULT_MIN_EXPECTED_VALUE = 0.0
_LIVE_SCAN_INTERVAL_SECONDS = 8.0

# The scanner gained EV metrics after the original HTTP contract.  Keep the
# API tolerant of either spelling while the domain slices land independently.
# In particular, none of these aliases point at ``iv_edge``: IV edge is a
# surface-pricing signal, not an expected-value estimate.
_OPPORTUNITY_METRIC_ALIASES = {
    "expected_value": ("expected_value",),
    "win_probability": ("win_probability", "probability_of_profit", "win_rate"),
    "risk_reward": ("risk_reward", "risk_reward_ratio"),
    "payoff_curve": ("payoff_curve",),
    "methodology": (
        "methodology",
        "payoff_metrics_methodology",
        "metrics_methodology",
        "expected_value_methodology",
    ),
    "metrics_status": ("metrics_status", "payoff_metrics_status", "expected_value_status"),
    "risk_reward_status": ("risk_reward_status",),
    "assumptions": ("assumptions", "payoff_metrics_assumptions"),
    "limitations": ("limitations", "payoff_metrics_limitations"),
}


class ScannerAdapter(Protocol):
    async def discover_assets(self) -> OptionAssetCatalog: ...

    async def load_universe(
        self,
        assets: tuple[str, ...] | None = None,
        *,
        valuation_time: datetime | None = None,
    ) -> NormalizedOptionUniverse: ...


class HistoricalVolatilityLoader(Protocol):
    async def load(
        self,
        assets: tuple[str, ...],
        *,
        as_of: datetime | None = None,
    ) -> HistoricalVolatilityContexts: ...


ProgressCallback = Callable[[str], Awaitable[None]]


class ScanFilters(BaseModel):
    """Validated JSON filters accepted by the scan endpoint."""

    model_config = ConfigDict(extra="forbid")

    risk_free_rate: float = _DEFAULT_SCAN_RISK_FREE_RATE
    assets: list[str] = Field(default_factory=list)
    valuation_mode: Literal["executable", "theoretical", "synthetic"] = "executable"
    market_view: Literal["up", "down", "sideways", "custom"] | None = None
    time_horizon: Literal["0_7", "7_30", "30_90"] | None = None
    strategy_preference: (
        Literal[
            "long_call",
            "long_put",
            "bull_call_vertical",
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
        ]
        | None
    ) = None
    min_dte: float | None = Field(default=None, ge=0)
    max_dte: float | None = Field(default=None, ge=0)
    min_delta: float | None = Field(default=None, ge=0, le=1)
    max_delta: float | None = Field(default=None, ge=0, le=1)
    min_volume_24h: float = Field(default=0, ge=0)
    min_open_interest: float = Field(default=0, ge=0)
    max_spread_pct: float | None = Field(default=None, ge=0, le=1)
    min_iv_edge: float = 0
    min_edge_after_costs: float = 0
    min_expected_value: float | None = Field(default=_DEFAULT_MIN_EXPECTED_VALUE, ge=0)
    max_loss: float | None = Field(default=None, ge=0)
    fee_per_contract: float = Field(default=0, ge=0)
    slippage_bps: float = Field(default=0, ge=0)
    assumed_spread_bps: float = Field(default=100, ge=0, le=20_000)
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
        "min_expected_value",
        "max_loss",
        "fee_per_contract",
        "slippage_bps",
        "assumed_spread_bps",
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
        unsupported = sorted(set(normalized) - _SUPPORTED_SCAN_STRATEGIES)
        if unsupported:
            raise ValueError(f"unsupported strategy: {', '.join(unsupported)}")
        if not normalized:
            raise ValueError("at least one strategy is required")
        return normalized

    @model_validator(mode="after")
    def validate_ranges(self) -> ScanFilters:
        if (self.market_view is None) != (self.time_horizon is None):
            raise ValueError("market_view and time_horizon must be provided together")
        if self.market_view is not None:
            if not self.assets:
                raise ValueError("at least one asset is required for a simple scan")
            if self.max_loss is None and self.valuation_mode in {"executable", "synthetic"}:
                raise ValueError("max_loss is required for a simple scan")
        if self.min_dte is not None and self.max_dte is not None and self.min_dte > self.max_dte:
            raise ValueError("min_dte cannot exceed max_dte")
        if (
            self.min_delta is not None
            and self.max_delta is not None
            and self.min_delta > self.max_delta
        ):
            raise ValueError("min_delta cannot exceed max_delta")
        return self

    def to_scan_request(self) -> ScanRequest:
        values = self.model_dump(
            exclude={
                "market_view",
                "time_horizon",
                "strategy_preference",
                # Older scanner versions have no EV filter.  The API applies
                # it to their returned opportunities below instead.
                "min_expected_value",
            }
        )
        if self.market_view is not None:
            values["strategies"] = (
                (self.strategy_preference,)
                if self.strategy_preference is not None
                else values["strategies"]
                if self.market_view == "custom"
                else _SIMPLE_VIEW_STRATEGIES[self.market_view]
            )
            horizon_min, horizon_max = _SIMPLE_HORIZONS[self.time_horizon or "7_30"]
            if self.min_dte is None:
                values["min_dte"] = horizon_min
            if self.max_dte is None:
                values["max_dte"] = horizon_max
        values["assets"] = tuple(values["assets"])
        values["strategies"] = tuple(values["strategies"])
        if "min_expected_value" in {field.name for field in fields(ScanRequest)}:
            values["min_expected_value"] = self.min_expected_value
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

    strategy_type: Literal[
        "long_call",
        "long_put",
        "call_vertical",
        "put_vertical",
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
    ]
    legs: list[ScenarioLegRequest] = Field(min_length=1)
    scenarios: list[MarketScenarioRequest] = Field(min_length=1)
    execution: ExecutionAssumptionsRequest = Field(default_factory=ExecutionAssumptionsRequest)

    def to_domain(self) -> tuple[StrategyDefinition, ScenarioSet]:
        strategy_type = self.strategy_type
        strategy = StrategyDefinition(
            strategy_type=strategy_type,
            legs=tuple(leg.to_domain() for leg in self.legs),
        )
        scenario_set = ScenarioSet(
            scenarios=tuple(scenario.to_domain() for scenario in self.scenarios),
            execution=self.execution.to_domain(),
        )
        return strategy, scenario_set


class BacktestExitPolicyRequest(BaseModel):
    """Exit rules evaluated against future archived quotes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "hold_to_expiry",
        "profit_target",
        "stop_loss",
        "min_dte",
        "end_of_test",
    ] = "hold_to_expiry"
    profit_target_pct: float = Field(default=0.5, ge=0)
    stop_loss_pct: float = Field(default=1.0, ge=0)
    min_dte: float = Field(default=3.0, ge=0)

    @field_validator("profit_target_pct", "stop_loss_pct", "min_dte", mode="before")
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

    @model_validator(mode="after")
    def validate_for_type(self) -> BacktestExitPolicyRequest:
        if self.type == "profit_target" and self.profit_target_pct <= 0:
            raise ValueError("profit_target_pct must be positive for profit_target")
        if self.type == "stop_loss" and self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct must be positive for stop_loss")
        return self

    def to_domain(self) -> ExitPolicy:
        return ExitPolicy(**self.model_dump())


class BacktestRequest(BaseModel):
    """Request for a historical, quote-replay options backtest."""

    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    filters: ScanFilters = Field(default_factory=ScanFilters)
    exit_policy: BacktestExitPolicyRequest = Field(default_factory=BacktestExitPolicyRequest)
    signal_interval_minutes: float = Field(default=60.0, gt=0)
    max_signals_per_snapshot: int = Field(default=5, ge=1, le=100)
    holdout_fraction: float = Field(default=0.3, gt=0, lt=1)
    minimum_train_samples: int = Field(default=30, ge=0)
    minimum_holdout_samples: int = Field(default=30, ge=1)
    cost_sensitivity_multipliers: list[float] = Field(default_factory=lambda: [1.0, 2.0, 5.0])

    @field_validator(
        "signal_interval_minutes",
        "holdout_fraction",
        "cost_sensitivity_multipliers",
        mode="before",
    )
    @classmethod
    def finite_numbers(cls, value: Any) -> Any:
        values = value if isinstance(value, list) else [value]
        for item in values:
            try:
                finite = math.isfinite(float(item))
            except (TypeError, ValueError):
                finite = False
            if isinstance(item, bool) or not finite:
                raise ValueError("must contain only finite numbers")
        return value

    @field_validator("assets")
    @classmethod
    def normalize_assets(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if any(not value for value in normalized):
            raise ValueError("asset names cannot be empty")
        return list(dict.fromkeys(normalized))

    @field_validator("cost_sensitivity_multipliers")
    @classmethod
    def validate_cost_sensitivity(cls, values: list[float]) -> list[float]:
        if not values or any(value <= 0 for value in values):
            raise ValueError("cost_sensitivity_multipliers must be positive")
        return values

    @model_validator(mode="after")
    def validate_range(self) -> BacktestRequest:
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware")
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self

    def to_domain(self, archive_path: Path) -> BacktestRunConfig:
        filters = self.filters.model_copy(update={"assets": self.assets})
        return BacktestRunConfig(
            archive=JsonlOptionSnapshotArchive(archive_path),
            start_time=self.start_time,
            end_time=self.end_time,
            assets=tuple(self.assets),
            scan_request=filters.to_scan_request(),
            exit_policy=self.exit_policy.to_domain(),
            signal_interval=timedelta(minutes=self.signal_interval_minutes),
            max_signals_per_snapshot=self.max_signals_per_snapshot,
            validation=ValidationConfig(
                holdout_fraction=self.holdout_fraction,
                minimum_train_samples=self.minimum_train_samples,
                minimum_holdout_samples=self.minimum_holdout_samples,
                cost_sensitivity_multipliers=tuple(self.cost_sensitivity_multipliers),
                lookahead_verified=True,
            ),
        )


class PositionMonitoringPolicyRequest(BaseModel):
    """One optional manual policy supplied to the position-monitoring UI."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    stop_loss_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    max_loss_amount: float | None = Field(default=None, gt=0)
    max_loss_pct: float | None = Field(default=None, gt=0, le=1)
    risk_budget: float | None = Field(default=None, gt=0)
    max_holding_hours: float | None = Field(default=None, gt=0)
    min_liquidation_distance_pct: float | None = Field(default=None, gt=0, le=1)
    thesis_status: Literal["valid", "invalid", "unknown"] = "unknown"
    opened_at: datetime | None = None
    policy_id: str | None = None

    def to_domain(self) -> PositionExitPolicy:
        return PositionExitPolicy(**self.model_dump())


class PositionMonitoringRequest(BaseModel):
    """Validated request for a read-only current-position monitoring pass."""

    model_config = ConfigDict(extra="forbid")

    base_coin: str = Field(default="BTC", min_length=1)
    position_type: Literal["option", "linear", "inverse", "all"] = "all"
    policies: list[PositionMonitoringPolicyRequest] = Field(default_factory=list)
    persist: bool = True

    @field_validator("base_coin")
    @classmethod
    def normalize_base_coin(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("base_coin cannot be empty")
        return normalized


def create_app(
    adapter: ScannerAdapter | None = None,
    scanner: Callable[[NormalizedOptionUniverse, ScanRequest], ScanResult] = scan_opportunities,
    historical_volatility_loader: HistoricalVolatilityLoader | None = None,
    backtest_runner: Callable[[BacktestRequest], Any] | None = None,
    monitoring_runner: Callable[[PositionMonitoringRequest], Any] | None = None,
    monitoring_stream_factory: Callable[[PositionMonitoringRequest], Any] | None = None,
    live_scan_interval_seconds: float = _LIVE_SCAN_INTERVAL_SECONDS,
) -> FastAPI:
    """Create the read-only scanner application with injectable boundaries."""

    if not math.isfinite(live_scan_interval_seconds) or live_scan_interval_seconds < 0:
        raise ValueError("live_scan_interval_seconds must be a finite non-negative number")

    if adapter is None:
        public_client = BybitPublicClient()
        market_adapter = BybitOptionMarketDataAdapter(client=public_client)
        history_loader = historical_volatility_loader or BybitHistoricalVolatilityContextLoader(
            public_client.get_historical_volatility
        )
    else:
        market_adapter = adapter
        history_loader = historical_volatility_loader
    run_backtest = backtest_runner or _default_backtest_runner
    run_monitoring = monitoring_runner or _default_monitoring_runner
    build_monitoring_stream = monitoring_stream_factory or _default_monitoring_stream
    app = FastAPI(title="Crypto Options Scanner API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_from_environment(),
        allow_origin_regex=_LOCAL_FRONTEND_ORIGIN_REGEX,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
        max_age=600,
    )
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
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
    async def root() -> HTMLResponse:
        return HTMLResponse(
            content=(static_dir / "index.html").read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/assets")
    async def assets() -> JSONResponse:
        started_at = time.perf_counter()
        logger.info("[OPTIONS] asset discovery started")
        try:
            catalog = await _maybe_await(market_adapter.discover_assets())
        except Exception as exc:
            logger.exception("[OPTIONS] asset discovery failed")
            raise _upstream_error(exc) from exc
        logger.info(
            "[OPTIONS] asset discovery completed assets=%d issues=%d elapsed=%.2fs",
            len(catalog.assets),
            len(catalog.issues),
            time.perf_counter() - started_at,
        )
        return JSONResponse(content=_serialize(catalog))

    @app.post("/api/v1/opportunities/scan")
    async def scan(filters: ScanFilters) -> JSONResponse:
        scan_request = filters.to_scan_request()
        result = await _execute_scan(
            scan_request,
            market_adapter,
            scanner,
            historical_volatility_loader=history_loader,
        )
        return JSONResponse(content=_serialize_scan_result(result, filters, scan_request))

    @app.post("/api/v1/opportunities/scan/stream")
    async def scan_stream(filters: ScanFilters) -> StreamingResponse:
        scan_request = filters.to_scan_request()

        async def events() -> Any:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def on_progress(message: str) -> None:
                await queue.put({"type": "log", "message": message})

            scan_task = asyncio.create_task(
                _execute_scan(
                    scan_request,
                    market_adapter,
                    scanner,
                    historical_volatility_loader=history_loader,
                    on_progress=on_progress,
                )
            )
            try:
                while not scan_task.done() or not queue.empty():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.25)
                    except TimeoutError:
                        continue
                    yield _ndjson_line(event)
                result = await scan_task
                yield _ndjson_line(
                    {
                        "type": "result",
                        "payload": _serialize_scan_result(result, filters, scan_request),
                    }
                )
            except ApiError as exc:
                yield _ndjson_line({"type": "error", "code": exc.code, "message": exc.message})
            except asyncio.CancelledError:
                scan_task.cancel()
                raise
            except Exception:
                logger.exception("[OPTIONS] scan stream failed")
                yield _ndjson_line(
                    {"type": "error", "code": "scan_failed", "message": "Opportunity scan failed"}
                )
            finally:
                if not scan_task.done():
                    scan_task.cancel()

        return StreamingResponse(
            events(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.websocket("/api/v1/opportunities/stream")
    async def live_opportunity_stream(websocket: WebSocket) -> None:
        """Stream timestamped scanner snapshots to the live desk.

        The browser never talks to Bybit directly.  Each bounded refresh uses
        the same adapter and ranking path as the one-shot scanner, which keeps
        the live view auditable and avoids creating a second pricing contract.
        """

        await websocket.accept()
        try:
            filters = ScanFilters.model_validate(await websocket.receive_json())
            scan_request = filters.to_scan_request()
            await websocket.send_json(
                {
                    "type": "stream_status",
                    "status": "starting",
                    "interval_seconds": live_scan_interval_seconds,
                    "execution_allowed": False,
                }
            )

            while True:
                async def on_progress(message: str) -> None:
                    await websocket.send_json({"type": "log", "message": message})

                snapshot = await _execute_scan(
                    scan_request,
                    market_adapter,
                    scanner,
                    historical_volatility_loader=history_loader,
                    on_progress=on_progress,
                )
                await websocket.send_json(
                    {
                        "type": "snapshot",
                        "payload": _serialize_scan_result(snapshot, filters, scan_request),
                        "execution_allowed": False,
                    }
                )
                await websocket.send_json(
                    {
                        "type": "stream_status",
                        "status": "connected",
                        "interval_seconds": live_scan_interval_seconds,
                        "execution_allowed": False,
                    }
                )
                await asyncio.sleep(live_scan_interval_seconds)
        except WebSocketDisconnect:
            return
        except (TypeError, ValueError) as exc:
            await websocket.send_json(
                {"type": "error", "code": "live_scan_invalid", "message": str(exc)}
            )
            await websocket.close(code=1008)
        except ApiError as exc:
            await websocket.send_json(
                {"type": "error", "code": exc.code, "message": exc.message}
            )
            await websocket.close(code=1011)
        except Exception:
            logger.exception("[OPTIONS] live opportunity stream failed")
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "live_scan_failed",
                        "message": "Live opportunity stream failed",
                    }
                )
                await websocket.close(code=1011)
            except Exception:
                logger.debug("Could not send the live opportunity error envelope", exc_info=True)

    @app.get("/api/v1/surfaces/{asset}")
    async def surface_summary(asset: str) -> JSONResponse:
        normalized_asset = asset.strip().upper()
        if not normalized_asset:
            raise ApiError(422, "validation_error", "asset cannot be empty")
        try:
            universe = await _maybe_await(market_adapter.load_universe(assets=(normalized_asset,)))
        except Exception as exc:
            raise _upstream_error(exc) from exc
        contracts = universe.contracts_by_asset.get(normalized_asset, ())
        if not contracts:
            raise ApiError(
                404, "asset_not_available", "No option quotes are available for this asset"
            )
        observations = tuple(
            VolatilityObservation(
                asset=contract.asset,
                expiry=contract.expiry_at,
                strike=contract.strike,
                spot=contract.spot_price,
                iv=contract.mark_iv,
                bid=(
                    contract.bid_price
                    if contract.bid_price is not None and contract.bid_price > 0
                    else None
                ),
                ask=(
                    contract.ask_price
                    if contract.ask_price is not None and contract.ask_price > 0
                    else None
                ),
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
                    "issues": tuple(
                        issue for issue in universe.issues if issue.asset == normalized_asset
                    ),
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

    @app.post("/api/v1/backtests")
    async def backtest(request: BacktestRequest) -> JSONResponse:
        try:
            result = await _maybe_await(run_backtest(request))
        except BacktestDataUnavailable as exc:
            raise ApiError(422, "backtest_data_unavailable", str(exc)) from exc
        except (FileNotFoundError, OSError) as exc:
            raise ApiError(422, "backtest_data_unavailable", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(422, "backtest_invalid", str(exc)) from exc
        except Exception as exc:
            logger.exception("[OPTIONS] backtest failed")
            raise ApiError(500, "backtest_failed", "Backtest failed") from exc
        payload = _serialize(result)
        if isinstance(result, BacktestResult) and isinstance(payload, dict):
            payload["equity_curve"] = _serialize(result.equity_curve)
        return JSONResponse(content=payload)

    @app.post("/api/v1/positions/monitor")
    async def monitor_positions(request: PositionMonitoringRequest) -> JSONResponse:
        """Return current positions and manual-review decisions without mutating orders."""

        try:
            result = await _maybe_await(run_monitoring(request))
        except (TypeError, ValueError) as exc:
            raise ApiError(422, "position_monitoring_invalid", str(exc)) from exc
        except Exception as exc:
            logger.exception("[OPTIONS] position monitoring failed")
            raise ApiError(500, "position_monitoring_failed", "Position monitoring failed") from exc
        return JSONResponse(content=_serialize(result))

    @app.websocket("/api/v1/positions/stream")
    async def monitor_position_stream(websocket: WebSocket) -> None:
        """Stream sanitized monitoring snapshots to the browser."""

        await websocket.accept()
        try:
            request = PositionMonitoringRequest.model_validate(await websocket.receive_json())
            session = await _maybe_await(build_monitoring_stream(request))
            await websocket.send_json(
                {
                    "type": "stream_status",
                    "status": "starting",
                    "execution_allowed": False,
                }
            )
            async for event in session.events():
                await websocket.send_json(_serialize(event))
        except WebSocketDisconnect:
            return
        except (TypeError, ValueError) as exc:
            await websocket.send_json(
                {"type": "error", "code": "position_monitoring_invalid", "message": str(exc)}
            )
            await websocket.close(code=1008)
        except Exception:
            logger.exception("[OPTIONS] live position monitoring failed")
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "position_monitoring_failed",
                        "message": "Position monitoring stream failed",
                    }
                )
                await websocket.close(code=1011)
            except Exception:
                logger.debug("Could not send the live monitoring error envelope", exc_info=True)

    return app


def _default_backtest_runner(request: BacktestRequest) -> Any:
    archive_value = os.getenv(_BACKTEST_ARCHIVE_ENV, "").strip()
    if not archive_value:
        raise BacktestDataUnavailable(
            f"historical archive is not configured; set {_BACKTEST_ARCHIVE_ENV} to a JSONL snapshot archive"
        )
    return run_snapshot_backtest(request.to_domain(Path(archive_value)))


async def _default_monitoring_runner(request: PositionMonitoringRequest) -> Any:
    """Bridge the web workspace to the existing MCP monitor lazily."""

    from mcp_trading.orchestrator import get_orchestrator

    return await get_orchestrator().monitor_positions(
        request.base_coin,
        request.position_type,
        [policy.to_domain() for policy in request.policies],
        request.persist,
    )


def _default_monitoring_stream(request: PositionMonitoringRequest) -> Any:
    """Build the server-owned Bybit private-stream session lazily."""

    from mcp_trading.orchestrator import get_orchestrator
    from position_monitoring import (
        BybitPositionSnapshotAdapter,
        BybitPrivateWebSocket,
        LiveMonitoringSession,
        PositionTracker,
    )

    orchestrator = get_orchestrator()
    adapter = BybitPositionSnapshotAdapter(orchestrator.api)
    policies: dict[str, PositionExitPolicy] = {}
    for policy in request.policies:
        domain_policy = policy.to_domain()
        if domain_policy.symbol in policies:
            raise ValueError(f"Duplicate exit policy for {domain_policy.symbol}")
        policies[domain_policy.symbol] = domain_policy
    return LiveMonitoringSession(
        adapter=adapter,
        tracker=PositionTracker(adapter),
        stream=BybitPrivateWebSocket.from_client(orchestrator.api),
        history=orchestrator.position_snapshot_history,
        base_coin=request.base_coin,
        position_type=request.position_type,
        policies=policies,
        persist=request.persist,
    )


async def _execute_scan(
    scan_request: ScanRequest,
    market_adapter: ScannerAdapter,
    scanner: Callable[[NormalizedOptionUniverse, ScanRequest], ScanResult],
    *,
    historical_volatility_loader: HistoricalVolatilityLoader | None = None,
    on_progress: ProgressCallback | None = None,
) -> HistoricalContextScanResult:
    started_at = time.perf_counter()
    selected_assets = ",".join(scan_request.assets) if scan_request.assets else "all"

    async def progress(message: str) -> None:
        logger.info(message)
        if on_progress is not None:
            await on_progress(message)

    await progress(
        f"[OPTIONS] scan started assets={selected_assets} "
        f"strategies={','.join(scan_request.strategies)}"
    )
    await progress("[OPTIONS] loading market data")
    try:
        universe = await _maybe_await(
            market_adapter.load_universe(assets=scan_request.assets or None)
        )
    except Exception as exc:
        logger.exception("[OPTIONS] market data loading failed")
        await progress(f"[OPTIONS] market data loading failed: {exc}")
        raise _upstream_error(exc) from exc
    await progress(
        "[OPTIONS] market data loaded "
        f"assets={len(universe.assets)} contracts={len(universe.contracts)} "
        f"issues={len(universe.issues)} elapsed={time.perf_counter() - started_at:.2f}s"
    )
    history_assets = _history_assets(universe, scan_request)
    await progress(
        "[OPTIONS] loading 30-day historical volatility "
        f"assets={','.join(history_assets) if history_assets else 'none'}"
    )
    historical_contexts = await _load_historical_contexts(
        historical_volatility_loader,
        history_assets,
        requested_at=universe.valuation_time,
    )
    await progress("[OPTIONS] running opportunity scanner")
    try:
        result = await _run_scanner(scanner, universe, scan_request)
    except Exception as exc:
        logger.exception("[OPTIONS] opportunity scanner failed")
        await progress(f"[OPTIONS] opportunity scanner failed: {exc}")
        raise ApiError(500, "scanner_failed", "Opportunity scan failed") from exc
    await progress(
        "[OPTIONS] scan completed "
        f"opportunities={len(result.opportunities)} rejections={len(result.rejections)} "
        f"asset_failures={len(result.asset_failures)} "
        f"elapsed={time.perf_counter() - started_at:.2f}s"
    )
    return HistoricalContextScanResult(
        scan=result,
        historical_volatility_contexts=historical_contexts,
    )


def _history_assets(
    universe: NormalizedOptionUniverse,
    scan_request: ScanRequest,
) -> tuple[str, ...]:
    if scan_request.assets:
        return tuple(sorted({asset.strip().upper() for asset in scan_request.assets if asset.strip()}))
    assets = {asset.base_coin.upper() for asset in universe.assets}
    assets.update(contract.asset.upper() for contract in universe.contracts)
    return tuple(sorted(assets))


async def _load_historical_contexts(
    loader: HistoricalVolatilityLoader | None,
    assets: tuple[str, ...],
    *,
    requested_at: datetime,
) -> HistoricalVolatilityContexts:
    if not assets:
        return HistoricalVolatilityContexts()
    if loader is None:
        return HistoricalVolatilityContexts(
            tuple(
                HistoricalVolatilityContext.not_loaded(asset, requested_at=requested_at)
                for asset in assets
            )
        )
    try:
        loaded = await _maybe_await(loader.load(assets, as_of=requested_at))
        if not isinstance(loaded, HistoricalVolatilityContexts):
            raise TypeError("historical volatility loader returned an invalid context collection")
        return HistoricalVolatilityContexts(
            loaded.cover(assets, requested_at=requested_at)
        )
    except Exception as exc:
        logger.exception("[OPTIONS] historical volatility loading failed")
        retrieved_at = datetime.now(UTC)
        return HistoricalVolatilityContexts(
            tuple(
                HistoricalVolatilityContext(
                    asset=asset,
                    period_days=30,
                    available=False,
                    status="fetch_error",
                    historical_volatility=None,
                    as_of=None,
                    requested_at=requested_at,
                    retrieved_at=retrieved_at,
                    message=f"Historical volatility context failed to load: {exc}",
                )
                for asset in assets
            )
        )


async def _run_scanner(
    scanner: Callable[[NormalizedOptionUniverse, ScanRequest], ScanResult],
    universe: NormalizedOptionUniverse,
    scan_request: ScanRequest,
) -> ScanResult:
    if inspect.iscoroutinefunction(scanner):
        return await scanner(universe, scan_request)
    result = await asyncio.to_thread(scanner, universe, scan_request)
    return await result if inspect.isawaitable(result) else result


def _ndjson_line(payload: dict[str, Any]) -> str:
    return f"{json.dumps(payload, ensure_ascii=False)}\n"


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _upstream_error(exc: Exception) -> ApiError:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        return ApiError(504, "upstream_timeout", "Upstream market data request failed")
    return ApiError(502, "upstream_unavailable", "Upstream market data request failed")


def _cors_origins_from_environment() -> list[str]:
    configured = os.getenv(_CORS_ORIGINS_ENV, "")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


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


def _serialize_scan_result(
    result: ScanResult | HistoricalContextScanResult,
    filters: ScanFilters,
    scan_request: ScanRequest,
) -> dict[str, Any]:
    if isinstance(result, HistoricalContextScanResult):
        payload = _serialize(result.scan)
        payload["historical_volatility_contexts"] = [
            _serialize_historical_context(context)
            for context in result.historical_volatility_contexts.contexts
        ]
        opportunities = result.scan.opportunities
    else:
        payload = _serialize(result)
        opportunities = result.opportunities
    theoretical = scan_request.valuation_mode == "theoretical"
    synthetic = scan_request.valuation_mode == "synthetic"
    payload["opportunities"] = [
        _serialize_opportunity(opportunity)
        for opportunity in opportunities
        if theoretical or _passes_expected_value_filter(opportunity, filters.min_expected_value)
    ]
    applied_filters = {
        "min_dte": scan_request.min_dte,
        "max_dte": scan_request.max_dte,
        "min_delta": scan_request.min_delta,
        "max_delta": scan_request.max_delta,
        "min_iv_edge": scan_request.min_iv_edge,
        "max_spread_pct": scan_request.max_spread_pct,
        "min_open_interest": scan_request.min_open_interest,
        "min_volume_24h": scan_request.min_volume_24h,
        "min_edge_after_costs": scan_request.min_edge_after_costs,
        "min_expected_value": filters.min_expected_value,
        "assumed_spread_bps": scan_request.assumed_spread_bps,
        "max_results": scan_request.max_results,
    }
    ignored_filters = (
        ["max_spread_pct", "min_edge_after_costs", "max_loss", "min_expected_value"]
        if theoretical
        else []
    )
    payload["scan_context"] = {
        "applied_filters": applied_filters,
        "expected_value_filter": {
            "enabled": filters.min_expected_value is not None and not theoretical,
            "minimum_expected_value": filters.min_expected_value,
            "source": "ignored_in_theoretical_mode" if theoretical else "opportunity.expected_value",
        },
    }
    # The request is authoritative so legacy/injected scanners cannot hide the
    # mode selected by the caller in the HTTP response.
    payload["valuation_mode"] = scan_request.valuation_mode
    payload["ignored_filters"] = ignored_filters
    if filters.market_view is not None and filters.time_horizon is not None:
        assumptions = {
            "valuation_mode": scan_request.valuation_mode,
            "risk_free_rate": scan_request.risk_free_rate,
            "fee_per_contract": scan_request.fee_per_contract,
            "slippage_bps": scan_request.slippage_bps,
            "assumed_spread_bps": scan_request.assumed_spread_bps,
            "quantity": scan_request.quantity,
            "contract_multiplier": scan_request.contract_multiplier,
            "include_unvalidated": scan_request.include_unvalidated,
        }
        ignored_filters = payload["ignored_filters"]
        max_loss_text = (
            "không giới hạn" if scan_request.max_loss is None else f"{scan_request.max_loss:g}"
        )
        view_text = {
            "up": "tăng",
            "down": "giảm",
            "sideways": "đi ngang",
            "custom": "tùy chỉnh nhiều chiến lược",
        }[filters.market_view]
        horizon_text = {
            "0_7": "0–7 ngày",
            "7_30": "7–30 ngày",
            "30_90": "30–90 ngày",
        }[filters.time_horizon]
        payload["scan_context"].update(
            {
                "market_view": filters.market_view,
                "time_horizon": filters.time_horizon,
                "strategy_preference": filters.strategy_preference,
                "max_loss": scan_request.max_loss,
                "valuation_mode": scan_request.valuation_mode,
                "strategies": list(scan_request.strategies),
                "applied_filters": applied_filters,
                "ignored_filters": ignored_filters,
                "assumptions": assumptions,
                "summary": (
                    f"Kỳ vọng {view_text} · {horizon_text} · "
                    + (
                        "chỉ định giá lý thuyết, không có giá khớp"
                        if theoretical
                        else f"định giá quote tổng hợp với spread {scan_request.assumed_spread_bps:g} bps"
                        if synthetic
                        else f"lỗ tối đa {max_loss_text}"
                    )
                ),
            }
        )
    return payload


def _serialize_historical_context(context: HistoricalVolatilityContext) -> dict[str, Any]:
    """Serialize the stable API shape for history quality metadata."""

    return {
        "asset": context.asset,
        "period_days": context.period_days,
        "available": context.available,
        "status": context.status,
        "historical_volatility": context.historical_volatility,
        "as_of": _serialize(context.as_of),
        "requested_at": _serialize(context.requested_at),
        "retrieved_at": _serialize(context.retrieved_at),
        "source": context.source,
        "message": context.message,
        "role": "anchor_quality_only",
    }


def _serialize_opportunity(opportunity: Any) -> dict[str, Any]:
    """Serialize an opportunity with stable metrics and a UTC expiry instant."""

    payload = _serialize(opportunity)
    if not isinstance(payload, dict):
        return {"value": payload}

    expiry_at = _opportunity_value(opportunity, ("expiry_at", "expiry"))
    if isinstance(expiry_at, datetime):
        payload["expiry_at"] = _serialize(expiry_at)
    elif isinstance(expiry_at, date):
        # A date-only compatibility value is made explicit as midnight UTC;
        # clients can rely on ``expiry_at`` always being a complete instant.
        payload["expiry_at"] = f"{expiry_at.isoformat()}T00:00:00Z"

    for output_name, aliases in _OPPORTUNITY_METRIC_ALIASES.items():
        metric = _opportunity_value(opportunity, aliases)
        if metric is not None:
            payload[output_name] = _serialize(metric)
        else:
            payload.setdefault(output_name, None)
    return payload


def _passes_expected_value_filter(opportunity: Any, minimum: float | None) -> bool:
    """Apply an EV gate only from an EV metric, never from IV/model edge."""

    if minimum is None:
        return True
    expected_value = _opportunity_value(opportunity, ("expected_value",))
    try:
        value = float(expected_value)
    except (TypeError, ValueError):
        return False
    return not isinstance(expected_value, bool) and math.isfinite(value) and value >= minimum


def _opportunity_value(opportunity: Any, names: tuple[str, ...]) -> Any | None:
    for name in names:
        value = getattr(opportunity, name, None)
        if value is not None:
            return value
    return None


__all__ = [
    "BacktestExitPolicyRequest",
    "BacktestRequest",
    "ExecutionAssumptionsRequest",
    "MarketScenarioRequest",
    "PositionMonitoringPolicyRequest",
    "PositionMonitoringRequest",
    "ScanFilters",
    "ScenarioLegRequest",
    "ScenarioRequest",
    "create_app",
]
