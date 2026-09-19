"""Unit tests for Directional Vertical Credit Spreads Bot."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from options_lib.strategy.vertical_spread_bot import (
    VerticalSpreadBot,
    VerticalSpreadConfig,
)


def _build_mock_chain(spot: float = 65000.0, dte_days: int = 10) -> list[dict]:
    """Build mock options chain for vertical credit spread testing."""
    now = datetime.now(UTC)
    exp_dt = now + timedelta(days=dte_days)
    exp_str = exp_dt.strftime("%Y-%m-%d")
    month_str = exp_dt.strftime("%b").upper()
    day_str = exp_dt.strftime("%d")
    year_str = exp_dt.strftime("%y")

    contracts = []

    # Calls (for Bear Call Spread)
    # Short Call: 68000 (~0.18 delta), Long Wing: 71000 (~0.05 delta)
    strikes_calls = [
        (66000, 0.45, 1800, 1850),
        (68000, 0.18, 600, 630),
        (71000, 0.05, 120, 140),
    ]
    for strike, delta, bid, ask in strikes_calls:
        sym = f"BTC-{day_str}{month_str}{year_str}-{strike}-C"
        contracts.append({
            "symbol": sym,
            "option_type": "call",
            "strike": float(strike),
            "expiry": f"{exp_str}T08:00:00+00:00",
            "delta": delta,
            "bid": bid,
            "ask": ask,
            "mark_price": (bid + ask) / 2.0,
        })

    # Puts (for Bull Put Spread)
    # Short Put: 62000 (~-0.18 delta), Long Wing: 59000 (~-0.05 delta)
    strikes_puts = [
        (64000, -0.45, 1750, 1800),
        (62000, -0.18, 580, 610),
        (59000, -0.05, 110, 130),
    ]
    for strike, delta, bid, ask in strikes_puts:
        sym = f"BTC-{day_str}{month_str}{year_str}-{strike}-P"
        contracts.append({
            "symbol": sym,
            "option_type": "put",
            "strike": float(strike),
            "expiry": f"{exp_str}T08:00:00+00:00",
            "delta": delta,
            "bid": bid,
            "ask": ask,
            "mark_price": (bid + ask) / 2.0,
        })

    return contracts


def test_select_bull_put_candidate():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = VerticalSpreadConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "vs_state.json"),
        )
        bot = VerticalSpreadBot(cfg)
        contracts = _build_mock_chain(spot=65000.0, dte_days=10)

        cand = bot.select_candidate(contracts, spot=65000.0, trend_direction="BULLISH")
        assert cand is not None
        assert cand.spread_type == "BULL_PUT"
        assert cand.short_leg["strike"] == 62000.0
        assert cand.long_wing["strike"] == 59000.0
        assert cand.net_credit > 0.0
        assert cand.spread_width == 3000.0
        assert cand.max_loss == 3000.0 - cand.net_credit
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_select_bear_call_candidate():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = VerticalSpreadConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "vs_state.json"),
        )
        bot = VerticalSpreadBot(cfg)
        contracts = _build_mock_chain(spot=65000.0, dte_days=10)

        cand = bot.select_candidate(contracts, spot=65000.0, trend_direction="BEARISH")
        assert cand is not None
        assert cand.spread_type == "BEAR_CALL"
        assert cand.short_leg["strike"] == 68000.0
        assert cand.long_wing["strike"] == 71000.0
        assert cand.net_credit > 0.0
        assert cand.spread_width == 3000.0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_evaluate_lifecycle_tp_and_sl():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = VerticalSpreadConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "vs_state.json"),
            target_profit_pct=0.50,
            max_loss_multiplier=1.8,
        )
        bot = VerticalSpreadBot(cfg)

        entry_credit = 400.0
        qty = 1.0

        # 1. 50% Take Profit when cost to close <= 200
        action, pnl = bot.evaluate_position(entry_credit, current_spread_cost=180.0, dte=5.0, qty=qty)
        assert action == "TAKE_PROFIT"
        assert pnl == pytest.approx(220.0)

        # 2. Stop loss when cost expands beyond 1.8x credit
        action_sl, pnl_sl = bot.evaluate_position(entry_credit, current_spread_cost=1200.0, dte=5.0, qty=qty)
        assert action_sl == "STOP_LOSS"
        assert pnl_sl < -400.0 * 1.8

        # 3. Expiration OTM
        action_exp, pnl_exp = bot.evaluate_position(entry_credit, current_spread_cost=0.0, dte=0.02, qty=qty)
        assert action_exp == "EXPIRED_OTM"
        assert pnl_exp == pytest.approx(400.0)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

