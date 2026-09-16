"""Optional NautilusTrader catalog bridge for archived Bybit option quotes.

NautilusTrader is intentionally optional because its native extension has a
platform-specific Python/Rust build.  The bridge validates the archive and
writes the native ``CryptoOption``, ``QuoteTick`` and ``OptionGreeks`` records
required by a Nautilus option-chain backtest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bybit_api.option_history import JsonlOptionSnapshotArchive, SnapshotQuery


class NautilusUnavailable(RuntimeError):
    """Raised when the optional NautilusTrader extension is not installed."""


@dataclass(frozen=True)
class NautilusCatalogExport:
    catalog_path: str
    instruments_written: int
    quote_ticks_written: int
    greeks_written: int
    synthetic_size_assumption: str
    warnings: tuple[str, ...] = ()


def export_archive_to_nautilus_catalog(
    archive: JsonlOptionSnapshotArchive,
    catalog_path: Path | str,
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    assets: Sequence[str] = (),
) -> NautilusCatalogExport:
    """Write eligible Bybit snapshot records into a Nautilus Parquet catalog.

    Bybit ticker history has no bid/ask sizes.  The generated QuoteTicks use
    size ``1`` solely as an explicit structural assumption; this is not a
    liquidity estimate and should not be used to claim queue-level fills.
    """

    try:
        from nautilus_trader.model import (  # type: ignore[import-not-found]
            CryptoOption,
            Currency,
            GreeksConvention,
            InstrumentId,
            OptionGreeks,
            OptionKind,
            Price,
            Quantity,
            QuoteTick,
            Symbol,
        )
        from nautilus_trader.persistence import ParquetDataCatalog  # type: ignore[import-not-found]
    except ImportError as exc:
        raise NautilusUnavailable(
            "NautilusTrader is not installed; use Python 3.12–3.14 and install "
            "the pinned backtest extra"
        ) from exc

    normalized_assets = tuple(dict.fromkeys(str(asset).strip().upper() for asset in assets if asset))
    result = archive.load(
        SnapshotQuery(
            start_time=start_time,
            end_time=end_time,
            assets=normalized_assets,
        )
    )
    if not result.snapshots:
        raise ValueError("the selected archive range contains no snapshots")

    instruments: dict[str, object] = {}
    quotes: list[object] = []
    greeks: list[object] = []
    warnings = [issue.message for issue in result.issues]
    for snapshot in result.snapshots:
        ts = _timestamp_ns(snapshot.source_timestamp)
        for item in snapshot.quotes:
            if not _eligible_quote(item):
                warnings.append(f"excluded incomplete quote {item.symbol} at {snapshot.source_timestamp}")
                continue
            instrument_id = InstrumentId.from_str(f"{item.symbol}-OPTION.BYBIT")
            if item.symbol not in instruments:
                instruments[item.symbol] = CryptoOption(
                    instrument_id=instrument_id,
                    raw_symbol=Symbol(item.symbol),
                    underlying=Currency.from_str(snapshot.asset),
                    quote_currency=Currency.from_str(item.quote_currency or "USDT"),
                    settlement_currency=Currency.from_str(item.settle_currency or item.quote_currency or "USDT"),
                    is_inverse=False,
                    option_kind=OptionKind.CALL if item.option_type == "Call" else OptionKind.PUT,
                    strike_price=Price.from_str(str(item.strike)),
                    activation_ns=ts,
                    expiration_ns=_timestamp_ns(item.expiry_at),
                    price_precision=8,
                    size_precision=0,
                    price_increment=Price.from_str("0.00000001"),
                    size_increment=Quantity.from_str("1"),
                    ts_event=ts,
                    ts_init=ts,
                )
            quotes.append(
                QuoteTick(
                    instrument_id=instrument_id,
                    bid_price=Price.from_str(str(item.bid_price)),
                    ask_price=Price.from_str(str(item.ask_price)),
                    bid_size=Quantity.from_str("1"),
                    ask_size=Quantity.from_str("1"),
                    ts_event=ts,
                    ts_init=ts,
                )
            )
            greeks.append(
                OptionGreeks(
                    instrument_id=instrument_id,
                    delta=float(item.delta),
                    gamma=float(item.gamma),
                    vega=float(item.vega),
                    theta=float(item.theta),
                    rho=0.0,
                    mark_iv=float(item.mark_iv),
                    bid_iv=item.bid_iv,
                    ask_iv=item.ask_iv,
                    underlying_price=float(item.underlying_price),
                    open_interest=float(item.open_interest),
                    ts_event=ts,
                    ts_init=ts,
                    convention=GreeksConvention.PRICE_ADJUSTED,
                )
            )

    if not quotes or not greeks:
        raise ValueError("the selected archive range contains no complete quote/Greeks records")
    catalog = ParquetDataCatalog(str(catalog_path))
    catalog.write_instruments(list(instruments.values()))
    catalog.write_quote_ticks(quotes)
    catalog.write_option_greeks(greeks)
    return NautilusCatalogExport(
        catalog_path=str(catalog_path),
        instruments_written=len(instruments),
        quote_ticks_written=len(quotes),
        greeks_written=len(greeks),
        synthetic_size_assumption="bid_size=ask_size=1 contract; source archive has no size history",
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _eligible_quote(item: object) -> bool:
    required = (
        "bid_price",
        "ask_price",
        "mark_iv",
        "underlying_price",
        "delta",
        "gamma",
        "theta",
        "vega",
        "open_interest",
    )
    values = {name: getattr(item, name, None) for name in required}
    return (
        all(value is not None for value in values.values())
        and float(values["bid_price"]) > 0
        and float(values["ask_price"]) >= float(values["bid_price"])
        and float(values["mark_iv"]) > 0
    )


def _timestamp_ns(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("catalog timestamps must be timezone-aware")
    return int(value.astimezone(UTC).timestamp() * 1_000_000_000)


__all__ = [
    "NautilusCatalogExport",
    "NautilusUnavailable",
    "export_archive_to_nautilus_catalog",
]
