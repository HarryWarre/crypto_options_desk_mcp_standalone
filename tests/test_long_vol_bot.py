"""Unit tests for Long Volatility Straddle & Strangle Bot."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from options_lib.strategy.long_vol_bot import (
    LongVolBot,
    LongVolConfig,
)


def _build_mock_straddle_chain(spot: float = 65000.0, dte_days: int = 10, iv: float = 0.50) -> list[dict]:
    now = datetime.now(UTC)
    exp_dt = now + timedelta(days=dte_days)
    exp_str = exp_dt.strftime("%Y-%m-%d")

    contracts = []
    # ATM Call
    contracts.append({
        "symbol": f"BTC-{exp_str}-65000-C",
        "option_type": "call",
        "strike": 65000.0,
        "expiry": f"{exp_str}T08:00:00+00:00",
        "delta": 0.50,
        "bid": 1450.0,
        "ask": 1550.0,
        "mark_price": 1500.0,
        "iv": iv,
    })
    # ATM Put
    contracts.append({
        "symbol": f"BTC-{exp_str}-65000-P",
        "option_type": "put",
        "strike": 65000.0,
        "expiry": f"{exp_str}T08:00:00+00:00",
        "delta": -0.50,
        "bid": 1450.0,
        "ask": 1550.0,
        "mark_price": 1500.0,
        "iv": iv,
    })
    return contracts


def test_select_long_vol_candidate():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = LongVolConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "lv_state.json"),
            min_dte=5,
            max_dte=18,
            min_rv_iv_ratio=1.00,
        )
        bot = LongVolBot(cfg)
        
        # Test 1: RV < IV -> No entry
        chain = _build_mock_straddle_chain(spot=65100.0, dte_days=10, iv=0.60)
        cand_none = bot.select_candidate(chain, spot=65100.0, realized_vol=0.50)
        assert cand_none is None

        # Test 2: RV >= IV -> Selects ATM Straddle
        cand = bot.select_candidate(chain, spot=65100.0, realized_vol=0.65)
        assert cand is not None
        assert cand.atm_strike == 65000.0
        assert cand.call_leg["side"] == "Buy"
        assert cand.put_leg["side"] == "Buy"
        assert cand.net_debit == 3000.0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_evaluate_long_vol_lifecycle():
    temp_dir = tempfile.mkdtemp()
    try:
        cfg = LongVolConfig(
            asset="BTC",
            db_path=str(Path(temp_dir) / "test.db"),
            log_dir=str(Path(temp_dir) / "logs"),
            state_file=str(Path(temp_dir) / "lv_state.json"),
            target_profit_pct=0.35,
            max_loss_pct=0.25,
            exit_dte_threshold=1.0,
        )
        bot = LongVolBot(cfg)
        entry_debit = 3000.0
        qty = 0.1

        # 1. 35% Take profit (value >= 4050)
        action, pnl = bot.evaluate_position(entry_debit, 4100.0, dte=5.0, qty=qty)
        assert action == "TAKE_PROFIT"
        assert pnl == pytest.approx(110.0)

        # 2. 25% Stop loss (value <= 2250)
        action, pnl = bot.evaluate_position(entry_debit, 2200.0, dte=5.0, qty=qty)
        assert action == "STOP_LOSS"
        assert pnl == pytest.approx(-80.0)

        # 3. Expiration exit (DTE <= 1.0)
        action, pnl = bot.evaluate_position(entry_debit, 2800.0, dte=0.8, qty=qty)
        assert action == "EXPIRY_EXIT"

        # 4. Hold
        action, pnl = bot.evaluate_position(entry_debit, 3100.0, dte=4.0, qty=qty)
        assert action == "HOLD"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
