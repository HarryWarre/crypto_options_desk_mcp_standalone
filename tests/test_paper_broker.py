"""Unit tests for Paper Broker, Matching Engine, Margin Calculator and Storage."""

import pytest
from pathlib import Path
import tempfile
import shutil

from options_lib.paper_broker.account import PaperAccount, PaperPosition
from options_lib.paper_broker.matching_engine import (
    MatchingEngine,
    PaperOrder,
    OrderType,
)
from options_lib.paper_broker.margin_calculator import MarginCalculator
from options_lib.paper_broker.storage import PaperStorage


def test_paper_account_lifecycle():
    acc = PaperAccount(account_id="test_acc", initial_capital=10000.0)
    assert acc.equity == 10000.0
    assert acc.cash_balance == 10000.0

    # 1. Open short call (Sell)
    trade1 = acc.apply_fill(
        symbol="BTC-27SEP26-68000-C",
        side="Sell",
        qty=0.1,
        price=500.0,
        fee=1.5,
        spot=64000.0,
        strategy_id="ic_1",
        leg_role="short_call",
    )
    # Cash increases by 0.1 * 500 - 1.5 = +48.5
    assert acc.cash_balance == pytest.approx(10048.5, rel=1e-4)
    assert len(acc.positions) == 1
    assert acc.positions["BTC-27SEP26-68000-C"].qty == 0.1

    # 2. Mark-to-market when price drops to 300 (profitable for short)
    unrealized = acc.mark_to_market({"BTC-27SEP26-68000-C": 300.0})
    # Profit = (500 - 300) * 0.1 = +20.0
    assert unrealized == pytest.approx(20.0, rel=1e-4)
    assert acc.equity == pytest.approx(10068.5, rel=1e-4)

    # 3. Buy to close position at 300
    trade2 = acc.apply_fill(
        symbol="BTC-27SEP26-68000-C",
        side="Buy",
        qty=0.1,
        price=300.0,
        fee=1.0,
        spot=64000.0,
    )
    assert trade2.realized_pnl == pytest.approx(20.0, rel=1e-4)
    # Cash decreases by 0.1 * 300 + 1.0 = 31.0 -> 10048.5 - 31.0 = 10017.5
    assert acc.cash_balance == pytest.approx(10017.5, rel=1e-4)
    assert len(acc.positions) == 0  # Fully closed
    assert acc.equity == pytest.approx(10017.5, rel=1e-4)


def test_matching_engine_fills_and_fees():
    engine = MatchingEngine(default_slippage_pct=0.01)  # 1% slippage

    # Market Buy with best_ask = 100
    order_buy = PaperOrder(
        symbol="BTC-27SEP26-70000-C",
        side="Buy",
        qty=0.1,
        order_type=OrderType.MARKET,
    )
    res_buy = engine.match_order(
        order=order_buy,
        best_bid=90.0,
        best_ask=100.0,
        spot=65000.0,
        apply_slippage=True,
    )
    assert res_buy.is_filled
    assert res_buy.filled_price == pytest.approx(101.0, rel=1e-4)  # 100 * 1.01
    assert res_buy.fee > 0

    # Market Sell with best_bid = 90
    order_sell = PaperOrder(
        symbol="BTC-27SEP26-70000-C",
        side="Sell",
        qty=0.1,
        order_type=OrderType.MARKET,
    )
    res_sell = engine.match_order(
        order=order_sell,
        best_bid=90.0,
        best_ask=100.0,
        spot=65000.0,
        apply_slippage=True,
    )
    assert res_sell.is_filled
    assert res_sell.filled_price == pytest.approx(89.1, rel=1e-4)  # 90 * 0.99


def test_margin_calculator_iron_condor():
    calc = MarginCalculator()

    # Create an Iron Condor portfolio:
    # Short Call 68000 (qty 0.1), Long Call 70000 (qty 0.1) -> Call Spread width = 2000 * 0.1 = $200
    # Short Put 60000 (qty 0.1), Long Put 58000 (qty 0.1) -> Put Spread width = 2000 * 0.1 = $200
    positions = {
        "BTC-27SEP26-68000-C": PaperPosition(
            symbol="BTC-27SEP26-68000-C",
            side="Sell",
            qty=0.1,
            entry_price=400.0,
            strategy_id="condor_btc",
            leg_role="short_call",
        ),
        "BTC-27SEP26-70000-C": PaperPosition(
            symbol="BTC-27SEP26-70000-C",
            side="Buy",
            qty=0.1,
            entry_price=100.0,
            strategy_id="condor_btc",
            leg_role="long_call",
        ),
        "BTC-27SEP26-60000-P": PaperPosition(
            symbol="BTC-27SEP26-60000-P",
            side="Sell",
            qty=0.1,
            entry_price=400.0,
            strategy_id="condor_btc",
            leg_role="short_put",
        ),
        "BTC-27SEP26-58000-P": PaperPosition(
            symbol="BTC-27SEP26-58000-P",
            side="Buy",
            qty=0.1,
            entry_price=100.0,
            strategy_id="condor_btc",
            leg_role="long_put",
        ),
    }

    summary = calc.evaluate_portfolio(
        positions=positions,
        equity=5000.0,
        spot_price=64000.0,
    )

    # Under Portfolio Margin for Iron Condor, IM is max(Call spread, Put spread) = max(200, 200) = 200
    assert summary.initial_margin == pytest.approx(200.0, rel=1e-4)
    # Utilization = 200 / 5000 = 4%
    assert summary.margin_utilization_pct == pytest.approx(4.0, rel=1e-2)
    assert not summary.is_warning
    assert not summary.is_critical
    assert not summary.is_liquidatable


def test_paper_storage_persistence():
    temp_dir = tempfile.mkdtemp()
    db_file = Path(temp_dir) / "test_paper.db"
    try:
        storage = PaperStorage(db_path=db_file)
        acc = storage.load_account(account_id="persisted_acc", default_capital=12000.0)
        assert acc.cash_balance == 12000.0

        # Place a trade
        acc.apply_fill(
            symbol="BTC-27SEP26-65000-C",
            side="Sell",
            qty=0.2,
            price=450.0,
            fee=2.0,
            spot=64000.0,
            strategy_id="test_strat",
        )

        calc = MarginCalculator()
        margin_sum = calc.evaluate_portfolio(acc.positions, acc.equity, 64000.0)
        storage.save_account(acc, margin_summary=margin_sum)

        # Restore in new storage instance
        storage2 = PaperStorage(db_path=db_file)
        restored_acc = storage2.load_account(account_id="persisted_acc")
        assert restored_acc.cash_balance == pytest.approx(acc.cash_balance, rel=1e-4)
        assert len(restored_acc.positions) == 1
        assert "BTC-27SEP26-65000-C" in restored_acc.positions
        assert len(restored_acc.trade_history) == 1

        snapshots = storage2.get_snapshots(account_id="persisted_acc")
        assert len(snapshots) == 1
        assert snapshots[0]["equity"] > 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

