"""Trader Pool coordinating specialized option trader agents in the swarm."""

from __future__ import annotations

import logging
from typing import Sequence

from bybit_api.options_market_data import OptionContract
from options_lib.research.market_regime import MarketRegimeReport
from options_lib.swarm.candidate_signal import CandidateSignal
from options_lib.swarm.trader_agents import (
    BaseTraderAgent,
    CalendarSpreadTrader,
    IronButterflyTrader,
    IronCondorTrader,
    LongVolTrader,
    VerticalSpreadTrader,
    WheelTrader,
)

logger = logging.getLogger(__name__)


class TraderPool:
    """Orchestrates candidate generation across all specialized trader agents."""

    def __init__(self, agents: Sequence[BaseTraderAgent] | None = None) -> None:
        if agents is not None:
            self.agents: list[BaseTraderAgent] = list(agents)
        else:
            self.agents = [
                IronCondorTrader(),
                WheelTrader(),
                VerticalSpreadTrader(),
                IronButterflyTrader(),
                CalendarSpreadTrader(),
                LongVolTrader(),
            ]

    def register_agent(self, agent: BaseTraderAgent) -> None:
        """Register a new specialized trader agent into the pool."""
        self.agents.append(agent)

    def generate_candidates(
        self,
        report: MarketRegimeReport,
        contracts: Sequence[OptionContract],
        spot_price: float | None = None,
        force_all: bool = False,
    ) -> list[CandidateSignal]:
        """Evaluate market opportunities across trader agents aligned with market regime.

        By default, agents whose strategy is marked in `report.avoid_strategies`
        are skipped to prevent low-edge/toxic entries.
        """
        candidates: list[CandidateSignal] = []
        avoid_set = set(report.avoid_strategies) if not force_all else set()
        rec_set = set(report.recommended_strategies)

        # Sort agents: recommended first, others next, avoiding prohibited unless force_all
        def sort_key(agent: BaseTraderAgent) -> int:
            if agent.strategy_type in rec_set:
                return 0
            if agent.strategy_type in avoid_set:
                return 2
            return 1

        ordered_agents = sorted(self.agents, key=sort_key)

        for agent in ordered_agents:
            if not force_all and agent.strategy_type in avoid_set:
                logger.debug("Skipping %s due to avoid_strategies directive", agent.name)
                continue

            try:
                cand = agent.evaluate(report, contracts, spot_price=spot_price)
                if cand is not None:
                    candidates.append(cand)
            except Exception as e:
                logger.warning("Error evaluating trader %s: %s", agent.name, e)

        # Rank candidates: recommended first, then highest model_edge
        def rank_key(sig: CandidateSignal) -> tuple[int, float]:
            is_rec = 0 if sig.strategy in rec_set else 1
            return (is_rec, -sig.model_edge)

        candidates.sort(key=rank_key)
        return candidates
