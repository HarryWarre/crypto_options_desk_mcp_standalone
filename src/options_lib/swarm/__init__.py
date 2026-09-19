"""Multi-Agent Swarm module for crypto options trading."""

from .candidate_signal import CandidateLeg, CandidateSignal
from .trader_agents import (
    BaseTraderAgent,
    CalendarSpreadTrader,
    IronButterflyTrader,
    IronCondorTrader,
    LongVolTrader,
    VerticalSpreadTrader,
    WheelTrader,
)
from .trader_pool import TraderPool

__all__ = [
    "CandidateLeg",
    "CandidateSignal",
    "BaseTraderAgent",
    "IronCondorTrader",
    "WheelTrader",
    "VerticalSpreadTrader",
    "IronButterflyTrader",
    "CalendarSpreadTrader",
    "LongVolTrader",
    "TraderPool",
]
