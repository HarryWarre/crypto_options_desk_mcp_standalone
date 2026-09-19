"""Specialized Trader Agents for Multi-Agent Options Swarm."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Sequence

from bybit_api.options_market_data import OptionContract
from options_lib.research.market_regime import MarketRegimeReport, TrendRegime
from options_lib.strategy.calendar_spread_bot import CalendarSpreadBot, CalendarSpreadConfig
from options_lib.strategy.iron_butterfly_bot import IronButterflyBot, IronButterflyConfig
from options_lib.strategy.iron_condor_bot import IronCondorBot, IronCondorConfig
from options_lib.strategy.long_vol_bot import LongVolBot, LongVolConfig
from options_lib.strategy.vertical_spread_bot import VerticalSpreadBot, VerticalSpreadConfig
from options_lib.strategy.wheel_bot import WheelBot, WheelConfig
from options_lib.swarm.candidate_signal import CandidateLeg, CandidateSignal

logger = logging.getLogger(__name__)


def contracts_to_dicts(contracts: Sequence[OptionContract]) -> list[dict[str, Any]]:
    """Convert Normalized OptionContracts to dictionary representation expected by bot engines."""
    now = datetime.now(UTC)
    result: list[dict[str, Any]] = []
    for c in contracts:
        opt_type = "Call" if c.option_type.upper().startswith("C") else "Put"
        dte = max(0.1, (c.expiry_at - now).total_seconds() / 86400.0)
        mark_price = c.mark_price or (c.strike * 0.05)
        mark_iv = c.mark_iv or 0.50
        result.append(
            {
                "symbol": c.symbol,
                "asset": c.asset,
                "strike": float(c.strike),
                "option_type": opt_type,
                "type": opt_type.lower(),
                "side": opt_type,
                "expiry": c.expiry_at.isoformat(),
                "expiry_date": c.expiry_at.strftime("%Y-%m-%d"),
                "dte": dte,
                "delta": float(c.delta),
                "gamma": float(c.gamma),
                "theta": float(c.theta),
                "vega": float(c.vega),
                "mark_price": float(mark_price),
                "mark_iv": float(mark_iv),
                "bid_price": float(c.bid_price or mark_price),
                "ask_price": float(c.ask_price or mark_price),
                "spot_price": float(c.spot_price),
            }
        )
    return result


class BaseTraderAgent(ABC):
    """Abstract base class for specialized option trader agents in the swarm."""

    def __init__(self, name: str, strategy_type: str) -> None:
        self.name = name
        self.strategy_type = strategy_type

    @abstractmethod
    def evaluate(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
    ) -> CandidateSignal | None:
        """Scan available contracts and return normalized CandidateSignal if opportunity exists."""
        pass


class IronCondorTrader(BaseTraderAgent):
    """Trader specializing in 4-leg neutral range-bound premium selling."""

    def __init__(self, config: IronCondorConfig | None = None) -> None:
        super().__init__(name="IronCondorTrader", strategy_type="iron_condor")
        self.config = config or IronCondorConfig(paper_mode=True)
        self.bot = IronCondorBot(self.config)

    def evaluate(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
    ) -> CandidateSignal | None:
        spot = spot_price or report.metrics.spot_price
        c_dicts = contracts_to_dicts(contracts)
        raw_cand = self.bot.select_iron_condor_candidate(c_dicts, spot=spot)
        if not raw_cand:
            return None

        # Build normalized legs: Long Put, Short Put, Short Call, Long Call
        legs = (
            CandidateLeg(
                symbol=raw_cand.long_put["symbol"],
                strike=float(raw_cand.long_put["strike"]),
                option_type="Put",
                side="BUY",
                mark_price=float(raw_cand.long_put["mark_price"]),
                iv=float(raw_cand.long_put.get("mark_iv", 0.5)),
                delta=float(raw_cand.long_put.get("delta", -0.03)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.short_put["symbol"],
                strike=float(raw_cand.short_put["strike"]),
                option_type="Put",
                side="SELL",
                mark_price=float(raw_cand.short_put["mark_price"]),
                iv=float(raw_cand.short_put.get("mark_iv", 0.5)),
                delta=float(raw_cand.short_put.get("delta", -0.15)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.short_call["symbol"],
                strike=float(raw_cand.short_call["strike"]),
                option_type="Call",
                side="SELL",
                mark_price=float(raw_cand.short_call["mark_price"]),
                iv=float(raw_cand.short_call.get("mark_iv", 0.5)),
                delta=float(raw_cand.short_call.get("delta", 0.15)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.long_call["symbol"],
                strike=float(raw_cand.long_call["strike"]),
                option_type="Call",
                side="BUY",
                mark_price=float(raw_cand.long_call["mark_price"]),
                iv=float(raw_cand.long_call.get("mark_iv", 0.5)),
                delta=float(raw_cand.long_call.get("delta", 0.03)),
                dte=raw_cand.dte,
            ),
        )

        return CandidateSignal(
            signal_id=f"sig_{raw_cand.condor_id}",
            strategy="iron_condor",
            trader_name=self.name,
            asset=report.asset,
            expiry_date=raw_cand.expiry_date,
            dte=raw_cand.dte,
            direction="NEUTRAL",
            action_type="CREDIT",
            net_premium_per_unit=raw_cand.net_credit_per_unit,
            max_loss_per_unit=raw_cand.max_loss_per_unit,
            max_profit_per_unit=raw_cand.net_credit_per_unit,
            legs=legs,
            model_edge=max(0.0, report.metrics.iv_rv_spread),
            underlying_spot=spot,
            raw_candidate=raw_cand.__dict__,
            created_at=datetime.now(UTC).isoformat(),
        )


class WheelTrader(BaseTraderAgent):
    """Trader specializing in The Wheel strategy (Cash-Secured Puts & Covered Calls)."""

    def __init__(self, config: WheelConfig | None = None) -> None:
        super().__init__(name="WheelTrader", strategy_type="wheel")
        self.config = config or WheelConfig(asset="BTC")
        self.bot = WheelBot(self.config)

    def evaluate(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
    ) -> CandidateSignal | None:
        spot = spot_price or report.metrics.spot_price
        c_dicts = contracts_to_dicts(contracts)

        # In CSP phase
        raw_cand = self.bot.select_csp_candidate(c_dicts, spot=spot)
        if not raw_cand:
            return None

        premium = getattr(raw_cand, "premium_collected", getattr(raw_cand, "mark_price", 0.0))
        leg = CandidateLeg(
            symbol=raw_cand.symbol,
            strike=raw_cand.strike,
            option_type="Put",
            side="SELL",
            mark_price=premium,
            iv=raw_cand.delta,  # delta as fallback proxy if iv omitted
            delta=raw_cand.delta,
            dte=raw_cand.dte,
        )

        # Max loss for CSP is strike - premium (if spot drops to 0)
        max_loss = max(1.0, raw_cand.strike - premium)

        return CandidateSignal(
            signal_id=f"sig_wheel_{raw_cand.candidate_id}",
            strategy="wheel",
            trader_name=self.name,
            asset=report.asset,
            expiry_date=raw_cand.expiry_date,
            dte=raw_cand.dte,
            direction="NEUTRAL" if report.trend_regime == TrendRegime.NEUTRAL_CONSOLIDATING else "BULLISH",
            action_type="CREDIT",
            net_premium_per_unit=premium,
            max_loss_per_unit=max_loss,
            max_profit_per_unit=premium,
            legs=(leg,),
            model_edge=max(0.0, premium),
            underlying_spot=spot,
            raw_candidate=raw_cand.__dict__,
            created_at=datetime.now(UTC).isoformat(),
        )


class VerticalSpreadTrader(BaseTraderAgent):
    """Trader specializing in Directional Bull Put and Bear Call credit spreads."""

    def __init__(self, config: VerticalSpreadConfig | None = None) -> None:
        super().__init__(name="VerticalSpreadTrader", strategy_type="vertical_spread")
        self.config = config or VerticalSpreadConfig(asset="BTC")
        self.bot = VerticalSpreadBot(self.config)

    def evaluate(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
    ) -> CandidateSignal | None:
        spot = spot_price or report.metrics.spot_price
        c_dicts = contracts_to_dicts(contracts)

        # Decide direction based on trend regime
        is_bullish = report.trend_regime in {TrendRegime.BULLISH, TrendRegime.STRONG_BULL, TrendRegime.NEUTRAL_CONSOLIDATING}
        trend_dir = "BULLISH" if is_bullish else "BEARISH"

        raw_cand = self.bot.select_candidate(c_dicts, spot=spot, trend_direction=trend_dir)
        if not raw_cand:
            alt_dir = "BEARISH" if is_bullish else "BULLISH"
            raw_cand = self.bot.select_candidate(c_dicts, spot=spot, trend_direction=alt_dir)
            if not raw_cand:
                return None

        is_put = raw_cand.spread_type.upper() == "BULL_PUT"
        opt_type = "Put" if is_put else "Call"
        legs = (
            CandidateLeg(
                symbol=raw_cand.short_leg["symbol"],
                strike=float(raw_cand.short_leg["strike"]),
                option_type=opt_type,
                side="SELL",
                mark_price=float(raw_cand.short_leg.get("mark_price") or raw_cand.short_leg.get("mark", 0.0)),
                iv=float(raw_cand.short_leg.get("mark_iv", 0.5)),
                delta=float(raw_cand.short_leg.get("delta", -0.25 if is_put else 0.25)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.long_wing["symbol"],
                strike=float(raw_cand.long_wing["strike"]),
                option_type=opt_type,
                side="BUY",
                mark_price=float(raw_cand.long_wing.get("mark_price") or raw_cand.long_wing.get("mark", 0.0)),
                iv=float(raw_cand.long_wing.get("mark_iv", 0.5)),
                delta=float(raw_cand.long_wing.get("delta", -0.10 if is_put else 0.10)),
                dte=raw_cand.dte,
            ),
        )

        direction = "BULLISH" if is_put else "BEARISH"
        credit_ratio = (raw_cand.net_credit / raw_cand.spread_width) if raw_cand.spread_width > 0 else 0.20

        return CandidateSignal(
            signal_id=f"sig_vert_{raw_cand.candidate_id}",
            strategy="vertical_spread",
            trader_name=self.name,
            asset=report.asset,
            expiry_date=raw_cand.expiry_date,
            dte=raw_cand.dte,
            direction=direction,
            action_type="CREDIT",
            net_premium_per_unit=raw_cand.net_credit,
            max_loss_per_unit=raw_cand.max_loss,
            max_profit_per_unit=raw_cand.net_credit,
            legs=legs,
            model_edge=credit_ratio * 100.0,
            underlying_spot=spot,
            raw_candidate=raw_cand.__dict__,
            created_at=datetime.now(UTC).isoformat(),
        )


class IronButterflyTrader(BaseTraderAgent):
    """Trader specializing in ATM Short Straddle + OTM Wings for maximum premium harvest."""

    def __init__(self, config: IronButterflyConfig | None = None) -> None:
        super().__init__(name="IronButterflyTrader", strategy_type="iron_butterfly")
        self.config = config or IronButterflyConfig(asset="BTC")
        self.bot = IronButterflyBot(self.config)

    def evaluate(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
    ) -> CandidateSignal | None:
        spot = spot_price or report.metrics.spot_price
        c_dicts = contracts_to_dicts(contracts)
        raw_cand = self.bot.select_candidate(c_dicts, spot=spot)
        if not raw_cand:
            return None

        def _get_mark(leg_dict: dict[str, Any]) -> float:
            return float(leg_dict.get("mark") or leg_dict.get("mark_price", 0.0))

        legs = (
            CandidateLeg(
                symbol=raw_cand.long_put["symbol"],
                strike=float(raw_cand.long_put["strike"]),
                option_type="Put",
                side="BUY",
                mark_price=_get_mark(raw_cand.long_put),
                iv=float(raw_cand.long_put.get("mark_iv", 0.5)),
                delta=float(raw_cand.long_put.get("delta", -0.10)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.short_put["symbol"],
                strike=float(raw_cand.short_put["strike"]),
                option_type="Put",
                side="SELL",
                mark_price=_get_mark(raw_cand.short_put),
                iv=float(raw_cand.short_put.get("mark_iv", 0.5)),
                delta=float(raw_cand.short_put.get("delta", -0.50)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.short_call["symbol"],
                strike=float(raw_cand.short_call["strike"]),
                option_type="Call",
                side="SELL",
                mark_price=_get_mark(raw_cand.short_call),
                iv=float(raw_cand.short_call.get("mark_iv", 0.5)),
                delta=float(raw_cand.short_call.get("delta", 0.50)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.long_call["symbol"],
                strike=float(raw_cand.long_call["strike"]),
                option_type="Call",
                side="BUY",
                mark_price=_get_mark(raw_cand.long_call),
                iv=float(raw_cand.long_call.get("mark_iv", 0.5)),
                delta=float(raw_cand.long_call.get("delta", 0.10)),
                dte=raw_cand.dte,
            ),
        )

        return CandidateSignal(
            signal_id=f"sig_ib_{raw_cand.candidate_id}",
            strategy="iron_butterfly",
            trader_name=self.name,
            asset=report.asset,
            expiry_date=raw_cand.expiry,
            dte=raw_cand.dte,
            direction="NEUTRAL",
            action_type="CREDIT",
            net_premium_per_unit=raw_cand.net_credit,
            max_loss_per_unit=raw_cand.max_loss,
            max_profit_per_unit=raw_cand.net_credit,
            legs=legs,
            model_edge=report.metrics.iv_rv_spread,
            underlying_spot=spot,
            raw_candidate=raw_cand.__dict__,
            created_at=datetime.now(UTC).isoformat(),
        )


class CalendarSpreadTrader(BaseTraderAgent):
    """Trader specializing in Term Structure theta differential & contango spreads."""

    def __init__(self, config: CalendarSpreadConfig | None = None) -> None:
        super().__init__(name="CalendarSpreadTrader", strategy_type="calendar_spread")
        self.config = config or CalendarSpreadConfig(asset="BTC")
        self.bot = CalendarSpreadBot(self.config)

    def evaluate(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
    ) -> CandidateSignal | None:
        spot = spot_price or report.metrics.spot_price
        c_dicts = contracts_to_dicts(contracts)
        raw_cand = self.bot.select_candidate(c_dicts, spot=spot, option_type="call")
        if not raw_cand:
            raw_cand = self.bot.select_candidate(c_dicts, spot=spot, option_type="put")
            if not raw_cand:
                return None

        is_call = "call" in raw_cand.near_leg.get("option_type", "call").lower()
        opt_type = "Call" if is_call else "Put"

        legs = (
            CandidateLeg(
                symbol=raw_cand.near_leg["symbol"],
                strike=float(raw_cand.near_leg["strike"]),
                option_type=opt_type,
                side="SELL",
                mark_price=float(raw_cand.near_leg["mark_price"]),
                iv=float(raw_cand.near_leg.get("mark_iv", 0.5)),
                delta=float(raw_cand.near_leg.get("delta", 0.50 if is_call else -0.50)),
                dte=raw_cand.near_dte,
            ),
            CandidateLeg(
                symbol=raw_cand.far_leg["symbol"],
                strike=float(raw_cand.far_leg["strike"]),
                option_type=opt_type,
                side="BUY",
                mark_price=float(raw_cand.far_leg["mark_price"]),
                iv=float(raw_cand.far_leg.get("mark_iv", 0.5)),
                delta=float(raw_cand.far_leg.get("delta", 0.50 if is_call else -0.50)),
                dte=raw_cand.far_dte,
            ),
        )

        return CandidateSignal(
            signal_id=f"sig_cal_{raw_cand.candidate_id}",
            strategy="calendar_spread",
            trader_name=self.name,
            asset=report.asset,
            expiry_date=raw_cand.near_expiry,
            dte=raw_cand.near_dte,
            direction="NEUTRAL",
            action_type="DEBIT",
            net_premium_per_unit=raw_cand.net_debit,
            max_loss_per_unit=raw_cand.net_debit,
            max_profit_per_unit=raw_cand.net_debit * 0.80,  # Estimated peak target profit
            legs=legs,
            model_edge=report.metrics.term_structure_slope,
            underlying_spot=spot,
            raw_candidate=raw_cand.__dict__,
            created_at=datetime.now(UTC).isoformat(),
        )


class LongVolTrader(BaseTraderAgent):
    """Trader specializing in Long Volatility Straddles/Strangles during IV Discount."""

    def __init__(self, config: LongVolConfig | None = None) -> None:
        super().__init__(name="LongVolTrader", strategy_type="long_vol")
        self.config = config or LongVolConfig(asset="BTC")
        self.bot = LongVolBot(self.config)

    def evaluate(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
    ) -> CandidateSignal | None:
        spot = spot_price or report.metrics.spot_price
        c_dicts = contracts_to_dicts(contracts)
        # Realized vol in decimal
        rv_dec = report.metrics.rv_30d / 100.0 if report.metrics.rv_30d > 2.0 else report.metrics.rv_30d
        raw_cand = self.bot.select_candidate(c_dicts, spot=spot, realized_vol=rv_dec)
        if not raw_cand:
            return None

        legs = (
            CandidateLeg(
                symbol=raw_cand.call_leg["symbol"],
                strike=float(raw_cand.call_leg["strike"]),
                option_type="Call",
                side="BUY",
                mark_price=float(raw_cand.call_leg["mark_price"]),
                iv=float(raw_cand.call_leg.get("mark_iv", 0.5)),
                delta=float(raw_cand.call_leg.get("delta", 0.50)),
                dte=raw_cand.dte,
            ),
            CandidateLeg(
                symbol=raw_cand.put_leg["symbol"],
                strike=float(raw_cand.put_leg["strike"]),
                option_type="Put",
                side="BUY",
                mark_price=float(raw_cand.put_leg["mark_price"]),
                iv=float(raw_cand.put_leg.get("mark_iv", 0.5)),
                delta=float(raw_cand.put_leg.get("delta", -0.50)),
                dte=raw_cand.dte,
            ),
        )

        return CandidateSignal(
            signal_id=f"sig_lv_{raw_cand.candidate_id}",
            strategy="long_vol",
            trader_name=self.name,
            asset=report.asset,
            expiry_date=raw_cand.expiry,
            dte=raw_cand.dte,
            direction="NEUTRAL",
            action_type="DEBIT",
            net_premium_per_unit=raw_cand.net_debit,
            max_loss_per_unit=raw_cand.net_debit,
            max_profit_per_unit=raw_cand.net_debit * 2.0,  # Defined-risk debit, theoretically unlimited upside
            legs=legs,
            model_edge=-report.metrics.iv_rv_spread,  # Positive edge when RV > IV
            underlying_spot=spot,
            raw_candidate=raw_cand.__dict__,
            created_at=datetime.now(UTC).isoformat(),
        )
