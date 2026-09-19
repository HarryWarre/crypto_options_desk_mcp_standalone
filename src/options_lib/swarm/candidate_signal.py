"""Normalized Candidate Signal and Leg representations for Multi-Agent Swarm."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateLeg:
    """Normalized single option leg within a multi-leg structure."""

    symbol: str
    strike: float
    option_type: str  # "Call" or "Put"
    side: str  # "BUY" or "SELL"
    ratio: float = 1.0
    mark_price: float = 0.0
    iv: float = 0.0
    delta: float = 0.0
    dte: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateSignal:
    """Standardized trading candidate emitted by specialized Trader Agents."""

    signal_id: str
    strategy: str  # "iron_condor", "wheel", "vertical_spread", "iron_butterfly", "calendar_spread", "long_vol"
    trader_name: str
    asset: str
    expiry_date: str
    dte: float
    direction: str  # "NEUTRAL", "BULLISH", "BEARISH"
    action_type: str  # "CREDIT" or "DEBIT"
    net_premium_per_unit: float  # Credit received (positive) or Debit paid (positive for debit cost)
    max_loss_per_unit: float
    max_profit_per_unit: float
    legs: tuple[CandidateLeg, ...]
    model_edge: float
    underlying_spot: float
    raw_candidate: dict[str, Any]
    created_at: str

    @property
    def risk_reward_ratio(self) -> float:
        """Ratio of max potential profit to max potential loss."""
        if self.max_loss_per_unit <= 0.0001:
            return 1.0
        return self.max_profit_per_unit / self.max_loss_per_unit

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["legs"] = [leg.to_dict() for leg in self.legs]
        data["risk_reward_ratio"] = round(self.risk_reward_ratio, 4)
        return data
