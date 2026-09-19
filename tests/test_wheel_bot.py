"""Unit tests for The Wheel Strategy Bot Engine & Lifecycle Management."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from options_lib.strategy.wheel_bot import (
    WheelBot,
    WheelConfig,
    WheelLeg,
)


def _build_mock_chain(spot: float = 65000.0, dte_days: int = 10) -> list[dict]:
    """Build realistic mock Bybit/Deribit options chain."""
    now = datetime.now(UTC)
    exp_dt = now + timedelta(days=dte_days)
    exp_str = exp_dt.strftime("%Y-%m-%d")
    month_str = exp_dt.strftime("%b").upper()
    day_str = exp_dt.strftime("%d")
    year_str = exp_dt.strftime("%y")

    # Calls
    strikes_calls = [
        (66000, 0.45, 1800, 1850),
        (68000, 0.20, 600, 630),   # Target CC strike
        (72000, 0.05, 110, 120),
    ]
    # Puts
    strikes_puts = [
        (64000, -0.45, 1750, 1800),
        (62000, -0.20, 580, 610),  # Target CSP strike
        (58000, -0.05, 100, 110),
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


def test_select_csp_candidate():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = WheelConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "wheel_state.json"),
            target_put_delta=0.20,
            min_dte=5,
            max_dte=15,
        )
        bot = WheelBot(cfg)
        contracts = _build_mock_chain(spot=65000.0, dte_days=10)

        cand = bot.select_csp_candidate(contracts, spot=65000.0)
        assert cand is not None
        assert cand.option_type == "put"
        assert cand.strike == 62000.0
        assert abs(cand.delta - 0.20) < 0.05
        assert cand.phase == "CSP"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_select_cc_candidate_cost_basis_floor():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = WheelConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "wheel_state.json"),
            target_call_delta=0.20,
            min_dte=5,
            max_dte=15,
        )
        bot = WheelBot(cfg)
        contracts = _build_mock_chain(spot=65000.0, dte_days=10)

        # Cost basis is 66,000 -> must pick strike >= 66,000
        cand = bot.select_cc_candidate(contracts, spot=65000.0, cost_basis=66000.0)
        assert cand is not None
        assert cand.option_type == "call"
        assert cand.strike >= 66000.0
        assert cand.strike == 68000.0
        assert cand.phase == "CC"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_evaluate_lifecycle_tp_and_assignment():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = WheelConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "wheel_state.json"),
            target_profit_pct=0.50,
        )
        bot = WheelBot(cfg)
        now = datetime.now(UTC)
        exp_dt = now + timedelta(days=7)

        pos = WheelLeg(
            symbol="BTC-MOCK-60000-P",
            side="Sell",
            strike=60000.0,
            option_type="put",
            delta=-0.20,
            entry_price=1000.0,
            current_mark=1000.0,
            qty=1.0,
            role="cash_secured_put",
        )

        # 1. Take Profit when mark drops to <= 500 (50% TP)
        action, pnl = bot.evaluate_active_position(
            pos, current_mark=480.0, current_spot=64000.0, now=now, expiry_dt=exp_dt
        )
        assert action == "TAKE_PROFIT"
        assert pnl == pytest.approx(520.0)

        # 2. Expiry OTM when spot is well above put strike
        expiry_now = exp_dt
        action_otm, pnl_otm = bot.evaluate_active_position(
            pos, current_mark=0.0, current_spot=64000.0, now=expiry_now, expiry_dt=exp_dt
        )
        assert action_otm == "EXPIRED_OTM"
        assert pnl_otm == pytest.approx(1000.0)

        # 3. Assignment when spot is below put strike at expiry
        action_assign, _ = bot.evaluate_active_position(
            pos, current_mark=2000.0, current_spot=58000.0, now=expiry_now, expiry_dt=exp_dt
        )
        assert action_assign == "ASSIGNED"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

