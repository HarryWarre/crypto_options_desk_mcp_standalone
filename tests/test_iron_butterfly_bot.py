"""Unit tests for Dynamic Iron Butterfly Bot Strategy Engine."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from options_lib.strategy.iron_butterfly_bot import (
    IronButterflyBot,
    IronButterflyConfig,
)


def _build_mock_chain(spot: float = 65000.0, dte_days: int = 10) -> list[dict]:
    """Build mock options chain for Iron Butterfly testing with common ATM strike."""
    now = datetime.now(UTC)
    exp_dt = now + timedelta(days=dte_days)
    exp_str = exp_dt.strftime("%Y-%m-%d")
    month_str = exp_dt.strftime("%b").upper()
    day_str = exp_dt.strftime("%d")
    year_str = exp_dt.strftime("%y")

    contracts = []

    # ATM Strike: 65000 (both call and put)
    # Wing Call: 69000 (~0.08 delta)
    # Wing Put: 61000 (~-0.08 delta)
    calls_data = [
        (65000, 0.50, 1800, 1850),  # ATM Short Call
        (67000, 0.25, 800, 840),
        (69000, 0.08, 200, 220),   # Long Call Wing
    ]
    for strike, delta, bid, ask in calls_data:
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

    puts_data = [
        (65000, -0.50, 1800, 1850),  # ATM Short Put
        (63000, -0.25, 780, 820),
        (61000, -0.08, 190, 210),   # Long Put Wing
    ]
    for strike, delta, bid, ask in puts_data:
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


def test_select_iron_butterfly_candidate():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = IronButterflyConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "ib_state.json"),
            target_wing_delta=0.08,
            min_dte=3,
            max_dte=14,
        )
        bot = IronButterflyBot(cfg)
        contracts = _build_mock_chain(spot=65100.0, dte_days=10)

        cand = bot.select_candidate(contracts, spot=65100.0)
        assert cand is not None
        # ATM strike must be 65000 for both
        assert cand.atm_strike == 65000.0
        assert cand.short_call["strike"] == 65000.0
        assert cand.short_put["strike"] == 65000.0
        assert cand.long_call_strike == 69000.0
        assert cand.long_put_strike == 61000.0
        assert cand.net_credit > 0.0
        assert cand.max_loss > 0.0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_evaluate_iron_butterfly_lifecycle():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = IronButterflyConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "ib_state.json"),
            target_profit_pct=0.30,
            max_loss_multiplier=1.0,
        )
        bot = IronButterflyBot(cfg)

        entry_credit = 3000.0
        qty = 1.0

        # 1. 30% Take Profit when cost to close <= 2100 (70% remaining)
        action, pnl = bot.evaluate_position(entry_credit, current_combo_debit=2000.0, dte=5.0, qty=qty)
        assert action == "TAKE_PROFIT"
        assert pnl == pytest.approx(1000.0)

        # 2. Stop loss when cost expands by 1.0x credit (current debit >= 6000)
        action_sl, pnl_sl = bot.evaluate_position(entry_credit, current_combo_debit=6500.0, dte=5.0, qty=qty)
        assert action_sl == "STOP_LOSS"
        assert pnl_sl < -3000.0

        # 3. Expiration ATM Pinning
        action_exp, pnl_exp = bot.evaluate_position(entry_credit, current_combo_debit=0.0, dte=0.02, qty=qty)
        assert action_exp == "EXPIRED_OTM"
        assert pnl_exp == pytest.approx(3000.0)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
