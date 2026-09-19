"""Market Regime Research Agent for Options Trading Swarm.

Provides hybrid quantitative metric calculation and LLM reasoning synthesis
with a robust 100% deterministic fallback mechanism when offline or unconfigured.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Sequence

import httpx

from bybit_api.options_market_data import OptionContract
from options_lib.historical_volatility import HistoricalVolatilityContext

logger = logging.getLogger(__name__)


class VolRegime(str, Enum):
    """Volatility environment classification."""

    HIGH_VOL = "HIGH_VOL"  # IV significantly above RV; premium selling edge
    LOW_VOL = "LOW_VOL"  # Low absolute IV & low RV; quiet market
    IV_DISCOUNT = "IV_DISCOUNT"  # RV > IV; options underpricing movement; long vol edge
    NORMAL = "NORMAL"  # Moderate volatility in balance


class TrendRegime(str, Enum):
    """Underlying asset price trend classification."""

    STRONG_BULL = "STRONG_BULL"  # Spot > SMA20 by > 3.0%
    BULLISH = "BULLISH"  # Spot > SMA20 by 0.5% - 3.0%
    NEUTRAL_CONSOLIDATING = "NEUTRAL_CONSOLIDATING"  # |Spot - SMA20| <= 0.5%
    BEARISH = "BEARISH"  # Spot < SMA20 by 0.5% - 3.0%
    STRONG_BEAR = "STRONG_BEAR"  # Spot < SMA20 by > 3.0%


class TermStructureRegime(str, Enum):
    """Volatility term structure shape."""

    CONTANGO = "CONTANGO"  # Near IV < Far IV (normal upward slope)
    BACKWARDATION = "BACKWARDATION"  # Near IV > Far IV (short-term panic / catalyst)
    FLAT = "FLAT"  # Near IV ≈ Far IV


class SkewRegime(str, Enum):
    """Option volatility smile skew direction."""

    PUT_SKEW = "PUT_SKEW"  # OTM Put IV > OTM Call IV (downside protection demand)
    CALL_SKEW = "CALL_SKEW"  # OTM Call IV > OTM Put IV (upside speculation / FOMO)
    BALANCED = "BALANCED"  # Symmetrical smile


@dataclass(frozen=True)
class QuantitativeMetrics:
    """Raw computed metrics for market regime analysis."""

    spot_price: float
    sma_20: float
    spot_sma_dist_pct: float
    atm_iv: float
    rv_30d: float
    iv_rv_spread: float  # In vol percentage points (e.g. +6.5)
    near_iv: float
    far_iv: float
    term_structure_slope: float  # far_iv - near_iv (in vol pts)
    otm_put_iv: float
    otm_call_iv: float
    skew_spread: float  # otm_put_iv - otm_call_iv (in vol pts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketRegimeReport:
    """Consolidated market analysis report emitted by Research Agent."""

    asset: str
    timestamp: str
    vol_regime: VolRegime
    trend_regime: TrendRegime
    term_structure_regime: TermStructureRegime
    skew_regime: SkewRegime
    metrics: QuantitativeMetrics
    recommended_strategies: tuple[str, ...]
    avoid_strategies: tuple[str, ...]
    thesis: str
    is_fallback: bool
    summary: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["vol_regime"] = self.vol_regime.value
        data["trend_regime"] = self.trend_regime.value
        data["term_structure_regime"] = self.term_structure_regime.value
        data["skew_regime"] = self.skew_regime.value
        return data


class MarketRegimeAgent:
    """Autonomous Research Agent providing market regime analysis."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        timeout_sec: float = 6.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        self.timeout_sec = timeout_sec

    def analyze(
        self,
        asset: str,
        contracts: Sequence[OptionContract],
        historical_volatility: HistoricalVolatilityContext | None,
        sma_20: float | None = None,
        spot_price: float | None = None,
    ) -> MarketRegimeReport:
        """Analyze option universe and compute quantitative regime metrics."""
        asset_norm = asset.upper()

        # Compute quantitative metrics
        metrics = self._calculate_metrics(
            asset=asset_norm,
            contracts=contracts,
            hv_context=historical_volatility,
            sma_20=sma_20,
            spot_override=spot_price,
        )

        # Classify enums
        vol_regime = self._classify_vol_regime(metrics)
        trend_regime = self._classify_trend_regime(metrics)
        ts_regime = self._classify_term_structure(metrics)
        skew_regime = self._classify_skew(metrics)

        # Select strategies
        recommended, avoid = self._select_strategies(
            vol=vol_regime,
            trend=trend_regime,
            ts=ts_regime,
            skew=skew_regime,
            metrics=metrics,
        )

        # Generate summary
        summary = (
            f"{asset_norm} Regime: {vol_regime.value} | {trend_regime.value} | "
            f"TS: {ts_regime.value} | IV-RV Spread: {metrics.iv_rv_spread:+.1f} vol pts | "
            f"Spot vs SMA20: {metrics.spot_sma_dist_pct:+.2f}%"
        )

        # Generate thesis (LLM with fallback)
        thesis, is_fallback = self._synthesize_thesis(
            asset=asset_norm,
            vol=vol_regime,
            trend=trend_regime,
            ts=ts_regime,
            skew=skew_regime,
            metrics=metrics,
            recommended=recommended,
        )

        return MarketRegimeReport(
            asset=asset_norm,
            timestamp=datetime.now(UTC).isoformat(),
            vol_regime=vol_regime,
            trend_regime=trend_regime,
            term_structure_regime=ts_regime,
            skew_regime=skew_regime,
            metrics=metrics,
            recommended_strategies=recommended,
            avoid_strategies=avoid,
            thesis=thesis,
            is_fallback=is_fallback,
            summary=summary,
        )

    def _calculate_metrics(
        self,
        asset: str,
        contracts: Sequence[OptionContract],
        hv_context: HistoricalVolatilityContext | None,
        sma_20: float | None,
        spot_override: float | None,
    ) -> QuantitativeMetrics:
        """Extract prices, IVs, term structure, and skew from contracts."""
        if not contracts:
            spot = spot_override or 50000.0
            sma = sma_20 or spot
            return QuantitativeMetrics(
                spot_price=spot,
                sma_20=sma,
                spot_sma_dist_pct=0.0,
                atm_iv=50.0,
                rv_30d=50.0,
                iv_rv_spread=0.0,
                near_iv=50.0,
                far_iv=50.0,
                term_structure_slope=0.0,
                otm_put_iv=50.0,
                otm_call_iv=50.0,
                skew_spread=0.0,
            )

        # Get spot price
        spot = spot_override or contracts[0].spot_price
        if spot <= 0:
            spot = 50000.0
        sma = sma_20 if sma_20 and sma_20 > 0 else spot
        spot_sma_dist = ((spot - sma) / sma) * 100.0

        # RV
        rv = 50.0
        if hv_context and hv_context.available and hv_context.historical_volatility:
            raw_rv = hv_context.historical_volatility
            rv = raw_rv * 100.0 if raw_rv <= 2.0 else raw_rv

        # Group contracts by expiry (using 12h tolerance to absorb microsecond/time differences)
        valid_contracts = [c for c in contracts if c.mark_iv and c.mark_iv > 0]
        if not valid_contracts:
            valid_contracts = list(contracts)

        expiries = sorted(list({c.expiry_at for c in valid_contracts}))
        min_expiry = expiries[0] if expiries else None
        max_expiry = expiries[-1] if len(expiries) > 1 else min_expiry

        def get_iv(c: OptionContract) -> float:
            raw = c.mark_iv or 0.0
            return raw * 100.0 if raw <= 2.0 else raw

        # Near IV & ATM IV
        near_contracts = (
            [c for c in valid_contracts if abs((c.expiry_at - min_expiry).total_seconds()) <= 43200]
            if min_expiry
            else []
        )
        if near_contracts:
            # Find closest to spot
            atm_contract = min(near_contracts, key=lambda c: abs(c.strike - spot))
            atm_iv = get_iv(atm_contract)
            near_iv = sum(get_iv(c) for c in near_contracts) / len(near_contracts)
        else:
            atm_iv = rv
            near_iv = rv

        # Far IV
        far_contracts = (
            [c for c in valid_contracts if abs((c.expiry_at - max_expiry).total_seconds()) <= 43200]
            if max_expiry
            else near_contracts
        )
        if far_contracts:
            far_iv = sum(get_iv(c) for c in far_contracts) / len(far_contracts)
        else:
            far_iv = near_iv

        ts_slope = far_iv - near_iv

        # Skew: 25-delta Put vs 25-delta Call (or strike 90% vs 110%)
        puts_otm = [c for c in near_contracts if c.option_type.lower().startswith("p") and c.strike < spot]
        calls_otm = [c for c in near_contracts if c.option_type.lower().startswith("c") and c.strike > spot]

        put_iv = get_iv(puts_otm[0]) if puts_otm else atm_iv
        call_iv = get_iv(calls_otm[0]) if calls_otm else atm_iv
        skew_spread = put_iv - call_iv

        iv_rv_spread = atm_iv - rv

        return QuantitativeMetrics(
            spot_price=spot,
            sma_20=sma,
            spot_sma_dist_pct=spot_sma_dist,
            atm_iv=atm_iv,
            rv_30d=rv,
            iv_rv_spread=iv_rv_spread,
            near_iv=near_iv,
            far_iv=far_iv,
            term_structure_slope=ts_slope,
            otm_put_iv=put_iv,
            otm_call_iv=call_iv,
            skew_spread=skew_spread,
        )

    def _classify_vol_regime(self, m: QuantitativeMetrics) -> VolRegime:
        """Classify volatility regime."""
        # IV Discount: Realized Vol is higher than Implied Vol (Options underpriced)
        if m.rv_30d >= m.atm_iv * 1.02 and m.iv_rv_spread <= -2.0:
            return VolRegime.IV_DISCOUNT

        # High Vol: IV significantly higher than RV
        if m.iv_rv_spread >= 4.0:
            return VolRegime.HIGH_VOL

        # Low Vol: Both IV and RV are subdued
        if m.atm_iv < 45.0 and m.rv_30d < 45.0:
            return VolRegime.LOW_VOL

        return VolRegime.NORMAL

    def _classify_trend_regime(self, m: QuantitativeMetrics) -> TrendRegime:
        """Classify trend direction based on spot distance to SMA20."""
        dist = m.spot_sma_dist_pct
        if dist > 3.0:
            return TrendRegime.STRONG_BULL
        if dist > 0.6:
            return TrendRegime.BULLISH
        if dist < -3.0:
            return TrendRegime.STRONG_BEAR
        if dist < -0.6:
            return TrendRegime.BEARISH
        return TrendRegime.NEUTRAL_CONSOLIDATING

    def _classify_term_structure(self, m: QuantitativeMetrics) -> TermStructureRegime:
        """Classify term structure slope."""
        if m.term_structure_slope >= 2.0:
            return TermStructureRegime.CONTANGO
        if m.term_structure_slope <= -2.0:
            return TermStructureRegime.BACKWARDATION
        return TermStructureRegime.FLAT

    def _classify_skew(self, m: QuantitativeMetrics) -> SkewRegime:
        """Classify skew."""
        if m.skew_spread >= 2.5:
            return SkewRegime.PUT_SKEW
        if m.skew_spread <= -2.5:
            return SkewRegime.CALL_SKEW
        return SkewRegime.BALANCED

    def _select_strategies(
        self,
        vol: VolRegime,
        trend: TrendRegime,
        ts: TermStructureRegime,
        skew: SkewRegime,
        metrics: QuantitativeMetrics,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Map market regime to optimal options trading strategies."""
        recommended: list[str] = []
        avoid: list[str] = []

        # 1. High Volatility Regime -> Premium Selling
        if vol == VolRegime.HIGH_VOL:
            if trend == TrendRegime.NEUTRAL_CONSOLIDATING:
                recommended.extend(["iron_condor", "iron_butterfly"])
            elif trend in {TrendRegime.BULLISH, TrendRegime.STRONG_BULL}:
                recommended.extend(["bull_put_vertical", "wheel_csp"])
            elif trend in {TrendRegime.BEARISH, TrendRegime.STRONG_BEAR}:
                recommended.extend(["bear_call_vertical"])
            avoid.extend(["long_straddle", "long_strangle", "long_call", "long_put"])

        # 2. IV Discount Regime -> Long Volatility
        elif vol == VolRegime.IV_DISCOUNT:
            recommended.extend(["long_straddle", "long_strangle"])
            avoid.extend(["iron_condor", "iron_butterfly", "calendar_spread"])

        # 3. Low Vol / Normal Vol with Consolidation -> Calendar Spreads & Wheel
        elif vol in {VolRegime.LOW_VOL, VolRegime.NORMAL}:
            if ts == TermStructureRegime.CONTANGO and abs(metrics.spot_sma_dist_pct) <= 2.0:
                recommended.append("calendar_spread")
            if trend in {TrendRegime.NEUTRAL_CONSOLIDATING, TrendRegime.BULLISH}:
                recommended.append("wheel")
            if trend in {TrendRegime.BULLISH, TrendRegime.STRONG_BULL}:
                recommended.append("bull_call_vertical")

        # Deduplicate while preserving order
        rec_tuple = tuple(dict.fromkeys(recommended))
        avd_tuple = tuple(dict.fromkeys(avoid))

        if not rec_tuple:
            rec_tuple = ("wheel", "vertical_spread")

        return rec_tuple, avd_tuple

    def _synthesize_thesis(
        self,
        asset: str,
        vol: VolRegime,
        trend: TrendRegime,
        ts: TermStructureRegime,
        skew: SkewRegime,
        metrics: QuantitativeMetrics,
        recommended: tuple[str, ...],
    ) -> tuple[str, bool]:
        """Synthesize narrative market thesis using Gemini LLM, with fallback."""
        if not self.api_key:
            return self._deterministic_fallback_thesis(asset, vol, trend, ts, skew, metrics, recommended), True

        prompt = (
            f"You are the Head Research Analyst of an institutional crypto options trading desk. "
            f"Analyze the market regime for {asset} based on the following real-time parameters:\n"
            f"- Spot Price: ${metrics.spot_price:,.2f} (Distance to SMA20: {metrics.spot_sma_dist_pct:+.2f}%)\n"
            f"- ATM IV: {metrics.atm_iv:.1f}%, 30d RV: {metrics.rv_30d:.1f}%\n"
            f"- IV - RV Spread: {metrics.iv_rv_spread:+.1f} vol pts\n"
            f"- Volatility Regime: {vol.value}\n"
            f"- Trend Regime: {trend.value}\n"
            f"- Term Structure: {ts.value} (Slope: {metrics.term_structure_slope:+.1f} pts)\n"
            f"- Skew: {skew.value} (Put/Call Spread: {metrics.skew_spread:+.1f} pts)\n"
            f"- Recommended Strategies: {', '.join(recommended)}\n\n"
            f"Write a concise 2-3 sentence executive thesis explaining why this regime favors these specific "
            f"options structures and what the primary market risk is."
        )

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 200,
                },
            }
            with httpx.Client(timeout=self.timeout_sec) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return text, False
        except Exception as e:
            logger.warning("LLM synthesis failed, using quantitative fallback: %s", e)
            return self._deterministic_fallback_thesis(asset, vol, trend, ts, skew, metrics, recommended), True

    def _deterministic_fallback_thesis(
        self,
        asset: str,
        vol: VolRegime,
        trend: TrendRegime,
        ts: TermStructureRegime,
        skew: SkewRegime,
        metrics: QuantitativeMetrics,
        recommended: tuple[str, ...],
    ) -> str:
        """Deterministic, rule-grounded narrative thesis when LLM is unavailable."""
        vol_desc = {
            VolRegime.HIGH_VOL: f"IV ({metrics.atm_iv:.1f}%) đang cao hơn đáng kể so với RV ({metrics.rv_30d:.1f}%) với spread {metrics.iv_rv_spread:+.1f} vol pts, tạo lợi thế thu premium hấp dẫn.",
            VolRegime.IV_DISCOUNT: f"RV ({metrics.rv_30d:.1f}%) đang vượt trội so với IV ({metrics.atm_iv:.1f}%), cho thấy thị trường đang bán rẻ biến động thực tế, ưu tiên mua vol.",
            VolRegime.LOW_VOL: f"Biến động ngầm và biến động thực tế đều ở mức thấp ({metrics.atm_iv:.1f}%), thị trường trong pha tích lũy nén biên độ.",
            VolRegime.NORMAL: f"Biến động duy trì mức cân bằng ổn định quanh {metrics.atm_iv:.1f}%.",
        }.get(vol, "")

        trend_desc = {
            TrendRegime.STRONG_BULL: f"Xu hướng tăng mạnh (Spot cách SMA20 {metrics.spot_sma_dist_pct:+.2f}%).",
            TrendRegime.BULLISH: f"Xu hướng thiên tăng vừa phải trên SMA20 ({metrics.spot_sma_dist_pct:+.2f}%).",
            TrendRegime.NEUTRAL_CONSOLIDATING: f"Giá tích lũy đi ngang chặt chẽ quanh SMA20 ({metrics.spot_sma_dist_pct:+.2f}%).",
            TrendRegime.BEARISH: f"Xu hướng thiên giảm dưới SMA20 ({metrics.spot_sma_dist_pct:+.2f}%).",
            TrendRegime.STRONG_BEAR: f"Xu hướng bán tháo giảm mạnh ({metrics.spot_sma_dist_pct:+.2f}% dưới SMA20).",
        }.get(trend, "")

        strats = ", ".join(recommended)
        return (
            f"[{asset} Phân Tích Định Lượng] {vol_desc} {trend_desc} "
            f"Cấu trúc kỳ hạn {ts.value} và độ lệch Skew {skew.value}. "
            f"Hệ thống khuyến nghị kích hoạt các chiến lược: {strats}."
        )
