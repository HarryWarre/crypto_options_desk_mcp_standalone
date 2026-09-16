from datetime import UTC, datetime, timedelta

import pytest

from bybit_api.option_history import (
    BybitOptionSnapshotCollector,
    HistoricalDataUnavailable,
    HistoricalOptionQuote,
    HistoricalOptionSnapshot,
    JsonlOptionSnapshotArchive,
    SnapshotConflictError,
    SnapshotQuery,
)

SOURCE_TIME = datetime(2026, 9, 15, 12, tzinfo=UTC)
RETRIEVED_TIME = SOURCE_TIME + timedelta(seconds=1)
SYMBOL = "BTC-30DEC26-100000-C"


def quote(**overrides) -> HistoricalOptionQuote:
    values = {
        "symbol": SYMBOL,
        "expiry_at": datetime(2026, 12, 30, 8, tzinfo=UTC),
        "expiry_code": "30DEC26",
        "option_type": "Call",
        "strike": 100000.0,
        "underlying_price": 95000.0,
        "mark_price": 1200.0,
        "mark_iv": 0.55,
        "bid_price": 1100.0,
        "ask_price": 1300.0,
        "delta": 0.45,
        "gamma": 0.00001,
        "theta": -10.0,
        "vega": 100.0,
        "volume_24h": 10.0,
        "open_interest": 20.0,
    }
    values.update(overrides)
    return HistoricalOptionQuote(**values)


def snapshot(*, source_time=SOURCE_TIME, option_quote=None) -> HistoricalOptionSnapshot:
    return HistoricalOptionSnapshot(
        schema_version=1,
        source="fixture",
        source_timestamp=source_time,
        retrieval_timestamp=RETRIEVED_TIME,
        asset="BTC",
        quotes=(option_quote or quote(),),
    )


def test_jsonl_roundtrip_is_canonical_and_deduplicates(tmp_path) -> None:
    path = tmp_path / "options.jsonl"
    archive = JsonlOptionSnapshotArchive(path)
    first = archive.save([snapshot(), snapshot()])
    before = path.read_bytes()

    assert first.snapshots_written == 1
    assert first.duplicates_removed == 1
    assert archive.save(archive.load().snapshots).duplicates_removed == 1
    assert path.read_bytes() == before
    assert archive.load(SnapshotQuery(assets=("ETH",))).snapshots == ()


def test_conflicting_snapshot_identity_is_rejected(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save([snapshot()])

    with pytest.raises(SnapshotConflictError):
        archive.save([snapshot(option_quote=quote(mark_iv=0.7))])


def test_replay_selects_latest_snapshot_at_or_before_as_of(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save(
        [
            snapshot(source_time=SOURCE_TIME - timedelta(hours=1)),
            snapshot(source_time=SOURCE_TIME),
            snapshot(source_time=SOURCE_TIME + timedelta(hours=1)),
        ]
    )

    replayed = archive.replay_universe(
        as_of=SOURCE_TIME + timedelta(minutes=5),
        assets=("BTC",),
        max_age=timedelta(minutes=10),
    )

    assert replayed.source == "bybit-option-snapshot:v1"
    assert replayed.valuation_time == SOURCE_TIME + timedelta(minutes=5)
    assert replayed.contracts[0].quote_timestamp == SOURCE_TIME


def test_replay_fails_when_history_is_stale(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save([snapshot()])

    with pytest.raises(HistoricalDataUnavailable, match="max_age"):
        archive.replay_universe(
            as_of=SOURCE_TIME + timedelta(minutes=1),
            assets=("BTC",),
            max_age=timedelta(seconds=30),
        )


@pytest.mark.asyncio
async def test_collector_records_bybit_source_time_and_normalizes_ticker() -> None:
    async def request(endpoint, params):
        assert endpoint == "/v5/market/tickers"
        assert params == {"category": "option", "baseCoin": "BTC"}
        return {
            "retCode": 0,
            "time": int(SOURCE_TIME.timestamp() * 1000),
            "result": {
                "list": [
                    {
                        "symbol": SYMBOL,
                        "underlyingPrice": "95000",
                        "markPrice": "1200",
                        "markIv": "0.55",
                        "bid1Price": "1100",
                        "ask1Price": "1300",
                        "delta": "0.45",
                        "gamma": "0.00001",
                        "theta": "-10",
                        "vega": "100",
                        "volume24h": "10",
                        "openInterest": "20",
                    }
                ]
            },
        }

    collector = BybitOptionSnapshotCollector(
        request,
        now_fn=lambda: RETRIEVED_TIME,
    )
    captured = await collector.capture(assets=("btc",))

    assert captured[0].source_timestamp == SOURCE_TIME
    assert captured[0].retrieval_timestamp == RETRIEVED_TIME
    assert captured[0].quotes[0].mark_iv == 0.55


def test_incomplete_quote_is_persisted_but_not_valuation_ready(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save([snapshot(option_quote=quote(mark_iv=None))])

    with pytest.raises(HistoricalDataUnavailable, match="no valuation-ready"):
        archive.replay_universe(as_of=SOURCE_TIME, assets=("BTC",))
