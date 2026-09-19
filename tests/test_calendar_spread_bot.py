"""Unit tests for Calendar & Diagonal Spread Bot Strategy Engine."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from options_lib.strategy.calendar_spread_bot import (
    CalendarSpreadBot,
    CalendarSpreadConfig,
)


def _build_mock_two_tenor_chain(spot: float = 65000.0) -> list[dict]:
    """Build mock options chain for Calendar Spread testing with Near (7 DTE) and Far (30 DTE) contracts."""
    now = datetime.now(UTC)
    near_exp = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    far_exp = (now + timedelta(days=30)).strftime("%Y-%m-%d")

    contracts = []
    # Near Leg (7 DTE) ATM strike 65000: Mark = 1200
    contracts.append({
        "symbol": "BTC-7D-65000-C",
        "option_type": "call",
        "strike": 65000.0,
        "expiry": f"{near_exp}T08:00:00+00:00",
        "delta": 0.50,
        "bid": 1180.0,
        "ask": 1220.0,
        "mark_price": 1200.0,
    })
    # Far Leg (30 DTE) ATM strike 65000: Mark = 2500
    contracts.append({
        "symbol": "BTC-30D-65000-C",
        "option_type": "call",
        "strike": 65000.0,
        "expiry": f"{far_exp}T08:00:00+00:00",
        "delta": 0.50,
        "bid": 2480.0,
        "ask": 2520.0,
        "mark_price": 2500.0,
    })
    return contracts


def test_select_calendar_spread_candidate():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = CalendarSpreadConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "cs_state.json"),
            min_near_dte=4,
            max_near_dte=12,
            min_far_dte=20,
            max_far_dte=45,
        )
        bot = CalendarSpreadBot(cfg)
        contracts = _build_mock_two_tenor_chain(spot=65100.0)

        cand = bot.select_candidate(contracts, spot=65100.0, option_type="call")
        assert cand is not None
        assert cand.strike == 65000.0
        assert cand.option_type == "call"
        assert cand.near_leg["side"] == "Sell"
        assert cand.far_leg["side"] == "Buy"
        assert cand.net_debit == 2500.0 - 1200.0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_evaluate_calendar_spread_lifecycle():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = CalendarSpreadConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "cs_state.json"),
            target_profit_pct=0.25,
            max_loss_pct=0.30,
        )
        bot = CalendarSpreadBot(cfg)
        entry_debit = 1000.0
        qty = 0.1

        # 1. Take profit (value expands to >= 1250)
        action, pnl = bot.evaluate_position(entry_debit, 1300.0, near_dte=5.0, qty=qty)
        assert action == "TAKE_PROFIT"
        assert pnl == pytest.approx(30.0)

        # 2. Stop loss (value drops to <= 700)
        action, pnl = bot.evaluate_position(entry_debit, 650.0, near_dte=5.0, qty=qty)
        assert action == "STOP_LOSS"
        assert pnl == pytest.approx(-35.0)

        # 3. Near expiry harvest (near_dte <= 0.05)
        action, pnl = bot.evaluate_position(entry_debit, 1100.0, near_dte=0.04, qty=qty)
        assert action == "NEAR_EXPIRY_ROLL"

        # 4. Hold
        action, pnl = bot.evaluate_position(entry_debit, 1050.0, near_dte=4.0, qty=qty)
        assert action == "HOLD"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

