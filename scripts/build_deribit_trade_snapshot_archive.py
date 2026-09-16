"""Build the app's snapshot archive from public Deribit historical trades.

This is an explicitly labelled fallback for environments without a historical
options quote archive.  Deribit historical trades contain a traded price,
mark price, IV, and index price, but not a historical top-of-book quote or
open interest.  The resulting archive therefore uses the last trade as the
price anchor, a configurable synthetic bid/ask band, and a positive liquidity
placeholder so the scanner can be exercised without silently claiming that
these are historical bid/ask/OI observations.

The script expects JSON responses saved from
``public/get_last_trades_by_currency_and_time``.  It keeps the latest valid
trade per instrument in each fixed time bucket and writes the canonical JSONL
format consumed by ``JsonlOptionSnapshotArchive``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bybit_api.option_history import (
    HistoricalOptionQuote,
    HistoricalOptionSnapshot,
    JsonlOptionSnapshotArchive,
)
from bybit_api.options_market_data import OptionDataQualityIssue
from options_lib.pricing import (
    FairValueRequest,
    PricingValidationError,
    price_fair_value,
)
from options_lib.symbol_parser import parse_bybit_option_symbol

SECONDS_PER_DAY = 86_400.0


def main() -> int:
    args = _parse_args()
    bucket = timedelta(minutes=args.bucket_minutes)
    if bucket <= timedelta(0):
        raise SystemExit("--bucket-minutes must be positive")
    snapshots, stats = build_snapshots(
        args.input_dir,
        bucket=bucket,
        spread_pct=args.spread_pct,
        liquidity_placeholder=args.liquidity_placeholder,
    )
    result = JsonlOptionSnapshotArchive(args.output).save(snapshots)
    first = snapshots[0].source_timestamp.isoformat() if snapshots else "—"
    last = snapshots[-1].source_timestamp.isoformat() if snapshots else "—"
    print(
        json.dumps(
            {
                "output": str(args.output),
                "snapshots": result.snapshots_written,
                "quotes": result.quotes_written,
                "raw_records": stats["raw_records"],
                "valid_trades": stats["valid_trades"],
                "skipped_trades": stats["skipped_trades"],
                "instruments": stats["instruments"],
                "range": {"start": first, "end": last},
                "mode": "deribit_last_trade_proxy",
                "warnings": [
                    "bid/ask are synthetic around the last traded price",
                    "open interest is a positive placeholder because public historical trades do not include OI",
                    "volume_24h is trade amount for the latest trade in the bucket, not exchange 24h volume",
                ],
            },
            indent=2,
        )
    )
    return 0


def build_snapshots(
    input_dir: Path,
    *,
    bucket: timedelta,
    spread_pct: float,
    liquidity_placeholder: float,
) -> tuple[tuple[HistoricalOptionSnapshot, ...], dict[str, int]]:
    if spread_pct < 0 or not math.isfinite(spread_pct):
        raise ValueError("spread_pct must be finite and non-negative")
    if liquidity_placeholder <= 0 or not math.isfinite(liquidity_placeholder):
        raise ValueError("liquidity_placeholder must be finite and positive")
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory does not exist: {input_dir}")

    bucket_ms = int(bucket.total_seconds() * 1000)
    latest: dict[tuple[int, str], dict[str, Any]] = {}
    stats = {"raw_records": 0, "valid_trades": 0, "skipped_trades": 0}

    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        trades = payload.get("result", {}).get("trades", [])
        if not isinstance(trades, list):
            continue
        stats["raw_records"] += len(trades)
        for trade in trades:
            normalized = _normalize_trade(trade)
            if normalized is None:
                stats["skipped_trades"] += 1
                continue
            stats["valid_trades"] += 1
            timestamp_ms = normalized["timestamp_ms"]
            bucket_key = timestamp_ms // bucket_ms
            key = (bucket_key, normalized["symbol"])
            previous = latest.get(key)
            if previous is None or timestamp_ms > previous["timestamp_ms"]:
                latest[key] = normalized

    by_bucket: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (bucket_key, _symbol), trade in latest.items():
        by_bucket[bucket_key].append(trade)

    snapshots: list[HistoricalOptionSnapshot] = []
    for bucket_key in sorted(by_bucket):
        source_timestamp = datetime.fromtimestamp(
            (bucket_key + 1) * bucket_ms / 1000.0,
            tz=UTC,
        )
        quotes: list[HistoricalOptionQuote] = []
        for trade in sorted(by_bucket[bucket_key], key=lambda item: item["symbol"]):
            quote = _trade_to_quote(
                trade,
                source_timestamp=source_timestamp,
                spread_pct=spread_pct,
                liquidity_placeholder=liquidity_placeholder,
            )
            if quote is not None:
                quotes.append(quote)
        if not quotes:
            continue
        snapshots.append(
            HistoricalOptionSnapshot(
                schema_version=1,
                source="deribit-historical-trades:last-trade-proxy:v1",
                source_timestamp=source_timestamp,
                retrieval_timestamp=source_timestamp,
                asset="BTC",
                quotes=tuple(quotes),
                issues=(
                    OptionDataQualityIssue(
                        code="trade_derived_quote",
                        message=(
                            "Quote reconstructed from the latest Deribit trade in the bucket; "
                            "historical bid/ask and open interest are unavailable"
                        ),
                        asset="BTC",
                    ),
                ),
            )
        )
    stats["instruments"] = len({trade["symbol"] for trade in latest.values()})
    return tuple(snapshots), stats


def _normalize_trade(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    symbol = str(raw.get("instrument_name") or "").upper()
    parsed = parse_bybit_option_symbol(symbol)
    try:
        timestamp_ms = int(raw["timestamp"])
        price = float(raw["price"])
        mark_price = float(raw.get("mark_price", price))
        iv_percent = float(raw["iv"])
        index_price = float(raw["index_price"])
        amount = float(raw.get("amount", raw.get("contracts", 1.0)))
    except (KeyError, TypeError, ValueError):
        return None
    if (
        parsed is None
        or timestamp_ms <= 0
        or price <= 0
        or mark_price <= 0
        or iv_percent <= 0
        or index_price <= 0
        or amount <= 0
        or not all(math.isfinite(value) for value in (price, mark_price, iv_percent, index_price, amount))
    ):
        return None
    return {
        "symbol": symbol,
        "timestamp_ms": timestamp_ms,
        "price": price,
        "mark_price": mark_price,
        "iv": iv_percent / 100.0,
        "index_price": index_price,
        "amount": amount,
        "expiry_at": parsed["expiry_date"].replace(hour=8, tzinfo=UTC),
        "option_type": "Call" if parsed["option_type"] == "C" else "Put",
        "strike": float(parsed["strike"]),
        "expiry_code": symbol.split("-")[1],
    }


def _trade_to_quote(
    trade: dict[str, Any],
    *,
    source_timestamp: datetime,
    spread_pct: float,
    liquidity_placeholder: float,
) -> HistoricalOptionQuote | None:
    expiry_at = trade["expiry_at"]
    if expiry_at <= source_timestamp:
        return None
    premium_usd = trade["price"] * trade["index_price"]
    mark_usd = trade["mark_price"] * trade["index_price"]
    bid = premium_usd * max(0.0, 1.0 - spread_pct)
    ask = premium_usd * (1.0 + spread_pct)
    if min(premium_usd, mark_usd, bid, ask) <= 0:
        return None
    try:
        greeks = price_fair_value(
            FairValueRequest(
                option_type=trade["option_type"],
                spot=trade["index_price"],
                strike=trade["strike"],
                expiry=expiry_at,
                valuation_time=source_timestamp,
                iv=trade["iv"],
                risk_free_rate=0.0,
            )
        )
    except (PricingValidationError, ValueError):
        return None
    return HistoricalOptionQuote(
        symbol=trade["symbol"],
        expiry_at=expiry_at,
        expiry_code=trade["expiry_code"],
        option_type=trade["option_type"],
        strike=trade["strike"],
        underlying_price=trade["index_price"],
        mark_price=mark_usd,
        mark_iv=trade["iv"],
        bid_price=bid,
        ask_price=ask,
        bid_iv=trade["iv"],
        ask_iv=trade["iv"],
        delta=greeks.delta,
        gamma=greeks.gamma,
        theta=greeks.theta,
        vega=greeks.vega,
        volume_24h=max(trade["amount"], liquidity_placeholder),
        open_interest=liquidity_placeholder,
        quote_currency="USD_PROXY",
        settle_currency="BTC",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bucket-minutes", type=float, default=60.0)
    parser.add_argument(
        "--spread-pct",
        type=float,
        default=0.01,
        help="synthetic half-spread around the trade price; default 1%%",
    )
    parser.add_argument(
        "--liquidity-placeholder",
        type=float,
        default=1.0,
        help="positive OI/liquidity placeholder required by the app's surface gate",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
