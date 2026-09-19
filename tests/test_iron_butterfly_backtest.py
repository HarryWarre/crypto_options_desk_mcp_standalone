"""Unit tests for Dynamic Iron Butterfly Backtest Engine."""

from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from options_lib.strategy.iron_butterfly_backtest import (
    IronButterflyBacktestConfig,
    IronButterflyBacktestEngine,
)


def _generate_synthetic_chain_history(days: int = 15) -> pd.DataFrame:
    """Generate chronological options chain snapshots with range-bound spot movement."""
    records = []
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    for step in range(days * 4):  # 6-hour intervals
        ts = base_time + timedelta(hours=step * 6)
        # Oscillating around 65000 (ideal for pinning)
        spot = 65000.0 + 200.0 * ((step % 4) - 2)

        for dte in [7, 14]:
            exp = ts + timedelta(days=dte)
            # ATM Strike 65000
            # Puts
            for strike, delta, mark in [(65000, -0.50, 1500.0), (61000, -0.08, 180.0)]:
                records.append({
                    "timestamp": ts,
                    "symbol": f"BTC-{exp.strftime('%d%b%y')}-{int(strike)}-P",
                    "currency": "BTC",
                    "expiry": exp,
                    "strike": float(strike),
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
            for strike, delta, mark in [(65000, 0.50, 1520.0), (69000, 0.08, 190.0)]:
                records.append({
                    "timestamp": ts,
                    "symbol": f"BTC-{exp.strftime('%d%b%y')}-{int(strike)}-C",
                    "currency": "BTC",
                    "expiry": exp,
                    "strike": float(strike),
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


def test_iron_butterfly_backtest_execution():
    df = _generate_synthetic_chain_history(days=15)
    cfg = IronButterflyBacktestConfig(
        initial_capital=10000.0,
        target_wing_delta=0.08,
        min_dte=3,
        max_dte=16,
        target_profit_pct=0.30,
        max_concurrent_positions=2,
    )
    engine = IronButterflyBacktestEngine(cfg)
    result = engine.run(df)

    assert result.total_trades > 0
    assert result.winning_trades > 0
    assert result.win_rate_pct >= 80.0
    assert result.total_net_pnl > 0.0
    assert result.profit_factor >= 1.0
    assert len(result.equity_curve) > 0


def test_iron_butterfly_backtest_empty_df():
    engine = IronButterflyBacktestEngine()
    res = engine.run(pd.DataFrame())
    assert res.total_trades == 0
    assert res.total_net_pnl == 0.0


def test_iron_butterfly_dynamic_sizing():
    df = _generate_synthetic_chain_history(days=15)
    # Dynamic sizing with asset=BTC should quantize to Deribit lot size (0.1 BTC multiple)
    cfg = IronButterflyBacktestConfig(
        initial_capital=10000.0,
        dynamic_sizing=True,
        asset="BTC",
        risk_pct_per_trade=0.02,
    )
    engine = IronButterflyBacktestEngine(cfg)
    res = engine.run(df)
    assert res.total_trades > 0
    for tr in res.trades:
        assert tr.qty > 0
        assert round(tr.qty % 0.1, 4) in (0.0, 0.1)


