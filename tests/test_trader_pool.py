"""Unit tests for TraderPool and specialized Trader Agents."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from bybit_api.options_market_data import OptionContract
from options_lib.historical_volatility import HistoricalVolatilityContext
from options_lib.research.market_regime import (
    MarketRegimeAgent,
    MarketRegimeReport,
    QuantitativeMetrics,
    SkewRegime,
    TermStructureRegime,
    TrendRegime,
    VolRegime,
)
from options_lib.swarm.candidate_signal import CandidateLeg, CandidateSignal
from options_lib.swarm.trader_agents import (
    CalendarSpreadTrader,
    IronButterflyTrader,
    IronCondorTrader,
    LongVolTrader,
    VerticalSpreadTrader,
    WheelTrader,
)
from options_lib.swarm.trader_pool import TraderPool


def _build_test_option_chain(
    asset: str = "BTC",
    spot_price: float = 60000.0,
    near_dte: int = 10,
    far_dte: int = 30,
) -> list[OptionContract]:
    """Generate rich option chain with calls and puts across two expiries."""
    now = datetime.now(UTC)
    contracts: list[OptionContract] = []

    for dte, base_iv in [(near_dte, 0.60), (far_dte, 0.65)]:
        exp = now + timedelta(days=dte)
        exp_code = exp.strftime("%d%b%y").upper()

        # Strikes from 40,000 to 80,000 with 2,000 increments
        for strike in range(40000, 82000, 2000):
            # Realistic call delta: 0.50 at ATM, decreasing smoothly as strike increases
            diff = (strike - spot_price) / 4000.0
            # Sigmoid-like approximation for clean testing
            c_delta = max(0.01, min(0.99, 1.0 / (1.0 + math.exp(diff))))
            c_price = max(50.0, spot_price * c_delta * 0.1)
            contracts.append(
                OptionContract(
                    asset=asset,
                    symbol=f"{asset}-{exp_code}-{strike}-C",
                    option_type="C",
                    strike=float(strike),
                    expiry_at=exp,
                    expiry_code=exp_code,
                    spot_price=spot_price,
                    mark_price=c_price,
                    mark_iv=base_iv,
                    bid_price=c_price * 0.98,
                    ask_price=c_price * 1.02,
                    bid_iv=base_iv - 0.01,
                    ask_iv=base_iv + 0.01,
                    delta=c_delta,
                    gamma=0.0001,
                    theta=-25.0,
                    vega=20.0,
                    volume_24h=500.0,
                    open_interest=2000.0,
                    quote_currency="USD",
                    settle_currency=asset,
                    quote_timestamp=now,
                )
            )

            # Realistic put delta: -0.50 at ATM, negative
            p_delta = c_delta - 1.0
            p_price = max(50.0, spot_price * abs(p_delta) * 0.1)
            contracts.append(
                OptionContract(
                    asset=asset,
                    symbol=f"{asset}-{exp_code}-{strike}-P",
                    option_type="P",
                    strike=float(strike),
                    expiry_at=exp,
                    expiry_code=exp_code,
                    spot_price=spot_price,
                    mark_price=p_price,
                    mark_iv=base_iv + 0.02,
                    bid_price=p_price * 0.98,
                    ask_price=p_price * 1.02,
                    bid_iv=base_iv + 0.01,
                    ask_iv=base_iv + 0.03,
                    delta=p_delta,
                    gamma=0.0001,
                    theta=-25.0,
                    vega=20.0,
                    volume_24h=500.0,
                    open_interest=2000.0,
                    quote_currency="USD",
                    settle_currency=asset,
                    quote_timestamp=now,
                )
            )

    return contracts


def _make_dummy_report(
    vol_regime: VolRegime,
    recommended: tuple[str, ...],
    avoid: tuple[str, ...] = (),
    spot: float = 60000.0,
) -> MarketRegimeReport:
    metrics = QuantitativeMetrics(
        spot_price=spot,
        sma_20=spot,
        spot_sma_dist_pct=0.0,
        atm_iv=60.0,
        rv_30d=50.0,
        iv_rv_spread=10.0 if vol_regime == VolRegime.HIGH_VOL else -10.0,
        near_iv=60.0,
        far_iv=65.0,
        term_structure_slope=5.0,
        otm_put_iv=62.0,
        otm_call_iv=60.0,
        skew_spread=2.0,
    )
    return MarketRegimeReport(
        asset="BTC",
        timestamp=datetime.now(UTC).isoformat(),
        vol_regime=vol_regime,
        trend_regime=TrendRegime.NEUTRAL_CONSOLIDATING,
        term_structure_regime=TermStructureRegime.CONTANGO,
        skew_regime=SkewRegime.BALANCED,
        metrics=metrics,
        recommended_strategies=recommended,
        avoid_strategies=avoid,
        thesis="Test thesis",
        is_fallback=True,
        summary="Test summary",
    )


def test_candidate_signal_serialization():
    leg = CandidateLeg(
        symbol="BTC-28SEP26-60000-C",
        strike=60000.0,
        option_type="Call",
        side="BUY",
        ratio=1.0,
        mark_price=1200.0,
        iv=0.55,
        delta=0.50,
        dte=9.0,
    )
    sig = CandidateSignal(
        signal_id="sig_test_1",
        strategy="long_vol",
        trader_name="LongVolTrader",
        asset="BTC",
        expiry_date="2026-09-28",
        dte=9.0,
        direction="NEUTRAL",
        action_type="DEBIT",
        net_premium_per_unit=2400.0,
        max_loss_per_unit=2400.0,
        max_profit_per_unit=4800.0,
        legs=(leg,),
        model_edge=5.0,
        underlying_spot=60000.0,
        raw_candidate={"raw": 1},
        created_at=datetime.now(UTC).isoformat(),
    )

    data = sig.to_dict()
    assert data["signal_id"] == "sig_test_1"
    assert data["risk_reward_ratio"] == 2.0
    assert len(data["legs"]) == 1
    assert data["legs"][0]["strike"] == 60000.0


def test_trader_pool_evaluates_high_vol_regime():
    contracts = _build_test_option_chain(spot_price=60000.0, near_dte=10, far_dte=30)
    report = _make_dummy_report(
        vol_regime=VolRegime.HIGH_VOL,
        recommended=("iron_condor", "iron_butterfly"),
        avoid=("long_straddle", "long_strangle", "long_vol"),
    )

    pool = TraderPool()
    candidates = pool.generate_candidates(report, contracts, spot_price=60000.0)

    # Should generate candidates
    assert len(candidates) > 0

    # Long Vol must be skipped because it is in avoid_strategies
    strategies = [c.strategy for c in candidates]
    assert "long_vol" not in strategies

    # The top candidate should be from recommended strategies
    top_cand = candidates[0]
    assert top_cand.strategy in ("iron_condor", "iron_butterfly")
    assert top_cand.action_type == "CREDIT"
    assert len(top_cand.legs) >= 2


def test_trader_pool_evaluates_iv_discount_regime():
    contracts = _build_test_option_chain(spot_price=60000.0, near_dte=14, far_dte=30)
    report = _make_dummy_report(
        vol_regime=VolRegime.IV_DISCOUNT,
        recommended=("long_vol",),
        avoid=("iron_condor", "iron_butterfly"),
    )

    pool = TraderPool()
    candidates = pool.generate_candidates(report, contracts, spot_price=60000.0)

    strategies = [c.strategy for c in candidates]
    # Iron Condor and Iron Butterfly should be skipped
    assert "iron_condor" not in strategies
    assert "iron_butterfly" not in strategies


def test_individual_trader_agents_evaluate():
    contracts = _build_test_option_chain(spot_price=60000.0, near_dte=10, far_dte=30)
    report = _make_dummy_report(
        vol_regime=VolRegime.HIGH_VOL,
        recommended=("iron_condor", "wheel", "vertical_spread"),
    )

    # Test Wheel Trader
    wheel_trader = WheelTrader()
    wheel_cand = wheel_trader.evaluate(report, contracts, spot_price=60000.0)
    if wheel_cand:
        assert wheel_cand.strategy == "wheel"
        assert wheel_cand.action_type == "CREDIT"
        assert len(wheel_cand.legs) == 1

    # Test Vertical Spread Trader
    vert_trader = VerticalSpreadTrader()
    vert_cand = vert_trader.evaluate(report, contracts, spot_price=60000.0)
    if vert_cand:
        assert vert_cand.strategy == "vertical_spread"
        assert vert_cand.action_type == "CREDIT"
        assert len(vert_cand.legs) == 2
