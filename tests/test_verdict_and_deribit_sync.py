"""Unit tests for VerdictAgent, Deribit sync, and EquityHistoryStore."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from options_app.api import create_app
from options_app.bot_manager import BotManager
from options_lib.paper_broker.deribit_adapter import DeribitBrokerAdapter
from options_lib.paper_broker.equity_history import EquityHistoryStore
from options_lib.paper_broker.matching_engine import PaperOrderResult
from options_lib.risk.portfolio_risk_engine import RiskAssessmentResult
from options_lib.swarm.candidate_signal import CandidateLeg, CandidateSignal
from options_lib.verdict.verdict_agent import VerdictAgent, VerdictDecision, VerdictStatus


def _make_dummy_signal() -> CandidateSignal:
    leg = CandidateLeg(
        symbol="BTC-29SEP26-60000-C",
        strike=60000.0,
        option_type="Call",
        side="BUY",
        ratio=1.0,
        mark_price=1000.0,
        iv=0.50,
        delta=0.50,
        dte=10.0,
    )
    return CandidateSignal(
        signal_id="sig_test_verdict",
        strategy="vertical_spread",
        trader_name="VerticalSpreadTrader",
        asset="BTC",
        expiry_date="2026-09-29",
        dte=10.0,
        direction="BULLISH",
        action_type="CREDIT",
        net_premium_per_unit=500.0,
        max_loss_per_unit=1500.0,
        max_profit_per_unit=500.0,
        legs=(leg,),
        model_edge=25.0,
        underlying_spot=60000.0,
        raw_candidate={},
        created_at=datetime.now(UTC).isoformat(),
    )


def test_verdict_auto_approves_and_executes():
    agent = VerdictAgent()
    signal = _make_dummy_signal()
    risk_res = RiskAssessmentResult(
        candidate_id=signal.signal_id,
        strategy=signal.strategy,
        asset="BTC",
        approved=True,
        allocated_qty=0.4,
        allocated_max_loss=600.0,
        allocated_margin=600.0,
        margin_utilization_after=20.0,
        net_delta_impact=0.2,
        rejection_reasons=(),
        warnings=(),
    )

    mock_broker = MagicMock(spec=DeribitBrokerAdapter)
    mock_broker.execute_order.return_value = PaperOrderResult(
        order_id="deribit_ord_12345",
        symbol="BTC-29SEP26-60000-C",
        side="Buy",
        status="Filled",
        filled_qty=0.4,
        filled_price=1000.0,
    )

    decision = agent.process_candidate(candidate=signal, risk_res=risk_res, broker=mock_broker)

    assert isinstance(decision, VerdictDecision)
    assert decision.status == VerdictStatus.APPROVED
    assert decision.allocated_qty == 0.4
    assert len(decision.execution_order_ids) == 1
    assert decision.execution_order_ids[0] == "deribit_ord_12345"
    mock_broker.execute_order.assert_called_once()


def test_verdict_rejects_disapproved_risk():
    agent = VerdictAgent()
    signal = _make_dummy_signal()
    risk_res = RiskAssessmentResult(
        candidate_id=signal.signal_id,
        strategy=signal.strategy,
        asset="BTC",
        approved=False,
        allocated_qty=0.0,
        allocated_max_loss=0.0,
        allocated_margin=0.0,
        margin_utilization_after=65.0,
        net_delta_impact=0.0,
        rejection_reasons=("margin_utilization_exceeded",),
        warnings=(),
    )

    mock_broker = MagicMock(spec=DeribitBrokerAdapter)
    decision = agent.process_candidate(candidate=signal, risk_res=risk_res, broker=mock_broker)

    assert decision.status == VerdictStatus.REJECTED
    assert decision.allocated_qty == 0.0
    assert "margin_utilization_exceeded" in decision.reasons
    assert len(decision.execution_order_ids) == 0
    mock_broker.execute_order.assert_not_called()


def test_equity_history_store(tmp_path):
    db_file = tmp_path / "equity_test.db"
    store = EquityHistoryStore(db_path=str(db_file))

    now = datetime.now(UTC)
    # Record snapshot 2 days ago (out of 1D, in 1W)
    store.record_snapshot(
        currency="BTC",
        equity_usd=9500.0,
        balance_crypto=0.15,
        margin_used=1000.0,
        margin_utilization_pct=10.5,
        timestamp=(now - timedelta(days=2)).isoformat(),
    )
    # Record snapshot 2 hours ago (in 1D, 1W, 1M)
    store.record_snapshot(
        currency="BTC",
        equity_usd=10200.0,
        balance_crypto=0.17,
        margin_used=1200.0,
        margin_utilization_pct=11.7,
        timestamp=(now - timedelta(hours=2)).isoformat(),
    )

    hist_1d = store.get_history(timeframe="1d", currency="BTC")
    assert len(hist_1d) == 1
    assert hist_1d[0]["equity_usd"] == 10200.0

    hist_1w = store.get_history(timeframe="1w", currency="BTC")
    assert len(hist_1w) == 2


def test_bot_manager_status_contains_deribit_and_swarm():
    bm = BotManager(asset="BTC", paper_mode=True)
    status = bm.get_status()

    assert "deribit_telemetry" in status
    assert status["deribit_telemetry"]["currency"] == "BTC"
    assert "margin_utilization_pct" in status["deribit_telemetry"]
    assert "portfolio_delta" in status["deribit_telemetry"]
    assert "swarm" in status


def test_api_equity_history_endpoint():
    app = create_app()
    client = TestClient(app)

    res = client.get("/api/v1/bot/equity-history?timeframe=1d")
    assert res.status_code == 200
    data = res.json()
    assert "timeframe" in data
    assert "data" in data
    assert data["timeframe"] == "1d"
