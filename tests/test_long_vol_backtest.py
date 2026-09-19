"""Unit tests for Long Volatility Backtest Engine."""

from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from options_lib.strategy.long_vol_backtest import (
    LongVolBacktestConfig,
    LongVolBacktestEngine,
)


def _generate_synthetic_straddle_chain(days: int = 15) -> pd.DataFrame:
    records = []
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    for step in range(days * 4):  # 6-hour snapshots
        ts = base_time + timedelta(hours=step * 6)
        # Fast moving spot to generate RV >= IV
        spot = 65000.0 + 800.0 * ((step % 6) - 3)
        exp = ts + timedelta(days=10)

        # ATM Strike 65000 Call and Put
        records.append({
            "timestamp": ts,
            "symbol": f"BTC-{exp.strftime('%d%b%y')}-65000-C",
            "currency": "BTC",
            "expiry": exp,
            "strike": 65000.0,
            "type": "call",
            "bid": 1450.0,
            "ask": 1550.0,
            "mark_price": 1500.0,
            "underlying_price": spot,
            "delta": 0.50,
            "iv": 0.40,
            "dte": 10.0,
        })
        records.append({
            "timestamp": ts,
            "symbol": f"BTC-{exp.strftime('%d%b%y')}-65000-P",
            "currency": "BTC",
            "expiry": exp,
            "strike": 65000.0,
            "type": "put",
            "bid": 1450.0,
            "ask": 1550.0,
            "mark_price": 1500.0,
            "underlying_price": spot,
            "delta": -0.50,
            "iv": 0.40,
            "dte": 10.0,
        })

    return pd.DataFrame(records)


def test_long_vol_backtest_execution():
    df = _generate_synthetic_straddle_chain(days=15)
    cfg = LongVolBacktestConfig(
        initial_capital=10000.0,
        min_dte=5,
        max_dte=18,
        min_rv_iv_ratio=0.50, # Ensure entries in synthetic test
        target_profit_pct=0.35,
        max_loss_pct=0.25,
        max_concurrent_positions=2,
    )
    engine = LongVolBacktestEngine(cfg)
    res = engine.run(df)

    assert res.total_trades > 0
    assert len(res.trades) == res.total_trades
    assert res.total_net_pnl is not None
    assert len(res.equity_curve) > 0


def test_long_vol_backtest_empty():
    engine = LongVolBacktestEngine()
    res = engine.run(pd.DataFrame())
    assert res.total_trades == 0
    assert res.total_net_pnl == 0.0


def test_long_vol_dynamic_sizing():
    df = _generate_synthetic_straddle_chain(days=15)
    cfg = LongVolBacktestConfig(
        initial_capital=10000.0,
        min_rv_iv_ratio=0.50,
        dynamic_sizing=True,
        asset="BTC",
        risk_pct_per_trade=0.02,
    )
    engine = LongVolBacktestEngine(cfg)
    res = engine.run(df)
    assert res.total_trades > 0
    for tr in res.trades:
        assert tr.qty > 0
        assert round(tr.qty % 0.1, 4) in (0.0, 0.1)

