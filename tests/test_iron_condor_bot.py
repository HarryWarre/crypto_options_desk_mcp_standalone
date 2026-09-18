"""Unit tests for Iron Condor Bot Strategy Engine & Lifecycle Management."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from options_lib.strategy.iron_condor_bot import (
    IronCondorBot,
    IronCondorConfig,
)


def _build_mock_chain(spot: float = 65000.0, dte_days: int = 10) -> list[dict]:
    """Build a realistic Bybit-like options chain with calls and puts."""
    now = datetime.now(UTC)
    exp_dt = now + timedelta(days=dte_days)
    exp_str = exp_dt.strftime("%Y-%m-%d")
    month_str = exp_dt.strftime("%b").upper()
    day_str = exp_dt.strftime("%d")
    year_str = exp_dt.strftime("%y")

    # Strikes:
    # Long Put: 58000, Short Put: 61000, Short Call: 69000, Long Call: 72000
    strikes_calls = [
        (66000, 0.40, 2000, 2050),
        (69000, 0.15, 600, 620),   # Short Call
        (72000, 0.03, 120, 130),   # Long Call Wing
    ]
    strikes_puts = [
        (64000, -0.40, 1900, 1950),
        (61000, -0.15, 580, 600),  # Short Put
        (58000, -0.03, 110, 120),  # Long Put Wing
    ]

    contracts = []
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


def test_select_iron_condor_candidate():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = IronCondorConfig(
            asset="BTC",
            paper_mode=True,
            target_short_delta=0.15,
            target_wing_delta=0.03,
            min_dte=5,
            max_dte=15,
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
        )
        bot = IronCondorBot(cfg)

        chain = _build_mock_chain(spot=65000.0, dte_days=10)
        candidate = bot.select_iron_condor_candidate(chain, spot=65000.0)

        assert candidate is not None
        assert candidate.short_call["strike"] == 69000.0
        assert candidate.long_call["strike"] == 72000.0
        assert candidate.short_put["strike"] == 61000.0
        assert candidate.long_put["strike"] == 58000.0
        # Net credit = (610 + 590) - (125 + 115) = ~960 per unit
        assert candidate.net_credit_per_unit > 0
        assert candidate.max_loss_per_unit > 0
        assert candidate.pop >= 0.70
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_iron_condor_lifecycle_and_take_profit():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = IronCondorConfig(
            asset="BTC",
            paper_mode=True,
            initial_capital=10000.0,
            target_profit_pct=0.50,
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            qty=0.1,
        )
        bot = IronCondorBot(cfg)
        spot = 65000.0
        chain = _build_mock_chain(spot=spot, dte_days=10)

        candidate = bot.select_iron_condor_candidate(chain, spot)
        assert candidate is not None

        # 1. Execute Open Condor (Legging-in)
        opened = bot.execute_open_condor(candidate, spot)
        assert opened
        assert bot._active_condor_id is not None
        assert len(bot.paper_account.positions) == 4
        assert bot._entry_credit > 0

        # 2. Check position holding when prices haven't decayed enough
        action = bot.monitor_and_manage_position(spot, chain)
        assert action == "HOLDING"

        # 3. Simulate Theta decay: All option prices drop by 70%
        decayed_chain = []
        for c in chain:
            c_copy = dict(c)
            c_copy["bid"] = c["bid"] * 0.30
            c_copy["ask"] = c["ask"] * 0.30
            c_copy["mark_price"] = c["mark_price"] * 0.30
            decayed_chain.append(c_copy)

        # 4. Trigger Take Profit at 50%
        action2 = bot.monitor_and_manage_position(spot, decayed_chain)
        assert action2 == "CLOSED_TP"
        assert len(bot.paper_account.positions) == 0  # All 4 legs closed
        assert bot._total_compounded_profit > 0
        assert bot.paper_account.equity > 10000.0  # Account grew!

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_iron_condor_stop_loss():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = IronCondorConfig(
            asset="BTC",
            paper_mode=True,
            initial_capital=10000.0,
            max_loss_multiplier=1.5,
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            qty=0.1,
        )
        bot = IronCondorBot(cfg)
        spot = 65000.0
        chain = _build_mock_chain(spot=spot, dte_days=10)

        candidate = bot.select_iron_condor_candidate(chain, spot)
        bot.execute_open_condor(candidate, spot)

        # Simulate catastrophic market pump: Short call price spikes by 400%
        loss_chain = []
        for c in chain:
            c_copy = dict(c)
            if c["strike"] == 69000.0:  # Short call breached
                c_copy["bid"] = 2800.0
                c_copy["ask"] = 2900.0
                c_copy["mark_price"] = 2850.0
            loss_chain.append(c_copy)

        action = bot.monitor_and_manage_position(spot, loss_chain)
        assert action == "CLOSED_SL"
        assert len(bot.paper_account.positions) == 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
