from datetime import UTC, datetime, timedelta

import pytest

from bybit_api.option_history import (
    HistoricalOptionQuote,
    HistoricalOptionSnapshot,
    JsonlOptionSnapshotArchive,
)
from bybit_api.options_market_data import OptionDataQualityIssue
from options_lib.backtest_engine import ExitPolicy
from options_lib.opportunity_scanner import Opportunity, OpportunityLeg, ScanRequest, ScanResult
from options_lib.strategy_head_dataset import (
    StrategyHeadDatasetConfig,
    build_strategy_head_dataset,
    extract_asof_features,
)

T0 = datetime(2026, 9, 15, 12, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)
EXPIRY = datetime(2026, 12, 30, 8, tzinfo=UTC)
SYMBOL = "BTC-30DEC26-100000-C"


def _quote(*, at: datetime, bid: float, ask: float, spot: float) -> HistoricalOptionQuote:
    return HistoricalOptionQuote(
        symbol=SYMBOL,
        expiry_at=EXPIRY,
        expiry_code="30DEC26",
        option_type="Call",
        strike=100_000.0,
        underlying_price=spot,
        mark_price=(bid + ask) / 2.0,
        mark_iv=0.55,
        bid_price=bid,
        ask_price=ask,
        bid_iv=0.54,
        ask_iv=0.56,
        delta=0.45,
        gamma=0.00001,
        theta=-10.0,
        vega=100.0,
        volume_24h=10.0,
        open_interest=20.0,
    )


def _snapshot(
    at: datetime,
    *,
    bid: float,
    ask: float,
    spot: float,
    source: str = "fixture",
    issues: tuple[OptionDataQualityIssue, ...] = (),
) -> HistoricalOptionSnapshot:
    return HistoricalOptionSnapshot(
        schema_version=1,
        source=source,
        source_timestamp=at,
        retrieval_timestamp=at + timedelta(seconds=2),
        asset="BTC",
        quotes=(_quote(at=at, bid=bid, ask=ask, spot=spot),),
        issues=issues,
    )


def _opportunity() -> Opportunity:
    leg = OpportunityLeg(
        symbol=SYMBOL,
        option_type="Call",
        strike=100_000.0,
        expiry_at=EXPIRY,
        spot_price=100_000.0,
        bid_price=9.0,
        ask_price=10.0,
        market_iv=0.55,
        fair_iv=0.56,
        fair_price=11.0,
        delta=0.45,
        volume_24h=10.0,
        open_interest=20.0,
        quote_timestamp=T0,
        position=1,
    )
    return Opportunity(
        asset="BTC",
        symbol=SYMBOL,
        strategy="long_call",
        option_type="Call",
        strike=100_000.0,
        expiry_at=EXPIRY,
        dte=105.0,
        spot_price=100_000.0,
        bid_price=9.0,
        ask_price=10.0,
        market_mid=9.5,
        market_iv=0.55,
        fair_iv=0.56,
        iv_edge=0.01,
        surface_status="ok",
        fair_price=11.0,
        executable_entry=10.0,
        fee=1.0,
        slippage_cost=0.1,
        edge_after_costs=0.8,
        edge_pct=0.08,
        max_loss=10.0,
        delta=0.45,
        volume_24h=10.0,
        open_interest=20.0,
        quote_timestamp=T0,
        evidence_status="insufficient_evidence",
        entry_fee=1.0,
        exit_fee=1.0,
        entry_slippage_cost=0.1,
        exit_slippage_cost=0.09,
        total_cost=2.19,
        long_symbol=SYMBOL,
        long_strike=100_000.0,
        legs=(leg,),
    )


def _scan_result(*, at: datetime, opportunities: tuple[Opportunity, ...] = ()) -> ScanResult:
    return ScanResult(
        timestamp=at,
        data_timestamp=at,
        opportunities=opportunities,
        rejections=(),
        asset_failures=(),
        issues=(),
    )


def _config(
    archive: JsonlOptionSnapshotArchive,
    *,
    end_time: datetime,
    strategies: tuple[str, ...] = ("long_call", "long_put"),
    signal_interval: timedelta = timedelta(days=1),
) -> StrategyHeadDatasetConfig:
    return StrategyHeadDatasetConfig(
        archive=archive,
        start_time=T0,
        end_time=end_time,
        assets=("BTC",),
        scan_request=ScanRequest(
            risk_free_rate=0.0,
            assets=("BTC",),
            strategies=strategies,
            fee_per_contract=1.0,
            slippage_bps=100.0,
        ),
        signal_interval=signal_interval,
        exit_policy=ExitPolicy(type="end_of_test"),
    )


def test_build_dataset_records_after_cost_outcome_no_trade_and_quality(tmp_path) -> None:
    issue = OptionDataQualityIssue("thin_history", "fixture warning", asset="BTC")
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save(
        [
            _snapshot(
                T0,
                bid=9.0,
                ask=10.0,
                spot=100_000.0,
                source="deribit-trade-derived:last-trade-proxy",
                issues=(issue,),
            ),
            _snapshot(T1, bid=20.0, ask=21.0, spot=101_000.0),
        ]
    )

    seen_strategies: list[tuple[str, ...]] = []

    def scanner(universe, request):
        seen_strategies.append(request.strategies)
        if request.strategies == ("long_call",):
            return _scan_result(at=universe.valuation_time, opportunities=(_opportunity(),))
        return _scan_result(at=universe.valuation_time)

    dataset = build_strategy_head_dataset(_config(archive, end_time=T1), scanner=scanner)

    assert seen_strategies == [("long_call",), ("long_put",)]
    assert len(dataset.rows) == 2
    long_call, long_put = dataset.rows
    assert long_call.outcome_label == "PROFIT"
    assert long_call.net_pnl == pytest.approx(7.4)
    assert long_call.costs == pytest.approx(2.3)
    assert long_call.outcome_timestamp == T1
    assert long_call.outcome_source_timestamp == T1
    assert long_call.included is True
    assert long_put.outcome_label == "NO_TRADE"
    assert long_put.included is True
    assert long_call.source_timestamp == T0
    assert long_call.retrieval_timestamp == T0 + timedelta(seconds=2)
    assert "thin_history:fixture warning" in long_call.data_quality_warnings
    assert "proxy_source:deribit-trade-derived:last-trade-proxy" in long_call.proxy_warnings


def test_missing_future_outcome_is_excluded_with_reason(tmp_path) -> None:
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save([_snapshot(T0, bid=9.0, ask=10.0, spot=100_000.0)])

    dataset = build_strategy_head_dataset(
        _config(archive, end_time=T0, strategies=("long_call",)),
        scanner=lambda universe, _request: _scan_result(
            at=universe.valuation_time, opportunities=(_opportunity(),)
        ),
    )

    row = dataset.rows[0]
    assert row.included is False
    assert row.outcome_label is None
    assert "future_outcome_unavailable" in row.excluded_reasons


def test_features_and_replay_are_as_of_only(tmp_path) -> None:
    first = _snapshot(T0, bid=9.0, ask=10.0, spot=100_000.0)
    future = _snapshot(T1, bid=90.0, ask=100.0, spot=900_000.0)
    archive = JsonlOptionSnapshotArchive(tmp_path / "options.jsonl")
    archive.save([first, future])

    captured_spots: list[float] = []

    def scanner(universe, _request):
        captured_spots.append(universe.contracts[0].spot_price)
        return _scan_result(at=universe.valuation_time)

    dataset = build_strategy_head_dataset(
        _config(
            archive,
            end_time=T1,
            strategies=("long_call",),
            signal_interval=timedelta(hours=1),
        ),
        scanner=scanner,
    )

    assert captured_spots == [100_000.0, 900_000.0]
    assert dict(dataset.rows[0].features)["underlying_price"] == 100_000.0
    assert dict(dataset.rows[1].features)["underlying_price"] == 900_000.0
    extracted = extract_asof_features(first)
    assert extracted.source_timestamp == T0
    assert dict(extracted.values)["underlying_price"] == 100_000.0
