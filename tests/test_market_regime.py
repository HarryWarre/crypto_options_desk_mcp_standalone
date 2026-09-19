"""Unit tests for MarketRegimeAgent and market regime classification."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

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


def _make_dummy_contract(
    asset: str = "BTC",
    option_type: str = "Call",
    strike: float = 60000.0,
    spot_price: float = 60000.0,
    mark_iv: float = 0.55,
    days_to_expiry: int = 14,
) -> OptionContract:
    now = datetime.now(UTC)
    expiry = now + timedelta(days=days_to_expiry)
    type_code = "C" if option_type.lower().startswith("c") else "P"
    expiry_code = expiry.strftime("%d%b%y").upper()
    symbol = f"{asset}-{expiry_code}-{int(strike)}-{type_code}"
    return OptionContract(
        asset=asset,
        symbol=symbol,
        option_type=type_code,
        strike=strike,
        expiry_at=expiry,
        expiry_code=expiry_code,
        spot_price=spot_price,
        mark_price=strike * 0.05,
        mark_iv=mark_iv,
        bid_price=strike * 0.05,
        ask_price=strike * 0.052,
        bid_iv=mark_iv,
        ask_iv=mark_iv + 0.01,
        delta=0.5 if type_code == "C" else -0.5,
        gamma=0.0001,
        theta=-20.0,
        vega=15.0,
        volume_24h=100.0,
        open_interest=500.0,
        quote_currency="USD",
        settle_currency=asset,
        quote_timestamp=now,
    )


def _make_hv_context(asset: str = "BTC", rv: float = 0.50) -> HistoricalVolatilityContext:
    now = datetime.now(UTC)
    return HistoricalVolatilityContext(
        asset=asset,
        period_days=30,
        available=True,
        status="available",
        historical_volatility=rv,
        as_of=now,
        requested_at=now,
        retrieved_at=now,
    )


def test_quantitative_metrics_and_vol_classification():
    agent = MarketRegimeAgent(api_key=None)

    # High Vol scenario: IV = 65% (0.65), RV = 50% (0.50) -> Spread = +15 vol pts
    contracts = [
        _make_dummy_contract(strike=60000, spot_price=60000, mark_iv=0.65, days_to_expiry=7),
        _make_dummy_contract(strike=62000, spot_price=60000, mark_iv=0.63, days_to_expiry=7),
        _make_dummy_contract(option_type="Put", strike=58000, spot_price=60000, mark_iv=0.68, days_to_expiry=7),
        # Far expiry: IV = 60%
        _make_dummy_contract(strike=60000, spot_price=60000, mark_iv=0.60, days_to_expiry=30),
    ]
    hv = _make_hv_context(rv=0.50)

    report = agent.analyze(
        asset="BTC",
        contracts=contracts,
        historical_volatility=hv,
        sma_20=60000.0,
        spot_price=60000.0,
    )

    assert isinstance(report, MarketRegimeReport)
    assert report.vol_regime == VolRegime.HIGH_VOL
    assert report.trend_regime == TrendRegime.NEUTRAL_CONSOLIDATING
    assert report.term_structure_regime == TermStructureRegime.BACKWARDATION  # far 60 - near ~65 = -5
    assert report.skew_regime == SkewRegime.PUT_SKEW  # put 68 - call 63 = +5
    assert "iron_condor" in report.recommended_strategies
    assert "iron_butterfly" in report.recommended_strategies
    assert "long_straddle" in report.avoid_strategies
    assert report.is_fallback is True  # No api key provided
    assert "BTC Phân Tích Định Lượng" in report.thesis


def test_iv_discount_regime():
    agent = MarketRegimeAgent(api_key=None)

    # IV Discount: IV = 45% (0.45), RV = 60% (0.60) -> Spread = -15 vol pts
    contracts = [
        _make_dummy_contract(strike=60000, spot_price=60000, mark_iv=0.45, days_to_expiry=14),
    ]
    hv = _make_hv_context(rv=0.60)

    report = agent.analyze(
        asset="BTC",
        contracts=contracts,
        historical_volatility=hv,
        sma_20=60000.0,
        spot_price=60000.0,
    )

    assert report.vol_regime == VolRegime.IV_DISCOUNT
    assert "long_straddle" in report.recommended_strategies
    assert "long_strangle" in report.recommended_strategies
    assert "iron_condor" in report.avoid_strategies


def test_calendar_spread_favorable_regime():
    agent = MarketRegimeAgent(api_key=None)

    # Contango + Low/Normal Vol + Consolidation
    # Near IV = 48%, Far IV = 53% -> slope +5 pts (Contango)
    contracts = [
        _make_dummy_contract(strike=60000, spot_price=60000, mark_iv=0.48, days_to_expiry=7),
        _make_dummy_contract(strike=60000, spot_price=60000, mark_iv=0.53, days_to_expiry=30),
    ]
    hv = _make_hv_context(rv=0.47)

    report = agent.analyze(
        asset="BTC",
        contracts=contracts,
        historical_volatility=hv,
        sma_20=60200.0,  # spot 60000 is within 0.33% of SMA20
        spot_price=60000.0,
    )

    assert report.term_structure_regime == TermStructureRegime.CONTANGO
    assert report.trend_regime == TrendRegime.NEUTRAL_CONSOLIDATING
    assert "calendar_spread" in report.recommended_strategies


def test_trend_regime_classification():
    agent = MarketRegimeAgent(api_key=None)
    contracts = [_make_dummy_contract(spot_price=65000)]
    hv = _make_hv_context(rv=0.50)

    # Spot 65000 vs SMA 60000 (+8.33% -> Strong Bull)
    report_bull = agent.analyze(
        asset="BTC",
        contracts=contracts,
        historical_volatility=hv,
        sma_20=60000.0,
        spot_price=65000.0,
    )
    assert report_bull.trend_regime == TrendRegime.STRONG_BULL

    # Spot 55000 vs SMA 60000 (-8.33% -> Strong Bear)
    report_bear = agent.analyze(
        asset="BTC",
        contracts=contracts,
        historical_volatility=hv,
        sma_20=60000.0,
        spot_price=55000.0,
    )
    assert report_bear.trend_regime == TrendRegime.STRONG_BEAR


def test_llm_synthesis_success_and_fallback():
    # 1. Test LLM success via mock
    agent = MarketRegimeAgent(api_key="fake-key-for-testing")
    contracts = [_make_dummy_contract()]
    hv = _make_hv_context()

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "BTC options show strong premium selling edge with elevated IV."}]
                }
            }
        ]
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        report = agent.analyze(asset="BTC", contracts=contracts, historical_volatility=hv)
        assert report.is_fallback is False
        assert "BTC options show strong premium selling edge" in report.thesis

    # 2. Test LLM failure gracefully falls back to deterministic thesis
    with patch("httpx.Client.post", side_effect=Exception("Connection timed out")):
        report_fallback = agent.analyze(asset="BTC", contracts=contracts, historical_volatility=hv)
        assert report_fallback.is_fallback is True
        assert "BTC Phân Tích Định Lượng" in report_fallback.thesis
