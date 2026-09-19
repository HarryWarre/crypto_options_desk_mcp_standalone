"""Unit tests for Parquet Downloader and Iron Condor Backtest Engine."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pandas as pd
import pytest

from options_lib.data.deribit_downloader import (
    convert_jsonl_to_parquet,
    load_parquet_snapshots,
)
from options_lib.strategy.iron_condor_backtest import (
    BacktestConfig,
    IronCondorBacktestEngine,
)


def _generate_mock_snapshots_df(num_steps: int = 20) -> pd.DataFrame:
    """Generate mock 15-minute options chains over multiple days."""
    records = []
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    expiry = base_time + timedelta(days=10)
    spot = 65000.0

    strikes = [
        # (strike, type, delta, mark)
        (58000.0, "put", -0.03, 120.0),   # Long Put Wing
        (61000.0, "put", -0.15, 600.0),   # Short Put
        (69000.0, "call", 0.15, 620.0),   # Short Call
        (72000.0, "call", 0.03, 130.0),   # Long Call Wing
    ]

    for step in range(num_steps):
        t = base_time + timedelta(hours=step * 4)
        # Spot moves slightly, theta decays marks over time
        decay = 1.0 - (step * 0.04)  # prices decay by 4% per step
        curr_spot = spot + (step * 150.0)

        for strike, otype, delta, mark in strikes:
            curr_mark = max(10.0, mark * decay)
            records.append({
                "timestamp": t,
                "symbol": f"BTC-10JAN26-{int(strike)}-{'C' if otype == 'call' else 'P'}",
                "asset": "BTC",
                "expiry": expiry,
                "strike": strike,
                "option_type": otype,
                "underlying_price": curr_spot,
                "mark_price": curr_mark,
                "mark_iv": 0.55,  # 55% IV
                "bid_price": curr_mark * 0.98,
                "ask_price": curr_mark * 1.02,
                "delta": delta,
                "volume_24h": 100.0,
                "open_interest": 50.0,
            })

    return pd.DataFrame(records)


def test_parquet_conversion_and_reading():
    temp_dir = tempfile.mkdtemp()
    try:
        jsonl_sample = Path(temp_dir) / "sample.jsonl"
        parquet_out = Path(temp_dir) / "sample.parquet"

        # Create sample jsonl line
        with open(jsonl_sample, "w") as f:
            line = {
                "source_timestamp": "2026-01-01T00:00:00Z",
                "quotes": [{
                    "symbol": "BTC-10JAN26-70000-C",
                    "expiry_at": "2026-01-10T08:00:00Z",
                    "strike": 70000.0,
                    "option_type": "Call",
                    "underlying_price": 65000.0,
                    "mark_price": 500.0,
                    "mark_iv": 0.50,
                    "bid_price": 490.0,
                    "ask_price": 510.0,
                    "delta": 0.20,
                    "volume_24h": 10.0,
                    "open_interest": 5.0,
                }]
            }
            import json
            f.write(json.dumps(line) + "\n")

        stats = convert_jsonl_to_parquet(jsonl_sample, parquet_out)
        assert stats["quotes_converted"] == 1
        assert parquet_out.exists()

        df = load_parquet_snapshots(parquet_out, asset="BTC")
        assert len(df) == 1
        assert df["strike"].iloc[0] == 70000.0
        assert df["option_type"].iloc[0] == "call"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_iron_condor_backtest_lifecycle():
    df = _generate_mock_snapshots_df(num_steps=15)
    config = BacktestConfig(
        initial_capital=10000.0,
        target_short_delta=0.15,
        target_wing_delta=0.03,
        iv_rv_threshold=0.0,  # disable IV filter for unit test
        target_profit_pct=0.50,
        max_loss_multiplier=2.0,
    )
    engine = IronCondorBacktestEngine(config)
    result = engine.run(df)

    assert result.total_trades >= 1
    # Check trade record
    first_trade = result.trades[0]
    assert first_trade.entry_credit > 0
    assert first_trade.exit_time is not None
    # Because prices decayed over time, this Iron Condor should take profit (TP 50%)
    assert first_trade.exit_reason in ("TAKE_PROFIT_50", "FORCE_CLOSE", "EXPIRY_ROLL")
    assert first_trade.realized_pnl > 0
    assert result.win_rate_pct >= 50.0
    assert result.total_net_pnl > 0


def test_iron_condor_empty_chain():
    engine = IronCondorBacktestEngine()
    result = engine.run(pd.DataFrame())
    assert result.total_trades == 0
    assert result.win_rate_pct == 0.0
    assert result.total_net_pnl == 0.0


def test_iron_condor_dynamic_sizing_quantization():
    df = _generate_mock_snapshots_df(num_steps=15)
    # 1. Dynamic sizing: $10,000 capital, 2% risk budget = $200. Max loss ~ $2000 -> qty = 0.1 BTC
    cfg_dyn = BacktestConfig(
        initial_capital=10000.0,
        dynamic_sizing=True,
        risk_pct_per_trade=0.02,
        iv_rv_threshold=0.0,
        asset="BTC",
    )
    res_dyn = IronCondorBacktestEngine(cfg_dyn).run(df)
    assert res_dyn.total_trades >= 1
    assert res_dyn.trades[0].qty == 0.1

    # 2. Fixed qty override
    cfg_fixed = BacktestConfig(
        initial_capital=10000.0,
        fixed_qty=0.5,
        iv_rv_threshold=0.0,
    )
    res_fixed = IronCondorBacktestEngine(cfg_fixed).run(df)
    assert res_fixed.total_trades >= 1
    assert res_fixed.trades[0].qty == 0.5


