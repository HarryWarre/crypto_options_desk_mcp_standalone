"""Unit tests for The Wheel Strategy Backtest Engine."""

from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from options_lib.strategy.wheel_backtest import (
    WheelBacktestConfig,
    WheelBacktestEngine,
)


def _generate_synthetic_chain_history(days: int = 15) -> pd.DataFrame:
    """Generate chronological options chain snapshots with underlying price movement."""
    records = []
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    spot = 65000.0

    for step in range(days * 4):  # 6-hour intervals
        ts = base_time + timedelta(hours=step * 6)
        # Gentle drift
        spot = 65000.0 + 500.0 * (step % 5)

        for dte in [7, 14]:
            exp = ts + timedelta(days=dte)
            # Puts
            for strike_offset, delta in [(-3000, -0.20), (-5000, -0.10)]:
                k = spot + strike_offset
                mark = 600.0 if dte == 7 else 900.0
                records.append({
                    "timestamp": ts,
                    "symbol": f"BTC-{exp.strftime('%d%b%y')}-{int(k)}-P",
                    "currency": "BTC",
                    "expiry": exp,
                    "strike": float(k),
                    "type": "put",
                    "bid": mark - 10.0,
                    "ask": mark + 10.0,
                    "mark_price": mark,
                    "underlying_price": spot,
                    "delta": delta,
                    "iv": 0.55,
                    "dte": float(dte),
                })
            # Calls
            for strike_offset, delta in [(3000, 0.20), (5000, 0.10)]:
                k = spot + strike_offset
                mark = 620.0 if dte == 7 else 950.0
                records.append({
                    "timestamp": ts,
                    "symbol": f"BTC-{exp.strftime('%d%b%y')}-{int(k)}-C",
                    "currency": "BTC",
                    "expiry": exp,
                    "strike": float(k),
                    "type": "call",
                    "bid": mark - 10.0,
                    "ask": mark + 10.0,
                    "mark_price": mark,
                    "underlying_price": spot,
                    "delta": delta,
                    "iv": 0.55,
                    "dte": float(dte),
                })

    return pd.DataFrame(records)


def test_wheel_backtest_engine_execution():
    df = _generate_synthetic_chain_history(days=15)
    cfg = WheelBacktestConfig(
        initial_capital=10000.0,
        target_put_delta=0.20,
        target_call_delta=0.20,
        min_dte=5,
        max_dte=16,
        target_profit_pct=0.50,
        max_concurrent_positions=2,
    )
    engine = WheelBacktestEngine(cfg)
    result = engine.run(df)

    assert result.total_trades > 0
    assert result.winning_trades > 0
    assert result.win_rate_pct >= 80.0
    assert result.total_net_pnl > 0.0
    assert result.profit_factor >= 1.0
    assert len(result.equity_curve) > 0


def test_wheel_backtest_empty_dataframe():
    engine = WheelBacktestEngine()
    res = engine.run(pd.DataFrame())
    assert res.total_trades == 0
    assert res.total_net_pnl == 0.0


def test_wheel_dynamic_sizing():
    df = _generate_synthetic_chain_history(days=15)
    cfg = WheelBacktestConfig(
        initial_capital=10000.0,
        dynamic_sizing=True,
        asset="BTC",
    )
    engine = WheelBacktestEngine(cfg)
    res = engine.run(df)
    assert res.total_trades > 0
    for tr in res.trades:
        assert tr.qty >= 0.1
        assert round(tr.qty % 0.1, 4) in (0.0, 0.1)


