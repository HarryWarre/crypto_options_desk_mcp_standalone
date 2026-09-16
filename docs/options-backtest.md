# Options backtest

The app now has a chronological backtest endpoint for Bybit option snapshot
archives. It replays the existing scanner at historical timestamps, enters
using the archived top-of-book, closes using a selectable exit rule, settles
at expiry when possible, and sends completed outcomes through the
train/holdout EV validator.

## Data source

Set the archive captured by `BybitOptionSnapshotCollector`:

```bash
export OPTIONS_BACKTEST_ARCHIVE=./data/bybit-options.jsonl
```

The archive must contain complete quotes: bid, ask, mark IV, underlying price,
Greeks, open interest and volume. Mark-price candles alone cannot produce an
executable backtest. The endpoint returns `422 backtest_data_unavailable`
instead of silently substituting live data or a current mark.

For a local smoke test without a prospectively captured Bybit archive, the
repository includes an explicit Deribit trade-derived adapter. It downloads
public historical trades separately, computes Greeks from the recorded IV and
underlying, and labels its synthetic bid/ask and liquidity assumptions:

```bash
uv run python scripts/build_deribit_trade_snapshot_archive.py \
  --input-dir /tmp/flowsurface-deribit-trades \
  --output ./data/deribit-btc-options.jsonl
export OPTIONS_BACKTEST_ARCHIVE=./data/deribit-btc-options.jsonl
```

This fallback is useful for exercising signal and exit-policy logic, but it is
not evidence of historical queue execution: public historical trades do not
include the historical order book or open interest.

## HTTP request

```http
POST /api/v1/backtests
```

```json
{
  "assets": ["BTC"],
  "start_time": "2026-01-01T00:00:00Z",
  "end_time": "2026-06-30T00:00:00Z",
  "filters": {
    "strategies": ["long_call"],
    "min_dte": 7,
    "max_dte": 60,
    "fee_per_contract": 2.5,
    "slippage_bps": 7,
    "quantity": 1,
    "contract_multiplier": 1
  },
  "exit_policy": {
    "type": "profit_target",
    "profit_target_pct": 0.5
  },
  "signal_interval_minutes": 60,
  "minimum_train_samples": 30,
  "minimum_holdout_samples": 30
}
```

Supported exit policies are `hold_to_expiry`, `profit_target`, `stop_loss`,
`min_dte` and `end_of_test`. The response contains trade-level `entry_time`,
`exit_time`, `exit_reason`, gross/net P&L, fees, slippage, return percentage,
an equity curve, unresolved signals and data-quality warnings.

## NautilusTrader catalog

NautilusTrader is an optional native Rust/Python dependency. Install it in a
separate Python 3.12–3.14 environment on a supported platform:

```bash
uv venv --python 3.13 .venv-nautilus
uv pip install --python .venv-nautilus/bin/python \
  "nautilus-trader==2.0.0rc6"
```

The bridge `export_archive_to_nautilus_catalog()` writes native
`CryptoOption`, `QuoteTick` and `OptionGreeks` records to a
`ParquetDataCatalog`. Nautilus still needs a catalog before `BacktestNode` can
run; it does not download missing Bybit history during a backtest.

The current Bybit archive does not contain bid/ask sizes or historical
instrument increments. The exporter therefore uses an explicit synthetic
size of one contract and records that assumption in its result. It is suitable
for structural replay, not queue-position or depth-sensitive execution claims.
