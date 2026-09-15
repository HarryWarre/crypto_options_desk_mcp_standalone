"""Normalized, read-only Bybit options market data.

This module is deliberately separate from the legacy options-chain helper.  It
provides the public seam used by downstream scanners: Bybit public responses
are converted into a validated, chronologically ordered option universe.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .utils import ensure_utc_datetime, format_bybit_timestamp, now_utc

PublicRequest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class OptionDataQualityIssue:
    """A reason why a public market-data record was not normalized."""

    code: str
    message: str
    symbol: str | None = None
    asset: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class OptionAsset:
    """An actively trading Bybit options underlying discovered from instruments."""

    base_coin: str
    status: str
    contract_count: int


@dataclass(frozen=True)
class OptionContract:
    """A normalized, quality-checked public option quote."""

    asset: str
    symbol: str
    option_type: str
    strike: float
    expiry_at: datetime
    expiry_code: str
    spot_price: float
    mark_price: float
    mark_iv: float
    bid_price: float
    ask_price: float
    bid_iv: float | None
    ask_iv: float | None
    delta: float
    gamma: float
    theta: float
    vega: float
    volume_24h: float
    open_interest: float
    quote_currency: str | None
    settle_currency: str | None
    quote_timestamp: datetime


@dataclass(frozen=True)
class OptionAssetCatalog:
    """The instrument discovery result and any excluded instrument reasons."""

    assets: tuple[OptionAsset, ...]
    issues: tuple[OptionDataQualityIssue, ...]
    fetched_at: datetime


@dataclass(frozen=True)
class NormalizedOptionUniverse:
    """The normalized multi-asset universe returned by one public scan."""

    assets: tuple[OptionAsset, ...]
    contracts: tuple[OptionContract, ...]
    issues: tuple[OptionDataQualityIssue, ...]
    valuation_time: datetime
    source: str = "bybit-public"

    @property
    def contracts_by_asset(self) -> dict[str, tuple[OptionContract, ...]]:
        grouped: dict[str, list[OptionContract]] = {}
        for contract in self.contracts:
            grouped.setdefault(contract.asset, []).append(contract)
        return {asset: tuple(contracts) for asset, contracts in grouped.items()}


@dataclass(frozen=True)
class _InstrumentRecord:
    asset: str
    symbol: str
    option_type: str
    strike: float
    expiry_at: datetime
    expiry_code: str
    quote_currency: str | None
    settle_currency: str | None


class BybitOptionMarketDataAdapter:
    """Adapt Bybit public option endpoints into a normalized universe.

    The adapter accepts an injected request function so all behavior can be
    tested deterministically without a network.  In production, pass a shared
    :class:`BybitPublicClient`; its request layer owns connection pooling,
    rate-limiting, retries, and exponential backoff.
    """

    def __init__(
        self,
        client: Any = None,
        *,
        request: PublicRequest | None = None,
        valuation_time: datetime | None = None,
        now_fn: Callable[[], datetime] = now_utc,
        max_concurrent_requests: int = 4,
        max_quote_age_seconds: float = 300.0,
        max_instrument_pages: int = 100,
    ):
        if request is None:
            if client is None:
                from .public import BybitPublicClient

                client = BybitPublicClient()
            request = client._make_request
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be at least 1")
        if max_quote_age_seconds < 0:
            raise ValueError("max_quote_age_seconds cannot be negative")
        if max_instrument_pages < 1:
            raise ValueError("max_instrument_pages must be at least 1")

        self._request = request
        self._valuation_time = (
            ensure_utc_datetime(valuation_time) if valuation_time is not None else None
        )
        self._now_fn = now_fn
        self._max_concurrent_requests = max_concurrent_requests
        self._max_quote_age = timedelta(seconds=max_quote_age_seconds)
        self._max_instrument_pages = max_instrument_pages

    async def discover_assets(self) -> OptionAssetCatalog:
        """Discover active option assets from the paginated public endpoint."""

        catalog, _ = await self._discover_instruments()
        return catalog

    async def load_universe(
        self,
        assets: Sequence[str] | None = None,
        *,
        valuation_time: datetime | None = None,
    ) -> NormalizedOptionUniverse:
        """Load one timestamped, normalized universe for one or more assets.

        Instrument discovery is performed once per call and reused by all
        ticker requests in that scan.  A failed asset is represented by a
        quality issue while successful assets remain available.
        """

        catalog, instruments = await self._discover_instruments()
        fixed_valuation_time = self._resolve_fixed_valuation_time(valuation_time)
        issues = list(catalog.issues)

        requested_assets = (
            tuple(dict.fromkeys(asset.upper() for asset in assets)) if assets is not None else None
        )
        if requested_assets is None:
            selected_assets = tuple(asset.base_coin for asset in catalog.assets)
        else:
            selected_assets = requested_assets
            known_assets = {asset.base_coin for asset in catalog.assets}
            for asset in requested_assets:
                if asset not in known_assets:
                    issues.append(
                        OptionDataQualityIssue(
                            code="asset_not_discovered",
                            message=f"No actively trading option instruments discovered for {asset}",
                            asset=asset,
                        )
                    )

        semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        tasks = [
            self._load_asset(
                asset,
                instruments.get(asset, ()),
                fixed_valuation_time,
                semaphore,
            )
            for asset in selected_assets
            if instruments.get(asset)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        contracts: list[OptionContract] = []
        for asset, result in zip(
            [asset for asset in selected_assets if instruments.get(asset)], results
        ):
            if isinstance(result, Exception):
                issues.append(
                    OptionDataQualityIssue(
                        code="asset_fetch_failed",
                        message=f"Failed to load option tickers for {asset}: {result}",
                        asset=asset,
                    )
                )
                continue
            asset_contracts, asset_issues = result
            contracts.extend(asset_contracts)
            issues.extend(asset_issues)

        contracts.sort(key=lambda contract: (contract.expiry_at, contract.strike, contract.option_type, contract.symbol))
        as_of = fixed_valuation_time or ensure_utc_datetime(self._now_fn())
        return NormalizedOptionUniverse(
            assets=catalog.assets,
            contracts=tuple(contracts),
            issues=tuple(issues),
            valuation_time=as_of,
        )

    async def _discover_instruments(
        self,
    ) -> tuple[OptionAssetCatalog, dict[str, tuple[_InstrumentRecord, ...]]]:
        # This is the actual retrieval time.  It must remain distinct from a
        # caller-supplied historical valuation time used for replay/backtests.
        fetched_at = ensure_utc_datetime(self._now_fn())
        issues: list[OptionDataQualityIssue] = []
        records: dict[str, _InstrumentRecord] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()

        for _ in range(self._max_instrument_pages):
            params: dict[str, Any] = {
                "category": "option",
                "baseCoin": "All",
                "status": "Trading",
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor
            try:
                response = await self._request("/v5/market/instruments-info", params)
                result = self._result_or_raise(response)
            except Exception as exc:  # noqa: BLE001 - one failed discovery must not crash the scan
                issues.append(
                    OptionDataQualityIssue(
                        code="instrument_discovery_failed",
                        message=f"Failed to discover option instruments: {exc}",
                    )
                )
                break

            items = result.get("list", [])
            if not isinstance(items, list):
                issues.append(
                    OptionDataQualityIssue(
                        code="invalid_instrument_response",
                        message="Bybit instrument result.list is not a list",
                    )
                )
                break

            for raw in items:
                record, record_issues = self._normalize_instrument(raw)
                issues.extend(record_issues)
                if record is None:
                    continue
                if record.symbol in records:
                    issues.append(
                        OptionDataQualityIssue(
                            code="duplicate_instrument",
                            message="Duplicate instrument symbol excluded; first record kept",
                            symbol=record.symbol,
                            asset=record.asset,
                        )
                    )
                    continue
                records[record.symbol] = record

            next_cursor = result.get("nextPageCursor") or None
            if not next_cursor:
                break
            if next_cursor in seen_cursors or next_cursor == cursor:
                issues.append(
                    OptionDataQualityIssue(
                        code="cursor_loop",
                        message="Instrument discovery stopped because the cursor repeated",
                    )
                )
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            issues.append(
                OptionDataQualityIssue(
                    code="instrument_page_limit",
                    message="Instrument discovery stopped at the configured page limit",
                )
            )

        grouped: dict[str, list[_InstrumentRecord]] = {}
        for record in records.values():
            grouped.setdefault(record.asset, []).append(record)

        assets = tuple(
            OptionAsset(
                base_coin=asset,
                status="Trading",
                contract_count=len(grouped[asset]),
            )
            for asset in sorted(grouped)
        )
        instruments = {
            asset: tuple(
                sorted(
                    records_for_asset,
                    key=lambda record: (record.expiry_at, record.strike, record.option_type, record.symbol),
                )
            )
            for asset, records_for_asset in grouped.items()
        }
        return OptionAssetCatalog(assets, tuple(issues), fetched_at), instruments

    async def _load_asset(
        self,
        asset: str,
        instruments: tuple[_InstrumentRecord, ...],
        valuation_time: datetime | None,
        semaphore: asyncio.Semaphore,
    ) -> tuple[list[OptionContract], list[OptionDataQualityIssue]]:
        issues: list[OptionDataQualityIssue] = []
        async with semaphore:
            response = await self._request(
                "/v5/market/tickers",
                {"category": "option", "baseCoin": asset},
            )
        result = self._result_or_raise(response)
        quote_timestamp = format_bybit_timestamp(response.get("time"))
        if quote_timestamp is None:
            issues.append(
                OptionDataQualityIssue(
                    code="missing_snapshot_timestamp",
                    message="Ticker response did not include a valid Bybit timestamp",
                    asset=asset,
                )
            )
            return [], issues

        # For live scans, take the comparison time after the ticker response
        # arrives.  Taking it before the request makes every normal response
        # look like a future quote and drops the whole asset.  A fixed time is
        # still used unchanged for historical replay/backtests.
        comparison_time = valuation_time or max(
            ensure_utc_datetime(self._now_fn()),
            quote_timestamp,
        )
        age = comparison_time - quote_timestamp
        if age < timedelta(0):
            issues.append(
                OptionDataQualityIssue(
                    code="future_quote",
                    message="Ticker snapshot is newer than the valuation time",
                    asset=asset,
                )
            )
            return [], issues

        tickers = result.get("list", [])
        if not isinstance(tickers, list):
            issues.append(
                OptionDataQualityIssue(
                    code="invalid_ticker_response",
                    message="Bybit ticker result.list is not a list",
                    asset=asset,
                )
            )
            return [], issues

        ticker_by_symbol: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            symbol = ticker.get("symbol") if isinstance(ticker, dict) else None
            if not symbol:
                issues.append(
                    OptionDataQualityIssue(
                        code="missing_ticker_symbol",
                        message="Ticker without a symbol excluded",
                        asset=asset,
                    )
                )
                continue
            if symbol in ticker_by_symbol:
                issues.append(
                    OptionDataQualityIssue(
                        code="duplicate_ticker",
                        message="Duplicate ticker symbol excluded; first record kept",
                        symbol=symbol,
                        asset=asset,
                    )
                )
                continue
            ticker_by_symbol[symbol] = ticker

        contracts: list[OptionContract] = []
        instrument_symbols = {instrument.symbol for instrument in instruments}
        for instrument in instruments:
            ticker = ticker_by_symbol.get(instrument.symbol)
            if ticker is None:
                issues.append(
                    OptionDataQualityIssue(
                        code="missing_ticker",
                        message="Instrument has no matching ticker",
                        symbol=instrument.symbol,
                        asset=asset,
                    )
                )
                continue
            if age > self._max_quote_age:
                issues.append(
                    OptionDataQualityIssue(
                        code="stale_quote",
                        message=f"Ticker snapshot is {age.total_seconds():.0f} seconds old",
                        symbol=instrument.symbol,
                        asset=asset,
                    )
                )
                continue
            contract, contract_issues = self._normalize_quote(
                instrument, ticker, quote_timestamp
            )
            issues.extend(contract_issues)
            if contract is not None:
                contracts.append(contract)

        # Keep this local set so a malformed response cannot accidentally add a
        # ticker for a symbol that was not part of the discovered universe.
        _ = instrument_symbols
        return contracts, issues

    def _normalize_instrument(
        self, raw: Any
    ) -> tuple[_InstrumentRecord | None, list[OptionDataQualityIssue]]:
        issues: list[OptionDataQualityIssue] = []
        if not isinstance(raw, dict):
            return None, [
                OptionDataQualityIssue(
                    code="invalid_instrument",
                    message="Instrument record is not an object",
                )
            ]

        symbol = raw.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            return None, [
                OptionDataQualityIssue(
                    code="missing_symbol",
                    message="Instrument has no symbol",
                )
            ]
        parts = symbol.split("-")
        # Bybit has returned both the legacy four-part form
        # (BTC-25SEP26-78000-C) and the current five-part form with an
        # explicit settlement coin (BTC-25SEP26-78000-C-USDT).
        if len(parts) not in {4, 5}:
            return None, [
                OptionDataQualityIssue(
                    code="malformed_symbol",
                    message="Option symbol must contain base, expiry, strike, type, and optionally settlement coin",
                    symbol=symbol,
                )
            ]

        symbol_asset = parts[0].upper()
        asset = str(raw.get("baseCoin") or symbol_asset).upper()
        if asset != symbol_asset:
            return None, [
                OptionDataQualityIssue(
                    code="asset_symbol_mismatch",
                    message="Instrument baseCoin disagrees with the asset in its symbol",
                    symbol=symbol,
                    asset=asset,
                    field="base_coin",
                )
            ]
        expiry_code = parts[1].upper()
        try:
            symbol_expiry = datetime.strptime(expiry_code, "%d%b%y").replace(tzinfo=UTC)
        except (TypeError, ValueError):
            return None, [
                OptionDataQualityIssue(
                    code="invalid_expiry_code",
                    message="Option symbol contains an invalid expiry code",
                    symbol=symbol,
                    asset=asset,
                    field="expiry",
                )
            ]

        symbol_option_type = self._normalize_option_type(parts[3])
        metadata_option_type = (
            self._normalize_option_type(raw.get("optionsType"))
            if raw.get("optionsType") is not None
            else symbol_option_type
        )
        if symbol_option_type is None or metadata_option_type is None:
            return None, [
                OptionDataQualityIssue(
                    code="invalid_option_type",
                    message="Option type must be Call/Put or C/P",
                    symbol=symbol,
                    asset=asset,
                    field="option_type",
                )
            ]
        if metadata_option_type != symbol_option_type:
            return None, [
                OptionDataQualityIssue(
                    code="option_type_mismatch",
                    message="Instrument optionsType disagrees with its symbol",
                    symbol=symbol,
                    asset=asset,
                    field="option_type",
                )
            ]
        option_type = symbol_option_type

        strike = self._number(raw.get("strikePrice"), fallback=parts[2])
        if strike is None or strike <= 0:
            return None, [
                OptionDataQualityIssue(
                    code="invalid_strike",
                    message="Strike must be a positive finite number",
                    symbol=symbol,
                    asset=asset,
                    field="strike",
                )
            ]

        expiry_at = format_bybit_timestamp(raw.get("deliveryTime"))
        if expiry_at is None:
            expiry_at = symbol_expiry.replace(tzinfo=None)
            issues.append(
                OptionDataQualityIssue(
                    code="missing_delivery_time",
                    message="Delivery time missing; symbol expiry date used",
                    symbol=symbol,
                    asset=asset,
                    field="expiry",
                )
            )
        if expiry_at.date() != symbol_expiry.date():
            return None, [
                OptionDataQualityIssue(
                    code="expiry_mismatch",
                    message="Instrument delivery time disagrees with symbol expiry",
                    symbol=symbol,
                    asset=asset,
                    field="expiry",
                )
            ]

        status = str(raw.get("status") or "").lower()
        if status != "trading":
            return None, [
                OptionDataQualityIssue(
                    code="not_trading",
                    message="Only actively trading instruments are supported",
                    symbol=symbol,
                    asset=asset,
                    field="status",
                )
            ]

        return (
            _InstrumentRecord(
                asset=asset,
                symbol=symbol,
                option_type=option_type,
                strike=strike,
                expiry_at=expiry_at,
                expiry_code=expiry_code,
                quote_currency=self._text(raw.get("quoteCoin")),
                settle_currency=self._text(raw.get("settleCoin")),
            ),
            issues,
        )

    def _normalize_quote(
        self,
        instrument: _InstrumentRecord,
        ticker: dict[str, Any],
        quote_timestamp: datetime,
    ) -> tuple[OptionContract | None, list[OptionDataQualityIssue]]:
        issues: list[OptionDataQualityIssue] = []

        def required_number(
            field: str,
            *,
            minimum: float | None = None,
            strictly_positive: bool = False,
        ) -> float | None:
            value = self._number(ticker.get(field))
            if value is None or (
                strictly_positive and value <= 0
            ) or (minimum is not None and value < minimum):
                issue_field = {
                    "underlyingPrice": "spot_price",
                    "markPrice": "mark_price",
                    "markIv": "mark_iv",
                    "bid1Price": "bid_price",
                    "ask1Price": "ask_price",
                    "totalVolume": "volume_24h",
                    "openInterest": "open_interest",
                }.get(field, field)
                code = (
                    f"non_positive_{issue_field}"
                    if value is not None and strictly_positive and value <= 0
                    else f"missing_{issue_field}"
                )
                issues.append(
                    OptionDataQualityIssue(
                        code=code,
                        message=f"Ticker field {field} is missing or invalid",
                        symbol=instrument.symbol,
                        asset=instrument.asset,
                        field=field,
                    )
                )
                return None
            return value

        spot = required_number("underlyingPrice", strictly_positive=True)
        mark_price = required_number("markPrice", strictly_positive=True)
        mark_iv = required_number("markIv", minimum=0.0)
        bid_price = required_number("bid1Price", minimum=0.0)
        ask_price = required_number("ask1Price", minimum=0.0)
        delta = required_number("delta")
        gamma = required_number("gamma")
        theta = required_number("theta")
        vega = required_number("vega")
        volume = required_number("totalVolume", minimum=0.0)
        open_interest = required_number("openInterest", minimum=0.0)

        if bid_price is not None and ask_price is not None:
            if bid_price <= 0 or ask_price <= 0:
                issues.append(
                    OptionDataQualityIssue(
                        code="non_positive_bid_ask",
                        message="Tradable option quote must have positive bid and ask",
                        symbol=instrument.symbol,
                        asset=instrument.asset,
                        field="quote",
                    )
                )
            elif ask_price < bid_price:
                issues.append(
                    OptionDataQualityIssue(
                        code="inverted_bid_ask",
                        message="Ask price cannot be below bid price",
                        symbol=instrument.symbol,
                        asset=instrument.asset,
                        field="quote",
                    )
                )

        if mark_iv is not None and mark_iv <= 0:
            issues.append(
                OptionDataQualityIssue(
                    code="invalid_mark_iv",
                    message="Mark IV must be positive and is represented as a decimal",
                    symbol=instrument.symbol,
                    asset=instrument.asset,
                    field="mark_iv",
                )
            )

        if any(value is None for value in (spot, mark_price, mark_iv, bid_price, ask_price, delta, gamma, theta, vega, volume, open_interest)):
            return None, issues
        if mark_iv <= 0 or bid_price <= 0 or ask_price <= 0 or ask_price < bid_price:
            return None, issues

        return (
            OptionContract(
                asset=instrument.asset,
                symbol=instrument.symbol,
                option_type=instrument.option_type,
                strike=instrument.strike,
                expiry_at=instrument.expiry_at,
                expiry_code=instrument.expiry_code,
                spot_price=spot,
                mark_price=mark_price,
                mark_iv=mark_iv,
                bid_price=bid_price,
                ask_price=ask_price,
                bid_iv=self._number(ticker.get("bid1Iv")),
                ask_iv=self._number(ticker.get("ask1Iv")),
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
                volume_24h=volume,
                open_interest=open_interest,
                quote_currency=instrument.quote_currency,
                settle_currency=instrument.settle_currency,
                quote_timestamp=quote_timestamp,
            ),
            issues,
        )

    def _resolve_fixed_valuation_time(self, value: datetime | None) -> datetime | None:
        if value is not None:
            return ensure_utc_datetime(value)
        if self._valuation_time is not None:
            return self._valuation_time
        return None

    @staticmethod
    def _result_or_raise(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise TypeError("Bybit response is not an object")
        if response.get("retCode", 0) != 0:
            raise ValueError(
                f"Bybit API error {response.get('retCode')}: {response.get('retMsg', '')}"
            )
        if "result" not in response:
            raise ValueError("Bybit response is missing result")
        result = response["result"]
        if not isinstance(result, dict):
            raise TypeError("Bybit response result is not an object")
        return result

    @staticmethod
    def _normalize_option_type(value: Any) -> str | None:
        normalized = str(value or "").strip().lower()
        if normalized in {"call", "c"}:
            return "Call"
        if normalized in {"put", "p"}:
            return "Put"
        return None

    @staticmethod
    def _number(value: Any, fallback: Any = None) -> float | None:
        candidate = value if value not in (None, "") else fallback
        try:
            parsed = float(candidate)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None or value == "":
            return None
        return str(value)
