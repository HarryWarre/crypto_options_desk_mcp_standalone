"""Timestamped Bybit option ticker snapshots and deterministic replay.

Bybit's public ticker endpoint is a latest-snapshot endpoint.  This module
therefore supports prospective capture and replay of archives collected by
the application; it never pretends that a current ticker is historical data.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from options_lib.symbol_parser import parse_bybit_option_symbol

from .options_market_data import (
    NormalizedOptionUniverse,
    OptionAsset,
    OptionContract,
    OptionDataQualityIssue,
)

PublicRequest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class OptionHistoryError(ValueError):
    """Base error for snapshot archive and replay failures."""


class SnapshotFormatError(OptionHistoryError):
    """Raised when an archive record cannot be decoded safely."""


class SnapshotConflictError(OptionHistoryError):
    """Raised when one snapshot identity has conflicting payloads."""


class HistoricalDataUnavailable(OptionHistoryError):
    """Raised when an exact or sufficiently fresh replay is unavailable."""


@dataclass(frozen=True)
class HistoricalOptionQuote:
    """One option quote captured in an asset-level ticker response."""

    symbol: str
    expiry_at: datetime
    expiry_code: str
    option_type: str
    strike: float
    underlying_price: float | None = None
    mark_price: float | None = None
    mark_iv: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    bid_iv: float | None = None
    ask_iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    volume_24h: float | None = None
    open_interest: float | None = None
    quote_currency: str | None = None
    settle_currency: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol or not isinstance(self.symbol, str):
            raise SnapshotFormatError("quote symbol must be a non-empty string")
        if self.expiry_at.tzinfo is None:
            raise SnapshotFormatError("quote expiry_at must be timezone-aware")
        if self.option_type not in {"Call", "Put"}:
            raise SnapshotFormatError("quote option_type must be Call or Put")
        if not math.isfinite(float(self.strike)) or self.strike <= 0:
            raise SnapshotFormatError("quote strike must be finite and positive")
        for name in _NUMERIC_FIELDS:
            value = getattr(self, name)
            if value is not None and not math.isfinite(float(value)):
                raise SnapshotFormatError(f"quote {name} must be finite when present")


@dataclass(frozen=True)
class HistoricalOptionSnapshot:
    """One asset-level Bybit ticker response with its source timestamp."""

    schema_version: int
    source: str
    source_timestamp: datetime
    retrieval_timestamp: datetime
    asset: str
    quotes: tuple[HistoricalOptionQuote, ...]
    issues: tuple[OptionDataQualityIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise SnapshotFormatError("unsupported historical option snapshot schema")
        if not self.source or not self.asset:
            raise SnapshotFormatError("snapshot source and asset are required")
        if self.source_timestamp.tzinfo is None or self.retrieval_timestamp.tzinfo is None:
            raise SnapshotFormatError("snapshot timestamps must be timezone-aware")


@dataclass(frozen=True)
class SnapshotQuery:
    """Deterministic archive filters."""

    start_time: datetime | None = None
    end_time: datetime | None = None
    assets: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        for value in (self.start_time, self.end_time):
            if value is not None and value.tzinfo is None:
                raise SnapshotFormatError("query timestamps must be timezone-aware")
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise SnapshotFormatError("query start_time must not be after end_time")
        if self.limit is not None and self.limit < 1:
            raise SnapshotFormatError("query limit must be positive")


@dataclass(frozen=True)
class SnapshotLoadResult:
    snapshots: tuple[HistoricalOptionSnapshot, ...]
    issues: tuple[OptionDataQualityIssue, ...]


@dataclass(frozen=True)
class ArchiveWriteResult:
    snapshots_written: int
    quotes_written: int
    duplicates_removed: int


class BybitOptionSnapshotCollector:
    """Capture latest option ticker snapshots prospectively."""

    def __init__(
        self,
        request: PublicRequest,
        *,
        now_fn: Callable[[], datetime],
        max_concurrent_requests: int = 4,
    ) -> None:
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be positive")
        self._request = request
        self._now_fn = now_fn
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

    async def capture(
        self,
        *,
        assets: Sequence[str],
        symbols: Sequence[str] = (),
    ) -> tuple[HistoricalOptionSnapshot, ...]:
        """Capture one Bybit ticker response per requested asset."""

        selected_assets = tuple(dict.fromkeys(str(asset).strip().upper() for asset in assets))
        selected_symbols = {
            str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()
        }
        snapshots = await asyncio.gather(
            *(self._capture_asset(asset, selected_symbols) for asset in selected_assets)
        )
        return tuple(sorted(snapshots, key=lambda item: (item.source_timestamp, item.asset)))

    async def _capture_asset(
        self, asset: str, selected_symbols: set[str]
    ) -> HistoricalOptionSnapshot:
        async with self._semaphore:
            response = await self._request(
                "/v5/market/tickers",
                {"category": "option", "baseCoin": asset},
            )
        if not isinstance(response, dict) or response.get("retCode", 0) != 0:
            raise HistoricalDataUnavailable(
                f"Bybit ticker capture failed for {asset}: "
                f"{response.get('retMsg', '') if isinstance(response, dict) else response}"
            )
        source_timestamp = _response_timestamp(response.get("time"))
        result = response.get("result")
        if (
            source_timestamp is None
            or not isinstance(result, dict)
            or not isinstance(result.get("list"), list)
        ):
            raise SnapshotFormatError(f"invalid Bybit ticker response for {asset}")
        issues: list[OptionDataQualityIssue] = []
        quotes: list[HistoricalOptionQuote] = []
        for raw in result["list"]:
            quote, quote_issues = _normalize_ticker(asset, raw)
            issues.extend(quote_issues)
            if quote is not None and (not selected_symbols or quote.symbol in selected_symbols):
                quotes.append(quote)
        return HistoricalOptionSnapshot(
            schema_version=1,
            source="bybit-option-ticker:v1",
            source_timestamp=source_timestamp,
            retrieval_timestamp=_aware_utc(self._now_fn()),
            asset=asset,
            quotes=tuple(sorted(quotes, key=_quote_sort_key)),
            issues=tuple(sorted(issues, key=_issue_sort_key)),
        )


class JsonlOptionSnapshotArchive:
    """Canonical, append-by-rewrite JSONL archive for historical snapshots."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def save(self, snapshots: Iterable[HistoricalOptionSnapshot]) -> ArchiveWriteResult:
        existing = self._read_strict() if self.path.exists() else []
        incoming = list(snapshots)
        merged: dict[tuple[datetime, str], HistoricalOptionSnapshot] = {}
        duplicates = 0
        for snapshot in existing + incoming:
            key = (_aware_utc(snapshot.source_timestamp), snapshot.asset.upper())
            normalized = _normalized_snapshot(snapshot)
            previous = merged.get(key)
            if previous is None:
                merged[key] = normalized
            elif _snapshot_payload(previous) == _snapshot_payload(normalized):
                duplicates += 1
            else:
                raise SnapshotConflictError(
                    f"conflicting snapshot payload for {key[1]} at {key[0].isoformat()}"
                )
        ordered = sorted(merged.values(), key=lambda item: (item.source_timestamp, item.asset))
        self._atomic_write(ordered)
        return ArchiveWriteResult(
            snapshots_written=len(ordered),
            quotes_written=sum(len(item.quotes) for item in ordered),
            duplicates_removed=duplicates,
        )

    def load(self, query: SnapshotQuery | None = None) -> SnapshotLoadResult:
        query = query or SnapshotQuery()
        loaded: list[HistoricalOptionSnapshot] = []
        issues: list[OptionDataQualityIssue] = []
        assets = {asset.strip().upper() for asset in query.assets}
        symbols = {symbol.strip().upper() for symbol in query.symbols}
        for line_number, line in (
            enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1)
            if self.path.exists()
            else ()
        ):
            try:
                snapshot = _snapshot_from_dict(json.loads(line))
            except (SnapshotFormatError, TypeError, ValueError, json.JSONDecodeError) as exc:
                issues.append(
                    OptionDataQualityIssue(
                        code="invalid_snapshot_record",
                        message=f"line {line_number}: {exc}",
                    )
                )
                continue
            source_time = _aware_utc(snapshot.source_timestamp)
            if query.start_time and source_time < _aware_utc(query.start_time):
                continue
            if query.end_time and source_time > _aware_utc(query.end_time):
                continue
            if assets and snapshot.asset.upper() not in assets:
                continue
            if symbols:
                quotes = tuple(
                    quote for quote in snapshot.quotes if quote.symbol.upper() in symbols
                )
                if not quotes:
                    continue
                snapshot = replace(snapshot, quotes=quotes)
            loaded.append(snapshot)
            issues.extend(snapshot.issues)
        loaded.sort(key=lambda item: (item.source_timestamp, item.asset))
        if query.limit is not None:
            loaded = loaded[: query.limit]
        return SnapshotLoadResult(tuple(loaded), tuple(sorted(issues, key=_issue_sort_key)))

    def replay_universe(
        self,
        *,
        as_of: datetime,
        assets: Sequence[str],
        symbols: Sequence[str] = (),
        max_age: timedelta = timedelta(0),
    ) -> NormalizedOptionUniverse:
        """Replay the latest eligible snapshot at or before ``as_of``."""

        as_of = _aware_utc(as_of)
        if max_age < timedelta(0):
            raise SnapshotFormatError("max_age cannot be negative")
        selected_assets = tuple(dict.fromkeys(str(asset).strip().upper() for asset in assets))
        result = self.load(SnapshotQuery(assets=selected_assets, symbols=tuple(symbols)))
        issues = list(result.issues)
        contracts: list[OptionContract] = []
        catalog: list[OptionAsset] = []
        for asset in selected_assets:
            eligible = [
                snapshot
                for snapshot in result.snapshots
                if snapshot.asset.upper() == asset
                and _aware_utc(snapshot.source_timestamp) <= as_of
            ]
            if not eligible:
                raise HistoricalDataUnavailable(
                    f"no snapshot at or before {as_of.isoformat()} for {asset}"
                )
            snapshot = max(eligible, key=lambda item: item.source_timestamp)
            age = as_of - _aware_utc(snapshot.source_timestamp)
            if age > max_age:
                raise HistoricalDataUnavailable(
                    f"latest snapshot for {asset} is {age.total_seconds():.0f}s old; "
                    f"max_age is {max_age.total_seconds():.0f}s"
                )
            asset_contracts = []
            for quote in snapshot.quotes:
                contract, contract_issue = _quote_to_contract(
                    quote, asset, snapshot.source_timestamp, as_of
                )
                if contract_issue is not None:
                    issues.append(contract_issue)
                if contract is not None:
                    asset_contracts.append(contract)
            contracts.extend(asset_contracts)
            catalog.append(OptionAsset(asset, "Historical", len(asset_contracts)))
        if not contracts:
            raise HistoricalDataUnavailable(
                "selected snapshots contain no valuation-ready option quotes"
            )
        contracts.sort(
            key=lambda item: (
                item.asset,
                item.expiry_at,
                item.strike,
                item.option_type,
                item.symbol,
            )
        )
        return NormalizedOptionUniverse(
            assets=tuple(catalog),
            contracts=tuple(contracts),
            issues=tuple(sorted(issues, key=_issue_sort_key)),
            valuation_time=as_of,
            source="bybit-option-snapshot:v1",
        )

    def _read_strict(self) -> list[HistoricalOptionSnapshot]:
        result = self.load()
        if result.issues:
            raise SnapshotFormatError("archive contains invalid snapshot records")
        return list(result.snapshots)

    def _atomic_write(self, snapshots: Sequence[HistoricalOptionSnapshot]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                for snapshot in snapshots:
                    handle.write(_canonical_json(_snapshot_to_dict(snapshot)))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


_NUMERIC_FIELDS = (
    "underlying_price",
    "mark_price",
    "mark_iv",
    "bid_price",
    "ask_price",
    "bid_iv",
    "ask_iv",
    "delta",
    "gamma",
    "theta",
    "vega",
    "volume_24h",
    "open_interest",
)


def _normalize_ticker(
    asset: str, raw: Any
) -> tuple[HistoricalOptionQuote | None, list[OptionDataQualityIssue]]:
    issues: list[OptionDataQualityIssue] = []
    if not isinstance(raw, dict):
        return None, [
            OptionDataQualityIssue("invalid_ticker", "ticker is not an object", asset=asset)
        ]
    symbol = str(raw.get("symbol") or "").upper()
    parsed = parse_bybit_option_symbol(symbol)
    if parsed is None:
        return None, [
            OptionDataQualityIssue(
                "malformed_symbol",
                "ticker symbol is not a Bybit option",
                symbol=symbol,
                asset=asset,
                field="symbol",
            )
        ]
    option_type = "Call" if parsed["option_type"] == "C" else "Put"
    expiry_at = parsed["expiry_date"].replace(hour=8, tzinfo=UTC)
    values = {
        "underlying_price": _optional_float(raw.get("underlyingPrice")),
        "mark_price": _optional_float(raw.get("markPrice")),
        "mark_iv": _optional_float(raw.get("markIv")),
        "bid_price": _optional_float(raw.get("bid1Price")),
        "ask_price": _optional_float(raw.get("ask1Price")),
        "bid_iv": _optional_float(raw.get("bid1Iv")),
        "ask_iv": _optional_float(raw.get("ask1Iv")),
        "delta": _optional_float(raw.get("delta")),
        "gamma": _optional_float(raw.get("gamma")),
        "theta": _optional_float(raw.get("theta")),
        "vega": _optional_float(raw.get("vega")),
        "volume_24h": _optional_float(raw.get("volume24h", raw.get("totalVolume"))),
        "open_interest": _optional_float(raw.get("openInterest")),
    }
    for field, value in values.items():
        if value is None and raw.get(field) not in (None, ""):
            issues.append(
                OptionDataQualityIssue(
                    "invalid_ticker_field",
                    f"invalid {field}",
                    symbol=symbol,
                    asset=asset,
                    field=field,
                )
            )
    try:
        return HistoricalOptionQuote(
            symbol=symbol,
            expiry_at=expiry_at,
            expiry_code=symbol.split("-")[1],
            option_type=option_type,
            strike=parsed["strike"],
            quote_currency=raw.get("quoteCoin"),
            settle_currency=raw.get("settleCoin"),
            **values,
        ), issues
    except SnapshotFormatError as exc:
        issues.append(
            OptionDataQualityIssue("invalid_ticker", str(exc), symbol=symbol, asset=asset)
        )
        return None, issues


def _quote_to_contract(
    quote: HistoricalOptionQuote,
    asset: str,
    source_timestamp: datetime,
    as_of: datetime,
) -> tuple[OptionContract | None, OptionDataQualityIssue | None]:
    required = {
        "underlying_price": quote.underlying_price,
        "mark_price": quote.mark_price,
        "mark_iv": quote.mark_iv,
        "bid_price": quote.bid_price,
        "ask_price": quote.ask_price,
        "delta": quote.delta,
        "gamma": quote.gamma,
        "theta": quote.theta,
        "vega": quote.vega,
        "volume_24h": quote.volume_24h,
        "open_interest": quote.open_interest,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return None, OptionDataQualityIssue(
            "incomplete_historical_quote",
            f"quote excluded from valuation replay; missing {', '.join(missing)}",
            symbol=quote.symbol,
            asset=asset,
        )
    if quote.expiry_at <= as_of:
        return None, OptionDataQualityIssue(
            "expired_historical_quote",
            "expired option excluded from valuation replay",
            symbol=quote.symbol,
            asset=asset,
            field="expiry_at",
        )
    if (
        quote.bid_price <= 0
        or quote.ask_price <= 0
        or quote.ask_price < quote.bid_price
        or quote.mark_iv <= 0
    ):
        return None, OptionDataQualityIssue(
            "invalid_historical_quote",
            "historical quote failed bid/ask/IV invariants",
            symbol=quote.symbol,
            asset=asset,
        )
    return OptionContract(
        asset=asset,
        symbol=quote.symbol,
        option_type=quote.option_type,
        strike=quote.strike,
        expiry_at=quote.expiry_at,
        expiry_code=quote.expiry_code,
        spot_price=quote.underlying_price,
        mark_price=quote.mark_price,
        mark_iv=quote.mark_iv,
        bid_price=quote.bid_price,
        ask_price=quote.ask_price,
        bid_iv=quote.bid_iv,
        ask_iv=quote.ask_iv,
        delta=quote.delta,
        gamma=quote.gamma,
        theta=quote.theta,
        vega=quote.vega,
        volume_24h=quote.volume_24h,
        open_interest=quote.open_interest,
        quote_currency=quote.quote_currency,
        settle_currency=quote.settle_currency,
        quote_timestamp=_aware_utc(source_timestamp),
    ), None


def _snapshot_to_dict(snapshot: HistoricalOptionSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "source": snapshot.source,
        "source_timestamp": _iso(snapshot.source_timestamp),
        "retrieval_timestamp": _iso(snapshot.retrieval_timestamp),
        "asset": snapshot.asset,
        "quotes": [_quote_to_dict(quote) for quote in sorted(snapshot.quotes, key=_quote_sort_key)],
        "issues": [_issue_to_dict(issue) for issue in sorted(snapshot.issues, key=_issue_sort_key)],
    }


def _snapshot_from_dict(raw: Any) -> HistoricalOptionSnapshot:
    if not isinstance(raw, dict):
        raise SnapshotFormatError("snapshot record is not an object")
    try:
        quotes = tuple(_quote_from_dict(item) for item in raw.get("quotes", []))
        issues = tuple(_issue_from_dict(item) for item in raw.get("issues", []))
        return HistoricalOptionSnapshot(
            schema_version=int(raw["schema_version"]),
            source=str(raw["source"]),
            source_timestamp=_parse_iso(raw["source_timestamp"]),
            retrieval_timestamp=_parse_iso(raw["retrieval_timestamp"]),
            asset=str(raw["asset"]).upper(),
            quotes=quotes,
            issues=issues,
        )
    except (KeyError, TypeError, ValueError, SnapshotFormatError) as exc:
        raise SnapshotFormatError(str(exc)) from exc


def _quote_to_dict(quote: HistoricalOptionQuote) -> dict[str, Any]:
    return {
        "symbol": quote.symbol,
        "expiry_at": _iso(quote.expiry_at),
        "expiry_code": quote.expiry_code,
        "option_type": quote.option_type,
        "strike": quote.strike,
        **{field: getattr(quote, field) for field in _NUMERIC_FIELDS},
        "quote_currency": quote.quote_currency,
        "settle_currency": quote.settle_currency,
    }


def _quote_from_dict(raw: Any) -> HistoricalOptionQuote:
    if not isinstance(raw, dict):
        raise SnapshotFormatError("quote record is not an object")
    try:
        return HistoricalOptionQuote(
            symbol=str(raw["symbol"]),
            expiry_at=_parse_iso(raw["expiry_at"]),
            expiry_code=str(raw["expiry_code"]),
            option_type=str(raw["option_type"]),
            strike=float(raw["strike"]),
            **{field: _optional_float(raw.get(field)) for field in _NUMERIC_FIELDS},
            quote_currency=raw.get("quote_currency"),
            settle_currency=raw.get("settle_currency"),
        )
    except (KeyError, TypeError, ValueError, SnapshotFormatError) as exc:
        raise SnapshotFormatError(str(exc)) from exc


def _issue_to_dict(issue: OptionDataQualityIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "symbol": issue.symbol,
        "asset": issue.asset,
        "field": issue.field,
    }


def _issue_from_dict(raw: Any) -> OptionDataQualityIssue:
    if not isinstance(raw, dict):
        raise SnapshotFormatError("issue record is not an object")
    return OptionDataQualityIssue(
        code=str(raw.get("code", "invalid_issue")),
        message=str(raw.get("message", "")),
        symbol=raw.get("symbol"),
        asset=raw.get("asset"),
        field=raw.get("field"),
    )


def _normalized_snapshot(snapshot: HistoricalOptionSnapshot) -> HistoricalOptionSnapshot:
    return replace(
        snapshot,
        asset=snapshot.asset.upper(),
        source_timestamp=_aware_utc(snapshot.source_timestamp),
        retrieval_timestamp=_aware_utc(snapshot.retrieval_timestamp),
        quotes=tuple(sorted(snapshot.quotes, key=_quote_sort_key)),
        issues=tuple(sorted(snapshot.issues, key=_issue_sort_key)),
    )


def _snapshot_payload(snapshot: HistoricalOptionSnapshot) -> str:
    return _canonical_json(_snapshot_to_dict(snapshot))


def _quote_sort_key(quote: HistoricalOptionQuote) -> tuple[Any, ...]:
    return quote.expiry_at, quote.strike, quote.option_type, quote.symbol


def _issue_sort_key(issue: OptionDataQualityIssue) -> tuple[Any, ...]:
    return issue.code, issue.asset or "", issue.symbol or "", issue.field or "", issue.message


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _response_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)
        if timestamp < 1e12:
            timestamp *= 1000
        return datetime.fromtimestamp(timestamp / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SnapshotFormatError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise SnapshotFormatError("timestamp must be an ISO string")
    try:
        return _aware_utc(datetime.fromisoformat(value))
    except (TypeError, ValueError) as exc:
        raise SnapshotFormatError("invalid timestamp") from exc


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SnapshotFormatError("snapshot contains non-JSON-safe data") from exc


__all__ = [
    "ArchiveWriteResult",
    "BybitOptionSnapshotCollector",
    "HistoricalDataUnavailable",
    "HistoricalOptionQuote",
    "HistoricalOptionSnapshot",
    "JsonlOptionSnapshotArchive",
    "OptionHistoryError",
    "SnapshotConflictError",
    "SnapshotFormatError",
    "SnapshotLoadResult",
    "SnapshotQuery",
]
