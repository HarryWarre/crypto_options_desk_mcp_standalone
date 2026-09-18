"""Unit tests for Smart Position Monitor."""

from datetime import UTC, datetime, timedelta

import pytest

from position_monitoring.notebook import TrackedNotebookPosition
from position_monitoring.smart_monitor import SmartPositionMonitor


def test_smart_monitor_take_profit():
    """Position with profit exceeding target triggers TAKE_PROFIT (CHỐT LỜI)."""
    now = datetime.now(UTC)
    pos = TrackedNotebookPosition(
        id="tp-pos-1",
        created_at=now.isoformat(),
        asset="BTC",
        strategy_type="bull_call_vertical",
        legs=[
            {
                "symbol": "BTC-EXP-60000-C",
                "option_type": "call",
                "strike": 60000.0,
                "position": 1,
                "quantity": 1,
                "entry_price": 2000.0,
                "expiry": (now + timedelta(days=10)).isoformat(),
                "iv": 0.60,
            },
            {
                "symbol": "BTC-EXP-65000-C",
                "option_type": "call",
                "strike": 65000.0,
                "position": -1,
                "quantity": 1,
                "entry_price": 800.0,
                "expiry": (now + timedelta(days=10)).isoformat(),
                "iv": 0.60,
            },
        ],
        entry_spot=60000.0,
        target_profit_pct=50.0,
        stop_loss_pct=50.0,
    )

    monitor = SmartPositionMonitor()

    # Entry cost was (2000 - 800) = 1200. Target profit 50% = +600 (value >= 1800)
    # Simulate current prices where long call is 3500 and short call is 1500 => value = 2000 => pnl = +800 (+66.7%)
    contracts_map = {
        "BTC-EXP-60000-C": {"bid": 3450.0, "ask": 3550.0, "mark_price": 3500.0, "iv": 0.60},
        "BTC-EXP-65000-C": {"bid": 1450.0, "ask": 1550.0, "mark_price": 1500.0, "iv": 0.60},
    }

    eval_result = monitor.evaluate_position(
        pos,
        current_spot=64000.0,
        contracts_map=contracts_map,
        valuation_time=now,
    )

    assert eval_result.decision.action == "TAKE_PROFIT"
    assert eval_result.decision.action_vn == "CHỐT LỜI"
    assert "chốt lời" in eval_result.decision.reason.lower() or "lợi nhuận" in eval_result.decision.reason.lower()
    assert eval_result.unrealized_pnl > 0
    assert eval_result.decision.urgency == "high"


def test_smart_monitor_cut_loss():
    """Position with loss exceeding stop threshold triggers CUT_LOSS (BỎ / CẮT LỖ)."""
    now = datetime.now(UTC)
    pos = TrackedNotebookPosition(
        id="sl-pos-1",
        created_at=now.isoformat(),
        asset="BTC",
        strategy_type="bull_call_vertical",
        legs=[
            {
                "symbol": "BTC-EXP-60000-C",
                "option_type": "call",
                "strike": 60000.0,
                "position": 1,
                "quantity": 1,
                "entry_price": 2000.0,
                "expiry": (now + timedelta(days=10)).isoformat(),
                "iv": 0.60,
            },
            {
                "symbol": "BTC-EXP-65000-C",
                "option_type": "call",
                "strike": 65000.0,
                "position": -1,
                "quantity": 1,
                "entry_price": 800.0,
                "expiry": (now + timedelta(days=10)).isoformat(),
                "iv": 0.60,
            },
        ],
        entry_spot=60000.0,
        target_profit_pct=50.0,
        stop_loss_pct=50.0,
    )

    monitor = SmartPositionMonitor()

    # Entry cost was 1200. Loss of >= 50% means value <= 600 (pnl <= -600)
    contracts_map = {
        "BTC-EXP-60000-C": {"bid": 600.0, "ask": 700.0, "mark_price": 650.0, "iv": 0.60},
        "BTC-EXP-65000-C": {"bid": 100.0, "ask": 150.0, "mark_price": 125.0, "iv": 0.60},
    }

    eval_result = monitor.evaluate_position(
        pos,
        current_spot=55000.0,
        contracts_map=contracts_map,
        valuation_time=now,
    )

    assert eval_result.decision.action == "CUT_LOSS"
    assert eval_result.decision.action_vn == "BỎ / CẮT LỖ"
    assert eval_result.unrealized_pnl < 0
    assert eval_result.decision.urgency == "high"


def test_smart_monitor_hold():
    """Position within normal risk limits triggers HOLD (GIỮ)."""
    now = datetime.now(UTC)
    pos = TrackedNotebookPosition(
        id="hold-pos-1",
        created_at=now.isoformat(),
        asset="BTC",
        strategy_type="bull_call_vertical",
        legs=[
            {
                "symbol": "BTC-EXP-60000-C",
                "option_type": "call",
                "strike": 60000.0,
                "position": 1,
                "quantity": 1,
                "entry_price": 2000.0,
                "expiry": (now + timedelta(days=15)).isoformat(),
                "iv": 0.60,
            },
            {
                "symbol": "BTC-EXP-65000-C",
                "option_type": "call",
                "strike": 65000.0,
                "position": -1,
                "quantity": 1,
                "entry_price": 800.0,
                "expiry": (now + timedelta(days=15)).isoformat(),
                "iv": 0.60,
            },
        ],
        entry_spot=60000.0,
        target_profit_pct=50.0,
        stop_loss_pct=50.0,
    )

    monitor = SmartPositionMonitor()

    # Small move: long is 2100, short is 850 => value = 1250, pnl = +50 (+4.2%)
    contracts_map = {
        "BTC-EXP-60000-C": {"bid": 2050.0, "ask": 2150.0, "mark_price": 2100.0, "iv": 0.60},
        "BTC-EXP-65000-C": {"bid": 800.0, "ask": 900.0, "mark_price": 850.0, "iv": 0.60},
    }

    eval_result = monitor.evaluate_position(
        pos,
        current_spot=60500.0,
        contracts_map=contracts_map,
        valuation_time=now,
    )

    assert eval_result.decision.action == "HOLD"
    assert eval_result.decision.action_vn == "GIỮ"
    assert eval_result.decision.urgency == "low"
