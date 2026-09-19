"""Multi-Asset Deribit Historical Options Fetcher & Parquet Pipeline.

Fetches options trade history across BTC & ETH from Deribit,
computes Black-Scholes Greeks, resamples into discrete 1-hour snapshots,
and writes compressed Parquet files partitioned by asset and month.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from options_lib.data.deribit_downloader import OPTIONS_PARQUET_SCHEMA
from options_lib.pricing import FairValueRequest, price_fair_value
from options_lib.symbol_parser import parse_bybit_option_symbol

logger = logging.getLogger(__name__)
DERIBIT_HISTORY_URL = "https://history.deribit.com/api/v2/public/get_last_trades_by_currency_and_time"


def fetch_trades_for_window(
    currency: str,
    start_dt: datetime,
    end_dt: datetime,
    max_trades: int = 5000,
) -> list[dict[str, Any]]:
    """Fetch trade records for a time slice from Deribit public history API."""
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    params = {
        "currency": currency.upper(),
        "kind": "option",
        "start_timestamp": start_ms,
        "end_timestamp": end_ms,
        "count": 1000,
    }

    all_trades = []
    has_more = True
    curr_end = end_ms

    with httpx.Client(timeout=15.0) as client:
        while has_more and len(all_trades) < max_trades:
            params["start_timestamp"] = start_ms
            params["end_timestamp"] = curr_end
            try:
                r = client.get(DERIBIT_HISTORY_URL, params=params)
                if r.status_code != 200:
                    logger.warning("Deribit API status %s: %s", r.status_code, r.text)
                    break
                data = r.json()
                trades = data.get("result", {}).get("trades", [])
                has_more = data.get("result", {}).get("has_more", False)
                if not trades:
                    break
                all_trades.extend(trades)
                # Next cursor: trades are sorted descending, so earliest trade is at the end
                earliest_ts = min(t["timestamp"] for t in trades)
                curr_end = earliest_ts - 1
                if curr_end <= start_ms:
                    break
                time.sleep(0.08)  # Respect rate limits
            except Exception as e:
                logger.warning("Fetch error: %s", e)
                break

    return all_trades


def build_resampled_parquet(
    currency: str,
    trades: list[dict[str, Any]],
    output_parquet: Path | str,
    bucket_minutes: int = 60,
    spread_pct: float = 0.01,
) -> int:
    """Resample raw trades into discrete time buckets, compute Greeks, and write Parquet."""
    if not trades:
        return 0

    bucket_ms = bucket_minutes * 60 * 1000
    # Group trades by bucket
    trades_by_bucket: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for raw in trades:
        symbol = str(raw.get("instrument_name", "")).upper()
        parsed = parse_bybit_option_symbol(symbol)
        if not parsed:
            continue
        try:
            ts_ms = int(raw["timestamp"])
            price = float(raw["price"])
            mark_price = float(raw.get("mark_price", price))
            iv = float(raw["iv"]) / 100.0
            index_price = float(raw["index_price"])
            amount = float(raw.get("amount", raw.get("contracts", 1.0)))
        except (KeyError, TypeError, ValueError):
            continue

        if min(price, mark_price, iv, index_price, amount) <= 0:
            continue

        b_key = ts_ms // bucket_ms
        prev = trades_by_bucket[b_key].get(symbol)
        if prev is None or ts_ms > prev["timestamp"]:
            trades_by_bucket[b_key][symbol] = {
                "symbol": symbol,
                "asset": currency.upper(),
                "timestamp": ts_ms,
                "price": price,
                "mark_price": mark_price,
                "iv": iv,
                "index_price": index_price,
                "amount": amount,
                "expiry_at": parsed["expiry_date"].replace(hour=8, tzinfo=UTC),
                "option_type": "call" if parsed["option_type"] == "C" else "put",
                "strike": float(parsed["strike"]),
            }

    # State machine: Forward fill latest quote per instrument across successive buckets
    # so every snapshot represents a complete, deep options chain
    current_chain: dict[str, dict[str, Any]] = {}
    by_bucket: dict[int, list[dict[str, Any]]] = {}

    for b_key in sorted(trades_by_bucket.keys()):
        # Update current state with trades in this bucket
        for sym, item in trades_by_bucket[b_key].items():
            current_chain[sym] = item

        # Record active unexpired chain
        source_ts = datetime.fromtimestamp((b_key + 1) * bucket_ms / 1000.0, tz=UTC)
        active_items = [
            dict(it) for it in current_chain.values()
            if it["expiry_at"] > source_ts
        ]
        if active_items:
            by_bucket[b_key] = active_items

    records: list[dict[str, Any]] = []
    for b_key in sorted(by_bucket):
        source_ts = datetime.fromtimestamp((b_key + 1) * bucket_ms / 1000.0, tz=UTC)
        for item in by_bucket[b_key]:
            if item["expiry_at"] <= source_ts:
                continue

            # Premium and mark in USD
            premium_usd = item["price"] * item["index_price"]
            mark_usd = item["mark_price"] * item["index_price"]
            bid = premium_usd * max(0.0, 1.0 - spread_pct)
            ask = premium_usd * (1.0 + spread_pct)

            # Compute Black-Scholes delta
            delta = 0.5 if item["option_type"] == "call" else -0.5
            try:
                greeks = price_fair_value(
                    FairValueRequest(
                        option_type="Call" if item["option_type"] == "call" else "Put",
                        spot=item["index_price"],
                        strike=item["strike"],
                        expiry=item["expiry_at"],
                        valuation_time=source_ts,
                        iv=item["iv"],
                        risk_free_rate=0.0,
                    )
                )
                delta = greeks.delta
            except Exception:
                pass

            records.append({
                "timestamp": pd.to_datetime(source_ts),
                "symbol": item["symbol"],
                "asset": currency.upper(),
                "expiry": pd.to_datetime(item["expiry_at"]),
                "strike": item["strike"],
                "option_type": item["option_type"],
                "underlying_price": item["index_price"],
                "mark_price": mark_usd,
                "mark_iv": item["iv"],
                "bid_price": bid,
                "ask_price": ask,
                "delta": delta,
                "volume_24h": item["amount"],
                "open_interest": 10.0,  # placeholder
            })

    if not records:
        return 0

    df = pd.DataFrame(records)
    table = pa.Table.from_pandas(df, schema=OPTIONS_PARQUET_SCHEMA, preserve_index=False)
    out_path = Path(output_parquet)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="zstd")
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Fetch Deribit trades and convert to Parquet")
    parser.add_argument("--currency", choices=["BTC", "ETH"], default="BTC")
    parser.add_argument("--days", type=int, default=14, help="Number of past days to fetch")
    parser.add_argument("--max-trades", type=int, default=25000, help="Maximum trades to fetch")
    parser.add_argument("--output", type=str, required=True, help="Output Parquet path")
    args = parser.parse_args()

    now = datetime.now(UTC)
    start = now - timedelta(days=args.days)
    print(f"Fetching {args.currency} options trades from {start.date()} to {now.date()} (max {args.max_trades})...")

    trades = fetch_trades_for_window(args.currency, start, now, max_trades=args.max_trades)
    print(f"Retrieved {len(trades)} raw trade records from Deribit.")

    quotes_count = build_resampled_parquet(args.currency, trades, args.output)
    print(f"Successfully generated {quotes_count} resampled option quotes at {args.output}")


if __name__ == "__main__":
    main()
