# Bybit option history

The repository now has two deliberately separate historical-data paths:

1. `BybitPublicClient.get_option_mark_price_history()` downloads historical
   option mark-price OHLC candles from Bybit's
   [`/v5/market/mark-price-kline`](https://bybit-exchange.github.io/docs/v5/market/mark-kline)
   endpoint.
2. `BybitOptionSnapshotCollector` captures the latest option ticker response
   prospectively, and `JsonlOptionSnapshotArchive` persists and replays those
   complete snapshots.

Bybit's V5 ticker endpoint is latest-only. It does not provide a time-range
backfill of historical best bid/ask, IV, Greeks, open interest, and volume.
Mark-price candles therefore cannot be treated as executable historical
quotes or as a positive-EV backtest by themselves.

## Capture and replay

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bybit_api import BybitOptionSnapshotCollector, JsonlOptionSnapshotArchive
from bybit_api.public import BybitPublicClient

client = BybitPublicClient()
collector = BybitOptionSnapshotCollector(
    client._make_request,
    now_fn=lambda: datetime.now(UTC),
)
snapshots = await collector.capture(assets=("BTC", "ETH"))
archive = JsonlOptionSnapshotArchive(Path("data/bybit-option-snapshots.jsonl"))
archive.save(snapshots)

universe = archive.replay_universe(
    as_of=snapshots[0].source_timestamp,
    assets=("BTC",),
    max_age=timedelta(minutes=5),
)
```

Replay selects the latest source snapshot at or before `as_of`, requires an
explicit freshness tolerance, and never calls Bybit or falls back to today's
quotes. Incomplete or invalid records remain auditable in the archive but are
excluded from the valuation universe.

Snapshots make deterministic signal replay possible. They do not create
completed trade outcomes, prove look-ahead-free signal generation, or validate
positive expected value; those remain separate backtest work.
