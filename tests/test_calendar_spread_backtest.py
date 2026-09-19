"""Unit tests for Calendar Spread Strategy Backtest Engine."""

from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from options_lib.strategy.calendar_spread_backtest import (
    CalendarSpreadBacktestConfig,
    CalendarSpreadBacktestEngine,
)


def _generate_synthetic_calendar_chain(days: int = 20) -> pd.DataFrame:
    """Generate synthetic options snapshots with both Near-Term (7 DTE) and Far-Term (25 DTE) contracts."""
    records = []
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    for step in range(days * 4):  # 6-hour snapshots
        ts = base_time + timedelta(hours=step * 6)
        # Gentle price fluctuation around 65000 (ideal for calendar spreads)
        spot = 65000.0 + 100.0 * ((step % 4) - 2)

        near_exp = ts + timedelta(days=7)
        far_exp = ts + timedelta(days=25)

        for expiry, dte, near_or_far in [(near_exp, 7.0, "near"), (far_exp, 25.0, "far")]:
            # Near leg mark: ~1200, Far leg mark: ~2400
            mark = 1200.0 if near_or_far == "near" else 2400.0
            records.append({
                "timestamp": ts,
                "symbol": f"BTC-{expiry.strftime('%d%b%y')}-65000-C",
                "currency": "BTC",
                "expiry": expiry,
                "strike": 65000.0,
                "type": "call",
                "bid": mark - 10.0,
                "ask": mark + 10.0,
                "mark_price": mark,
                "underlying_price": spot,
                "delta": 0.50,
                "iv": 0.55,
                "dte": dte,
            })

    return pd.DataFrame(records)


def test_calendar_spread_backtest_execution():
    df = _generate_synthetic_calendar_chain(days=20)
    cfg = CalendarSpreadBacktestConfig(
        initial_capital=10000.0,
        min_near_dte=4,
        max_near_dte=12,
        min_far_dte=16,
        max_far_dte=40,
        target_profit_pct=0.25,
        max_loss_pct=0.30,
        max_concurrent_positions=2,
    )
    engine = CalendarSpreadBacktestEngine(cfg)
    res = engine.run(df)

    assert res.total_trades > 0
    assert len(res.trades) == res.total_trades
    assert res.total_net_pnl is not None
    assert len(res.equity_curve) > 0


def test_calendar_spread_backtest_empty_df():
    engine = CalendarSpreadBacktestEngine()
    res = engine.run(pd.DataFrame())
    assert res.total_trades == 0
    assert res.total_net_pnl == 0.0


def test_calendar_spread_dynamic_sizing():
    df = _generate_synthetic_calendar_chain(days=20)
    cfg = CalendarSpreadBacktestConfig(
        initial_capital=10000.0,
        dynamic_sizing=True,
        asset="BTC",
        risk_pct_per_trade=0.02,
    )
    engine = CalendarSpreadBacktestEngine(cfg)
    res = engine.run(df)
    assert res.total_trades > 0
    for tr in res.trades:
        assert tr.qty > 0
        assert round(tr.qty % 0.1, 4) in (0.0, 0.1)
