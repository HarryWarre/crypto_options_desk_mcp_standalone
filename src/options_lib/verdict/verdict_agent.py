"""Verdict Agent for Multi-Agent Options Swarm (Full Autonomous Execution).

Receives risk-assessed candidates and autonomously executes approved trades
on the Deribit broker adapter or records audited rejections.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from options_lib.paper_broker.deribit_adapter import DeribitBrokerAdapter
from options_lib.paper_broker.matching_engine import OrderType, PaperOrder
from options_lib.risk.portfolio_risk_engine import RiskAssessmentResult
from options_lib.swarm.candidate_signal import CandidateSignal

logger = logging.getLogger(__name__)


class VerdictStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class VerdictDecision:
    """Auditable final decision and execution result from Verdict Agent."""

    decision_id: str
    signal_id: str
    strategy: str
    asset: str
    status: VerdictStatus
    allocated_qty: float
    allocated_margin: float
    allocated_max_loss: float
    reasons: tuple[str, ...]
    execution_order_ids: tuple[str, ...]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class VerdictAgent:
    """Full Autonomous Swarm Verdict Agent."""

    def __init__(self, name: str = "VerdictAgent") -> None:
        self.name = name

    def process_candidate(
        self,
        candidate: CandidateSignal,
        risk_res: RiskAssessmentResult,
        broker: DeribitBrokerAdapter | None = None,
    ) -> VerdictDecision:
        """Evaluate risk assessment and execute approved multi-leg orders on broker."""
        decision_id = f"verdict_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(UTC).isoformat()

        if not risk_res.approved or risk_res.allocated_qty <= 0:
            return VerdictDecision(
                decision_id=decision_id,
                signal_id=candidate.signal_id,
                strategy=candidate.strategy,
                asset=candidate.asset,
                status=VerdictStatus.REJECTED,
                allocated_qty=0.0,
                allocated_margin=0.0,
                allocated_max_loss=0.0,
                reasons=risk_res.rejection_reasons or ("risk_criteria_not_met",),
                execution_order_ids=(),
                timestamp=now_iso,
            )

        # Candidate is Approved! Execute on broker if connected
        execution_order_ids: list[str] = []
        if broker is not None:
            for leg in candidate.legs:
                side_str = "Buy" if leg.side.upper() == "BUY" else "Sell"
                leg_order = PaperOrder(
                    order_id=f"ord_{uuid.uuid4().hex[:8]}",
                    symbol=leg.symbol,
                    side=side_str,
                    qty=risk_res.allocated_qty * leg.ratio,
                    price=leg.mark_price if leg.mark_price > 0 else None,
                    order_type=OrderType.LIMIT if leg.mark_price > 0 else OrderType.MARKET,
                    strategy_id=candidate.strategy,
                )
                try:
                    res = broker.execute_order(leg_order, spot=candidate.underlying_spot)
                    if res and res.order_id:
                        execution_order_ids.append(res.order_id)
                except Exception as e:
                    logger.error("Failed to execute leg %s on Deribit: %s", leg.symbol, e)

        return VerdictDecision(
            decision_id=decision_id,
            signal_id=candidate.signal_id,
            strategy=candidate.strategy,
            asset=candidate.asset,
            status=VerdictStatus.APPROVED,
            allocated_qty=risk_res.allocated_qty,
            allocated_margin=risk_res.allocated_margin,
            allocated_max_loss=risk_res.allocated_max_loss,
            reasons=(),
            execution_order_ids=tuple(execution_order_ids),
            timestamp=now_iso,
        )
