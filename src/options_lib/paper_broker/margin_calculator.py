"""Margin Calculator for Bybit Options & Portfolio Margin Simulation.

Implements Bybit Portfolio Margin (PMM) estimation and standard margin rules,
with special support for:
1. Defined-risk multi-leg strategies (Vertical Spreads, Iron Condor, Butterflies).
2. Naked option short margins.
3. Account-level Margin Utilization and Liquidation threshold warnings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from options_lib.symbol_parser import parse_bybit_option_symbol

if TYPE_CHECKING:
    from .account import PaperPosition


@dataclass
class MarginSummary:
    """Margin evaluation for a portfolio of positions."""

    initial_margin: float
    maintenance_margin: float
    equity: float
    available_margin: float
    margin_utilization_pct: float
    is_warning: bool  # >= 80% utilization
    is_critical: bool  # >= 90% utilization
    is_liquidatable: bool  # equity < maintenance_margin

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_margin": round(self.initial_margin, 4),
            "maintenance_margin": round(self.maintenance_margin, 4),
            "equity": round(self.equity, 4),
            "available_margin": round(self.available_margin, 4),
            "margin_utilization_pct": round(self.margin_utilization_pct, 2),
            "is_warning": self.is_warning,
            "is_critical": self.is_critical,
            "is_liquidatable": self.is_liquidatable,
        }


class MarginCalculator:
    """Calculates margin requirements following Bybit Portfolio Margin principles."""

    def __init__(
        self,
        warning_utilization_pct: float = 80.0,
        critical_utilization_pct: float = 90.0,
    ) -> None:
        self.warning_utilization_pct = warning_utilization_pct
        self.critical_utilization_pct = critical_utilization_pct

    def compute_position_margin(
        self,
        pos: PaperPosition,
        spot_price: float,
    ) -> tuple[float, float]:
        """Compute (initial_margin, maintenance_margin) for a single leg standalone."""
        if pos.side == "Buy":
            # Long options require 100% upfront premium, zero maintenance margin
            return 0.0, 0.0

        parsed = parse_bybit_option_symbol(pos.symbol)
        strike = parsed["strike"] if parsed else spot_price
        opt_type = parsed["option_type_long"] if parsed else "call"
        mark = pos.current_mark_price or pos.entry_price

        # Bybit standard naked short margin approximation
        if opt_type == "call":
            otm_amount = max(0.0, strike - spot_price)
            im = (
                max(0.10 * spot_price - otm_amount, 0.05 * spot_price) + mark
            ) * pos.qty
            mm = (
                max(0.07 * spot_price - otm_amount, 0.035 * spot_price) + mark
            ) * pos.qty
        else:  # put
            otm_amount = max(0.0, spot_price - strike)
            im = (
                max(0.10 * spot_price - otm_amount, 0.05 * strike) + mark
            ) * pos.qty
            mm = (
                max(0.07 * spot_price - otm_amount, 0.035 * strike) + mark
            ) * pos.qty

        return max(0.0, im), max(0.0, mm)

    def evaluate_portfolio(
        self,
        positions: dict[str, PaperPosition],
        equity: float,
        spot_price: float,
    ) -> MarginSummary:
        """Evaluate margin requirements across all open positions.

        Under Portfolio Margin:
        - Legs grouped under the same strategy_id (e.g. Iron Condor) are evaluated as a combo.
        - An Iron Condor's required margin is max(Put spread margin, Call spread margin).
        - Independent naked legs are added linearly.
        """
        if not positions:
            return MarginSummary(
                initial_margin=0.0,
                maintenance_margin=0.0,
                equity=equity,
                available_margin=equity,
                margin_utilization_pct=0.0,
                is_warning=False,
                is_critical=False,
                is_liquidatable=False,
            )

        # Group positions by strategy_id
        by_strategy: dict[str, list[PaperPosition]] = {}
        standalone: list[PaperPosition] = []

        for pos in positions.values():
            if pos.strategy_id:
                by_strategy.setdefault(pos.strategy_id, []).append(pos)
            else:
                standalone.append(pos)

        total_im = 0.0
        total_mm = 0.0

        # 1. Evaluate combos
        for strat_id, legs in by_strategy.items():
            strat_im, strat_mm = self._evaluate_combo_margin(legs, spot_price)
            total_im += strat_im
            total_mm += strat_mm

        # 2. Evaluate standalone legs
        for pos in standalone:
            im, mm = self.compute_position_margin(pos, spot_price)
            total_im += im
            total_mm += mm

        available = max(0.0, equity - total_im)
        utilization = (total_im / equity * 100.0) if equity > 0 else 100.0

        return MarginSummary(
            initial_margin=total_im,
            maintenance_margin=total_mm,
            equity=equity,
            available_margin=available,
            margin_utilization_pct=utilization,
            is_warning=utilization >= self.warning_utilization_pct,
            is_critical=utilization >= self.critical_utilization_pct,
            is_liquidatable=equity < total_mm and total_mm > 0,
        )

    def _evaluate_combo_margin(
        self,
        legs: list[PaperPosition],
        spot_price: float,
    ) -> tuple[float, float]:
        """Compute combo margin for recognized structures like Vertical Spread or Iron Condor."""
        # Split into puts and calls
        calls: list[PaperPosition] = []
        puts: list[PaperPosition] = []

        for leg in legs:
            parsed = parse_bybit_option_symbol(leg.symbol)
            opt_type = parsed["option_type_long"] if parsed else "call"
            if opt_type == "call":
                calls.append(leg)
            else:
                puts.append(leg)

        call_spread_margin = self._spread_margin(calls, spot_price, "call")
        put_spread_margin = self._spread_margin(puts, spot_price, "put")

        # If it's an Iron Condor (has both Call spread and Put spread defined risk):
        # Portfolio Margin requires only the greater of the two sides
        if len(calls) == 2 and len(puts) == 2:
            im = max(call_spread_margin[0], put_spread_margin[0])
            mm = max(call_spread_margin[1], put_spread_margin[1])
            return im, mm

        # Otherwise sum the wings
        return (
            call_spread_margin[0] + put_spread_margin[0],
            call_spread_margin[1] + put_spread_margin[1],
        )

    def _spread_margin(
        self,
        legs: list[PaperPosition],
        spot_price: float,
        opt_type: str,
    ) -> tuple[float, float]:
        """Compute margin for a set of calls or puts within a combo."""
        if not legs:
            return 0.0, 0.0

        # If exactly 1 short and 1 long leg with same qty -> Vertical Credit Spread
        if len(legs) == 2:
            short_leg = next((l for l in legs if l.side == "Sell"), None)
            long_leg = next((l for l in legs if l.side == "Buy"), None)

            if short_leg and long_leg and abs(short_leg.qty - long_leg.qty) < 1e-6:
                p_short = parse_bybit_option_symbol(short_leg.symbol)
                p_long = parse_bybit_option_symbol(long_leg.symbol)
                if p_short and p_long:
                    strike_diff = abs(p_short["strike"] - p_long["strike"])
                    # Defined max risk is spread width * qty
                    spread_margin = strike_diff * short_leg.qty
                    return spread_margin, spread_margin * 0.85

        # Fallback: sum single leg margins
        im_sum, mm_sum = 0.0, 0.0
        for l in legs:
            im, mm = self.compute_position_margin(l, spot_price)
            im_sum += im
            mm_sum += mm
        return im_sum, mm_sum

