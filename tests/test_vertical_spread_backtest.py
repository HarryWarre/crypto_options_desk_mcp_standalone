"""Unit tests for Directional Vertical Credit Spreads Backtest Engine."""

from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from options_lib.strategy.vertical_spread_backtest import (
    VerticalSpreadBacktestConfig,
    VerticalSpreadBacktestEngine,
)


def _generate_synthetic_chain_history(days: int = 15) -> pd.DataFrame:
    """Generate chronological options chain snapshots with trending spot movement."""
    records = []
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    for step in range(days * 4):  # 6-hour intervals
        ts = base_time + timedelta(hours=step * 6)
        # Upward drift to trigger Bull Put Spreads
        spot = 65000.0 + 300.0 * step

        for dte in [7, 14]:
            exp = ts + timedelta(days=dte)
            # Puts
            for strike_offset, delta in [(-3000, -0.18), (-6000, -0.05)]:
                k = spot + strike_offset
                mark = 450.0 if strike_offset == -3000 else 90.0
                records.append({
                    "timestamp": ts,
                    "symbol": f"BTC-{exp.strftime('%d%b%y')}-{int(k)}-P",
                    "currency": "BTC",
                    "expiry": exp,
                    "strike": float(k),
                    "type": "put",
                    "bid": mark - 5.0,
                    "ask": mark + 5.0,
                    "mark_price": mark,
                    "underlying_price": spot,
                    "delta": delta,
                    "iv": 0.55,
                    "dte": float(dte),
                })
            # Calls
            for strike_offset, delta in [(3000, 0.18), (6000, 0.05)]:
                k = spot + strike_offset
                mark = 460.0 if strike_offset == 3000 else 95.0
                records.append({
                    "timestamp": ts,
                    "symbol": f"BTC-{exp.strftime('%d%b%y')}-{int(k)}-C",
                    "currency": "BTC",
                    "expiry": exp,
                    "strike": float(k),
                    "type": "call",
                    "bid": mark - 5.0,
                    "ask": mark + 5.0,
                    "mark_price": mark,
                    "underlying_price": spot,
                    "delta": delta,
                    "iv": 0.55,
                    "dte": float(dte),
                })

    return pd.DataFrame(records)


def test_vertical_spread_backtest_execution():
    df = _generate_synthetic_chain_history(days=15)
    cfg = VerticalSpreadBacktestConfig(
        initial_capital=10000.0,
        target_short_delta=0.18,
        target_wing_delta=0.05,
        min_dte=5,
        max_dte=16,
        target_profit_pct=0.50,
        max_concurrent_positions=2,
    )
    engine = VerticalSpreadBacktestEngine(cfg)
    result = engine.run(df)

    assert result.total_trades > 0
    assert result.winning_trades > 0
    assert result.win_rate_pct >= 80.0
    assert result.total_net_pnl > 0.0
    assert result.profit_factor >= 1.0
    assert len(result.equity_curve) > 0


def test_vertical_spread_backtest_empty_df():
    engine = VerticalSpreadBacktestEngine()
    res = engine.run(pd.DataFrame())
    assert res.total_trades == 0
    assert res.total_net_pnl == 0.0


def test_vertical_spread_dynamic_sizing():
    df = _generate_synthetic_chain_history(days=15)
    # Dynamic sizing on BTC -> quantized to 0.1 BTC lot size
    cfg = VerticalSpreadBacktestConfig(
        initial_capital=10000.0,
        dynamic_sizing=True,
        risk_pct_per_trade=0.02,
        asset="BTC",
    )
    result = VerticalSpreadBacktestEngine(cfg).run(df)
    assert result.total_trades > 0
    assert result.trades[0].qty == 0.1

    # Fixed qty override
    cfg_fixed = VerticalSpreadBacktestConfig(
        initial_capital=10000.0,
        fixed_qty=0.5,
    )
    res_fixed = VerticalSpreadBacktestEngine(cfg_fixed).run(df)
    assert res_fixed.total_trades > 0
    assert res_fixed.trades[0].qty == 0.5


