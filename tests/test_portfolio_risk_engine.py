"""Unit tests for PortfolioRiskEngine and dynamic position sizing."""

from datetime import UTC, datetime

import pytest
from options_lib.risk.portfolio_risk_engine import (
    AssetLotSpec,
    PortfolioRiskEngine,
    RiskAssessmentResult,
    RiskLimitsConfig,
)
from options_lib.swarm.candidate_signal import CandidateLeg, CandidateSignal


def _make_dummy_signal(
    asset: str = "BTC",
    strategy: str = "iron_condor",
    max_loss_per_unit: float = 500.0,
    net_premium_per_unit: float = 250.0,
    action_type: str = "CREDIT",
    leg_delta: float = 0.0,
    spot: float = 60000.0,
) -> CandidateSignal:
    leg = CandidateLeg(
        symbol=f"{asset}-TEST-60000-C",
        strike=60000.0,
        option_type="Call",
        side="SELL",
        ratio=1.0,
        mark_price=net_premium_per_unit,
        iv=0.50,
        delta=leg_delta,
        dte=14.0,
    )
    return CandidateSignal(
        signal_id=f"sig_{asset.lower()}_test",
        strategy=strategy,
        trader_name="TestTrader",
        asset=asset,
        expiry_date="2026-10-01",
        dte=14.0,
        direction="NEUTRAL",
        action_type=action_type,
        net_premium_per_unit=net_premium_per_unit,
        max_loss_per_unit=max_loss_per_unit,
        max_profit_per_unit=net_premium_per_unit,
        legs=(leg,),
        model_edge=10.0,
        underlying_spot=spot,
        raw_candidate={},
        created_at=datetime.now(UTC).isoformat(),
    )


def test_dynamic_sizing_btc():
    # Equity = $10,000, 2% risk budget = $200
    # Max loss per unit = $500 -> Raw qty = 200 / 500 = 0.4 BTC
    engine = PortfolioRiskEngine()
    signal = _make_dummy_signal(asset="BTC", max_loss_per_unit=500.0)

    res = engine.evaluate_candidate(
        candidate=signal,
        current_equity=10000.0,
        current_margin_used=1000.0,
    )

    assert isinstance(res, RiskAssessmentResult)
    assert res.approved is True
    assert res.allocated_qty == 0.4
    assert res.allocated_max_loss == 200.0  # 0.4 * 500
    assert len(res.rejection_reasons) == 0


def test_dynamic_sizing_eth():
    # Equity = $20,000, 2% risk budget = $400
    # Max loss per unit = $150 -> Raw qty = 400 / 150 = 2.66 -> Quantized to 2.0 ETH
    engine = PortfolioRiskEngine()
    signal = _make_dummy_signal(asset="ETH", max_loss_per_unit=150.0, spot=3000.0)

    res = engine.evaluate_candidate(
        candidate=signal,
        current_equity=20000.0,
        current_margin_used=2000.0,
    )

    assert res.approved is True
    assert res.allocated_qty == 2.0
    assert res.allocated_max_loss == 300.0  # 2.0 * 150


def test_margin_budget_exceeded():
    # Equity = $10,000, 60% max margin = $6,000
    # Current margin used = $5,950 -> only $50 available
    # Candidate requires $500 margin per unit, min 0.1 BTC ($50 margin)
    engine = PortfolioRiskEngine(config=RiskLimitsConfig(max_portfolio_margin_utilization=0.60))
    signal = _make_dummy_signal(asset="BTC", max_loss_per_unit=1000.0)

    # 0.1 * 1000 = $100 min margin needed, but only $50 available
    res = engine.evaluate_candidate(
        candidate=signal,
        current_equity=10000.0,
        current_margin_used=5960.0,
    )

    assert res.approved is False
    assert res.allocated_qty == 0.0
    assert any("margin_utilization_exceeded" in r for r in res.rejection_reasons)


def test_small_account_under_min_trade_size():
    # Equity = $300, 2% risk budget = $6.0
    # Max loss per unit = $500 -> Min size 0.1 BTC requires $50 risk (> 8x budget)
    engine = PortfolioRiskEngine()
    signal = _make_dummy_signal(asset="BTC", max_loss_per_unit=500.0)

    res = engine.evaluate_candidate(
        candidate=signal,
        current_equity=300.0,
        current_margin_used=0.0,
    )

    assert res.approved is False
    assert res.allocated_qty == 0.0
    assert any("risk_budget_below_minimum_size" in r for r in res.rejection_reasons)


def test_delta_exposure_limit():
    # Equity = $10,000, spot = 60,000
    # Max delta ratio = 0.20 -> Max portfolio delta = (10000 / 60000) * 0.20 = 0.0333
    # Candidate has leg_delta = 0.90 -> at 0.4 BTC = 0.36 delta (breaches 0.033)
    engine = PortfolioRiskEngine(config=RiskLimitsConfig(max_net_delta_equity_ratio=0.20))
    signal = _make_dummy_signal(asset="BTC", max_loss_per_unit=500.0, leg_delta=0.90, spot=60000.0)

    res = engine.evaluate_candidate(
        candidate=signal,
        current_equity=10000.0,
        current_margin_used=0.0,
    )

    assert res.approved is False
    assert any("portfolio_delta_limit_exceeded" in r for r in res.rejection_reasons)
