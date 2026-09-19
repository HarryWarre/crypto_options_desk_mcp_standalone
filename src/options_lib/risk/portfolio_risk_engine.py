"""Industry-standard Options Portfolio Risk Engine & Dynamic Position Sizing.

Implements fractional risk budgeting, Deribit lot-size rounding (0.1 BTC, 1.0 ETH),
Portfolio Margin utilization caps, and Net Greeks exposure limits.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any

from options_lib.swarm.candidate_signal import CandidateSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssetLotSpec:
    """Trading lot specifications for options on derivatives exchanges."""

    min_trade_amount: float
    step_size: float
    decimals: int


DEFAULT_ASSET_SPECS: dict[str, AssetLotSpec] = {
    "BTC": AssetLotSpec(min_trade_amount=0.1, step_size=0.1, decimals=1),
    "ETH": AssetLotSpec(min_trade_amount=1.0, step_size=1.0, decimals=0),
    "SOL": AssetLotSpec(min_trade_amount=1.0, step_size=1.0, decimals=0),
    "DOGE": AssetLotSpec(min_trade_amount=100.0, step_size=10.0, decimals=0),
    "XRP": AssetLotSpec(min_trade_amount=100.0, step_size=10.0, decimals=0),
    "MNT": AssetLotSpec(min_trade_amount=50.0, step_size=5.0, decimals=0),
}


@dataclass(frozen=True)
class RiskLimitsConfig:
    """Portfolio risk limits and sizing thresholds."""

    max_risk_pct_per_trade: float = 0.02  # Max 2% loss of total equity per single trade
    max_portfolio_margin_utilization: float = 0.60  # Maximum 60% total margin budget
    max_open_positions: int = 10  # Maximum concurrent open strategies
    max_net_delta_equity_ratio: float = 0.20  # Max portfolio net delta relative to equity
    max_asset_concentration_pct: float = 0.50  # Max 50% risk exposure to a single coin


@dataclass(frozen=True)
class RiskAssessmentResult:
    """Evaluation verdict and sizing determined by Risk Engine."""

    candidate_id: str
    strategy: str
    asset: str
    approved: bool
    allocated_qty: float
    allocated_max_loss: float
    allocated_margin: float
    margin_utilization_after: float
    net_delta_impact: float
    rejection_reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortfolioRiskEngine:
    """Derivative portfolio risk manager performing dynamic sizing and guardrail validation."""

    def __init__(
        self,
        config: RiskLimitsConfig | None = None,
        asset_specs: dict[str, AssetLotSpec] | None = None,
    ) -> None:
        self.config = config or RiskLimitsConfig()
        self.specs = asset_specs or DEFAULT_ASSET_SPECS

    def get_spec(self, asset: str) -> AssetLotSpec:
        """Get lot size specifications for asset."""
        return self.specs.get(
            asset.upper(),
            AssetLotSpec(min_trade_amount=0.1, step_size=0.1, decimals=1),
        )

    def evaluate_candidate(
        self,
        candidate: CandidateSignal,
        current_equity: float,
        current_margin_used: float = 0.0,
        current_open_positions_count: int = 0,
        current_portfolio_delta: float = 0.0,
        current_asset_risk_used: float = 0.0,
    ) -> RiskAssessmentResult:
        """Assess trade candidate against portfolio risk parameters and calculate dynamic size."""
        rejection_reasons: list[str] = []
        warnings: list[str] = []

        if current_equity <= 0:
            return RiskAssessmentResult(
                candidate_id=candidate.signal_id,
                strategy=candidate.strategy,
                asset=candidate.asset,
                approved=False,
                allocated_qty=0.0,
                allocated_max_loss=0.0,
                allocated_margin=0.0,
                margin_utilization_after=0.0,
                net_delta_impact=0.0,
                rejection_reasons=("zero_or_negative_equity",),
                warnings=(),
            )

        # 1. Check open position count limit
        if current_open_positions_count >= self.config.max_open_positions:
            rejection_reasons.append(
                f"max_open_positions_reached ({current_open_positions_count}/{self.config.max_open_positions})"
            )

        # 2. Check asset concentration limit
        max_asset_risk = current_equity * self.config.max_asset_concentration_pct
        if current_asset_risk_used >= max_asset_risk:
            rejection_reasons.append(
                f"asset_concentration_exceeded (${current_asset_risk_used:.2f} >= ${max_asset_risk:.2f})"
            )

        spec = self.get_spec(candidate.asset)

        # 3. Dynamic Position Sizing (Fixed % Risk Budget)
        risk_budget = current_equity * self.config.max_risk_pct_per_trade
        max_loss_per_unit = max(0.0001, candidate.max_loss_per_unit)

        # Theoretical optimal size
        raw_qty = risk_budget / max_loss_per_unit

        # Quantize to step size
        steps = math.floor(raw_qty / spec.step_size)
        qty = round(steps * spec.step_size, spec.decimals)

        # If quantized qty is below min_trade_amount, check if min_trade_amount exceeds risk budget
        if qty < spec.min_trade_amount:
            min_size_risk = spec.min_trade_amount * max_loss_per_unit
            # Allow up to 10% slippage above budget for minimum viable order
            if min_size_risk <= risk_budget * 1.10:
                qty = spec.min_trade_amount
                warnings.append("qty_rounded_up_to_min_trade_amount")
            else:
                rejection_reasons.append(
                    f"risk_budget_below_minimum_size (Budget: ${risk_budget:.2f}, Min Risk: ${min_size_risk:.2f})"
                )
                qty = 0.0

        # 4. Estimate Unit Margin Requirement
        # For defined-risk credit: margin is approx max_loss + credit (i.e. wing width)
        # For debit: margin is upfront premium
        if candidate.action_type == "DEBIT":
            unit_margin = max(1.0, candidate.net_premium_per_unit)
        else:
            unit_margin = max(1.0, candidate.max_loss_per_unit)

        trade_margin = qty * unit_margin
        total_margin_after = current_margin_used + trade_margin
        utilization_after = (total_margin_after / current_equity) * 100.0

        # 5. Check and enforce Portfolio Margin Ceiling
        max_allowed_margin = current_equity * self.config.max_portfolio_margin_utilization
        if total_margin_after > max_allowed_margin:
            # Try to scale down quantity
            available_margin = max(0.0, max_allowed_margin - current_margin_used)
            scaled_steps = math.floor((available_margin / unit_margin) / spec.step_size)
            scaled_qty = round(scaled_steps * spec.step_size, spec.decimals)

            if scaled_qty >= spec.min_trade_amount:
                warnings.append(
                    f"qty_scaled_down_for_margin (From {qty} to {scaled_qty} to keep margin < {self.config.max_portfolio_margin_utilization*100:.0f}%)"
                )
                qty = scaled_qty
                trade_margin = qty * unit_margin
                total_margin_after = current_margin_used + trade_margin
                utilization_after = (total_margin_after / current_equity) * 100.0
            else:
                rejection_reasons.append(
                    f"margin_utilization_exceeded ({utilization_after:.1f}% > {self.config.max_portfolio_margin_utilization*100:.0f}%)"
                )
                qty = 0.0

        # 6. Greeks Exposure Check (Net Delta)
        candidate_delta_per_unit = sum(leg.delta * leg.ratio for leg in candidate.legs)
        delta_impact = candidate_delta_per_unit * qty
        projected_portfolio_delta = current_portfolio_delta + delta_impact

        spot = max(1.0, candidate.underlying_spot)
        max_delta_limit = (current_equity / spot) * self.config.max_net_delta_equity_ratio
        if abs(projected_portfolio_delta) > max_delta_limit:
            rejection_reasons.append(
                f"portfolio_delta_limit_exceeded ({projected_portfolio_delta:.3f} exceeds ±{max_delta_limit:.3f})"
            )

        approved = len(rejection_reasons) == 0 and qty >= spec.min_trade_amount
        allocated_max_loss = round(qty * max_loss_per_unit, 2)
        allocated_margin = round(trade_margin, 2)

        return RiskAssessmentResult(
            candidate_id=candidate.signal_id,
            strategy=candidate.strategy,
            asset=candidate.asset,
            approved=approved,
            allocated_qty=qty if approved else 0.0,
            allocated_max_loss=allocated_max_loss if approved else 0.0,
            allocated_margin=allocated_margin if approved else 0.0,
            margin_utilization_after=round(utilization_after, 2),
            net_delta_impact=round(delta_impact, 4),
            rejection_reasons=tuple(rejection_reasons),
            warnings=tuple(warnings),
        )


def calculate_backtest_position_size(
    current_equity: float,
    max_loss_per_unit: float,
    asset: str = "BTC",
    risk_pct: float = 0.02,
    max_margin_utilization: float = 0.60,
    current_margin_used: float = 0.0,
    fixed_qty: float | None = None,
) -> float:
    """Calculate dynamic position size for backtest replay matching exchange standards."""
    if fixed_qty is not None:
        return max(0.0, float(fixed_qty))
    if current_equity <= 0 or max_loss_per_unit <= 0:
        return 0.0

    spec = DEFAULT_ASSET_SPECS.get(
        asset.upper(),
        AssetLotSpec(min_trade_amount=0.1, step_size=0.1, decimals=1),
    )

    risk_budget = current_equity * risk_pct
    raw_qty = risk_budget / max(0.0001, max_loss_per_unit)
    steps = math.floor(raw_qty / spec.step_size)
    qty = round(steps * spec.step_size, spec.decimals)

    if qty < spec.min_trade_amount:
        min_risk = spec.min_trade_amount * max_loss_per_unit
        # Allow 1 minimum viable lot as long as single-trade risk stays within 5% of equity
        if min_risk <= current_equity * 0.05:
            qty = spec.min_trade_amount
        else:
            return 0.0

    # Margin check
    max_allowed_margin = current_equity * max_margin_utilization
    unit_margin = max(1.0, max_loss_per_unit)
    total_margin = current_margin_used + (qty * unit_margin)
    if total_margin > max_allowed_margin:
        avail = max(0.0, max_allowed_margin - current_margin_used)
        scaled_steps = math.floor((avail / max(0.0001, unit_margin)) / spec.step_size)
        qty = round(scaled_steps * spec.step_size, spec.decimals)
        if qty < spec.min_trade_amount:
            return 0.0

    return max(0.0, qty)

