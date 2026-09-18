from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from bybit_api.option_history import (
    HistoricalOptionQuote,
    HistoricalOptionSnapshot,
    JsonlOptionSnapshotArchive,
)
from options_lib.backtest_engine import (
    BacktestRunConfig,
    ExitPolicy,
    run_snapshot_backtest,
)
from options_lib.ev_validation import ValidationConfig
from options_lib.opportunity_scanner import ScanRequest

START = datetime(2026, 9, 15, 12, tzinfo=UTC)
SYMBOL = "BTC-30DEC26-100000-C-USDT"


def _snapshot(at: datetime, *, bid: float, ask: float, spot: float) -> HistoricalOptionSnapshot:
    quote = HistoricalOptionQuote(
        symbol=SYMBOL,
        expiry_at=datetime(2026, 12, 30, 8, tzinfo=UTC),
        expiry_code="30DEC26",
        option_type="Call",
        strike=100_000,
        underlying_price=spot,
        mark_price=(bid + ask) / 2,
        mark_iv=0.55,
        bid_price=bid,
        ask_price=ask,
        bid_iv=0.54,
        ask_iv=0.56,
        delta=0.45,
        gamma=0.00001,
        theta=-10,
        vega=100,
        volume_24h=10,
        open_interest=20,
    )
    return HistoricalOptionSnapshot(
        schema_version=1,
        source="test",
        source_timestamp=at,
        retrieval_timestamp=at + timedelta(seconds=1),
        asset="BTC",
        quotes=(quote,),
    )


def _opportunity() -> SimpleNamespace:
    return SimpleNamespace(
        asset="BTC",
        strategy="long_call",
        symbol=SYMBOL,
        expiry_at=datetime(2026, 12, 30, 8, tzinfo=UTC),
        max_loss=1300.0,
        legs=(
            SimpleNamespace(
                symbol=SYMBOL,
                position=1,
                ask_price=1300.0,
                bid_price=1100.0,
                strike=100_000.0,
                option_type="Call",
            ),
        ),
    )


def _config(
    archive: JsonlOptionSnapshotArchive,
    policy: ExitPolicy,
    *,
    duration: timedelta = timedelta(hours=2),
) -> BacktestRunConfig:
    return BacktestRunConfig(
        archive=archive,
        start_time=START,
        end_time=START + duration,
        assets=("BTC",),
        scan_request=ScanRequest(
            risk_free_rate=0.05,
            assets=("BTC",),
            strategies=("long_call",),
        ),
        exit_policy=policy,
        signal_interval=timedelta(minutes=1),
        validation=ValidationConfig(
            minimum_train_samples=0,
            minimum_holdout_samples=1,
            lookahead_verified=True,
        ),
    )


def test_snapshot_backtest_replays_signal_and_closes_at_profit_target(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save(
        [
            _snapshot(START, bid=1100, ask=1300, spot=95_000),
            _snapshot(START + timedelta(hours=1), bid=2500, ask=2600, spot=97_000),
        ]
    )

    seen_times: list[datetime] = []

    def scanner(universe, _request):
        seen_times.append(universe.valuation_time)
        return SimpleNamespace(opportunities=(_opportunity(),))

    result = run_snapshot_backtest(
        _config(archive, ExitPolicy(type="profit_target", profit_target_pct=0.5)),
        scanner=scanner,
    )

    assert seen_times == [START, START + timedelta(hours=1)]
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "profit_target"
    assert trade.net_pnl > 0
    assert trade.fees == 0
    assert result.data_quality.lookahead_free is True
    assert result.equity_curve[-1]["equity"] == trade.net_pnl
    assert result.report.holdout.trade_count == 1


def test_snapshot_backtest_settles_at_expiry_without_future_option_quote(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    expiry = datetime(2026, 9, 15, 13, tzinfo=UTC)
    snapshot = _snapshot(expiry, bid=1300, ask=1400, spot=102_000)
    snapshot = HistoricalOptionSnapshot(
        schema_version=1,
        source=snapshot.source,
        source_timestamp=snapshot.source_timestamp,
        retrieval_timestamp=snapshot.retrieval_timestamp,
        asset=snapshot.asset,
        quotes=(
            HistoricalOptionQuote(
                **{
                    **snapshot.quotes[0].__dict__,
                    "expiry_at": expiry,
                }
            ),
        ),
    )
    archive.save([_snapshot(START, bid=1100, ask=1300, spot=95_000), snapshot])

    opportunity = _opportunity()
    opportunity.expiry_at = expiry

    result = run_snapshot_backtest(
        _config(archive, ExitPolicy(type="hold_to_expiry")),
        scanner=lambda _universe, _request: SimpleNamespace(opportunities=(opportunity,)),
    )

    assert result.trades[0].exit_reason == "expiry"
    assert result.trades[0].exit_time == expiry


def test_snapshot_backtest_blocks_active_duplicate_but_allows_reentry_after_exit(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save(
        [
            _snapshot(START, bid=1100, ask=1300, spot=95_000),
            _snapshot(START + timedelta(hours=1), bid=1400, ask=1500, spot=95_500),
            _snapshot(START + timedelta(hours=2), bid=2500, ask=2600, spot=97_000),
            _snapshot(START + timedelta(hours=3), bid=2500, ask=2600, spot=97_000),
        ]
    )

    result = run_snapshot_backtest(
        _config(
            archive,
            ExitPolicy(type="profit_target", profit_target_pct=0.5),
            duration=timedelta(hours=3),
        ),
        scanner=lambda _universe, _request: SimpleNamespace(opportunities=(_opportunity(),)),
    )

    assert len(result.trades) == 2
    assert [(trade.entry_time, trade.exit_time) for trade in result.trades] == [
        (START, START + timedelta(hours=2)),
        (START + timedelta(hours=2), START + timedelta(hours=3)),
    ]
    assert result.trades[0].exit_reason == "profit_target"
    assert result.trades[1].exit_reason == "profit_target"


def test_backtest_requires_archived_data(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "missing.jsonl")
    with pytest.raises(ValueError, match="no archived snapshots"):
        run_snapshot_backtest(_config(archive, ExitPolicy()))
