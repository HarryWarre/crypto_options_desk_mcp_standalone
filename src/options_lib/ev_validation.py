"""Reproducible, held-out evidence checks for option strategy research.

This module evaluates supplied historical outcomes; it does not manufacture
outcomes from a current quote and it never turns a small sample into a trading
guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class BacktestStatus(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    VALIDATED_POSITIVE_EV = "validated_positive_ev"
    VALIDATED_NON_POSITIVE_EV = "validated_non_positive_ev"


@dataclass(frozen=True)
class HistoricalTradeSample:
    timestamp: datetime
    gross_pnl: float
    notional: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        for name, value in (("gross_pnl", self.gross_pnl), ("notional", self.notional)):
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.notional <= 0:
            raise ValueError("notional must be positive")


@dataclass(frozen=True)
class ValidationConfig:
    holdout_fraction: float = 0.3
    holdout_count: int | None = None
    minimum_train_samples: int = 30
    minimum_holdout_samples: int = 30
    fee_bps_per_leg: float = 0.0
    slippage_bps_per_leg: float = 0.0
    cost_sensitivity_multipliers: tuple[float, ...] = (1.0, 2.0, 5.0)
    lookahead_verified: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.holdout_fraction < 1:
            raise ValueError("holdout_fraction must be greater than 0 and less than 1")
        if self.holdout_count is not None and self.holdout_count < 1:
            raise ValueError("holdout_count must be positive")
        if self.minimum_train_samples < 0 or self.minimum_holdout_samples < 1:
            raise ValueError("minimum sample counts are invalid")
        for name, value in (
            ("fee_bps_per_leg", self.fee_bps_per_leg),
            ("slippage_bps_per_leg", self.slippage_bps_per_leg),
        ):
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not self.cost_sensitivity_multipliers or any(
            not math.isfinite(float(value)) or value <= 0
            for value in self.cost_sensitivity_multipliers
        ):
            raise ValueError("cost_sensitivity_multipliers must contain positive finite values")


@dataclass(frozen=True)
class BacktestMetrics:
    trade_count: int
    wins: int
    losses: int
    net_pnl: float
    total_cost: float
    expected_value: float
    average_win: float
    average_loss: float
    max_drawdown: float


@dataclass(frozen=True)
class CostSensitivityPoint:
    multiplier: float
    net_pnl: float
    expected_value: float


@dataclass(frozen=True)
class BacktestReport:
    status: BacktestStatus
    train: BacktestMetrics
    holdout: BacktestMetrics
    cost_sensitivity: tuple[CostSensitivityPoint, ...]
    split_timestamp: datetime | None
    lookahead_free: bool
    evidence_note: str


def validate_backtest(
    samples: tuple[HistoricalTradeSample, ...] | list[HistoricalTradeSample],
    config: ValidationConfig,
) -> BacktestReport:
    """Evaluate chronological outcomes and classify held-out evidence."""

    ordered = tuple(sorted(samples, key=lambda sample: sample.timestamp))
    holdout_count = config.holdout_count
    if holdout_count is None:
        holdout_count = max(1, math.ceil(len(ordered) * config.holdout_fraction))
    holdout = ordered[-holdout_count:] if ordered else ()
    train = ordered[:-holdout_count] if ordered else ()

    train_metrics = _metrics(train, config, multiplier=1.0)
    holdout_metrics = _metrics(holdout, config, multiplier=1.0)
    sensitivity = tuple(
        CostSensitivityPoint(
            multiplier=float(multiplier),
            net_pnl=_metrics(holdout, config, multiplier=float(multiplier)).net_pnl,
            expected_value=_metrics(holdout, config, multiplier=float(multiplier)).expected_value,
        )
        for multiplier in config.cost_sensitivity_multipliers
    )

    enough_data = (
        len(train) >= config.minimum_train_samples
        and len(holdout) >= config.minimum_holdout_samples
    )
    if not enough_data:
        status = BacktestStatus.INSUFFICIENT_EVIDENCE
        note = "Insufficient held-out evidence; a positive result is not a guarantee of future returns."
    elif not config.lookahead_verified:
        status = BacktestStatus.INSUFFICIENT_EVIDENCE
        note = "Signal-generation look-ahead has not been independently verified; a positive result is not a guarantee of future returns."
    elif holdout_metrics.expected_value > 0:
        status = BacktestStatus.VALIDATED_POSITIVE_EV
        note = "Positive expected value is observed on the held-out sample after costs; this is not a guarantee of future returns."
    else:
        status = BacktestStatus.VALIDATED_NON_POSITIVE_EV
        note = "Held-out expected value is not positive after costs; this is not a guarantee of future returns."

    return BacktestReport(
        status=status,
        train=train_metrics,
        holdout=holdout_metrics,
        cost_sensitivity=sensitivity,
        split_timestamp=holdout[0].timestamp if holdout else None,
        lookahead_free=config.lookahead_verified,
        evidence_note=note,
    )


def _metrics(
    samples: tuple[HistoricalTradeSample, ...],
    config: ValidationConfig,
    *,
    multiplier: float,
) -> BacktestMetrics:
    net_values = tuple(
        sample.gross_pnl
        - sample.notional
        * 2.0
        * (config.fee_bps_per_leg + config.slippage_bps_per_leg)
        / 10_000.0
        * multiplier
        for sample in samples
    )
    costs = tuple(
        sample.notional
        * 2.0
        * (config.fee_bps_per_leg + config.slippage_bps_per_leg)
        / 10_000.0
        * multiplier
        for sample in samples
    )
    wins = tuple(value for value in net_values if value > 0)
    losses = tuple(value for value in net_values if value < 0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    total = sum(net_values)
    return BacktestMetrics(
        trade_count=len(net_values),
        wins=len(wins),
        losses=len(losses),
        net_pnl=total,
        total_cost=sum(costs),
        expected_value=total / len(net_values) if net_values else 0.0,
        average_win=sum(wins) / len(wins) if wins else 0.0,
        average_loss=sum(losses) / len(losses) if losses else 0.0,
        max_drawdown=max_drawdown,
    )


__all__ = [
    "BacktestMetrics",
    "BacktestReport",
    "BacktestStatus",
    "CostSensitivityPoint",
    "HistoricalTradeSample",
    "ValidationConfig",
    "validate_backtest",
]
