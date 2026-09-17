"""Deterministic risk assessment and manual exit decision engine."""

from __future__ import annotations

from datetime import UTC, datetime

from .models import (
    DecisionAction,
    DecisionSeverity,
    ExitDecision,
    ExitPolicy,
    PositionSide,
    RiskAssessment,
    RiskRuleResult,
    TrackedPosition,
)


def _hours_between(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600)


class RiskMonitor:
    """Computes objective risk facts from an observed position and policy."""

    def assess(
        self,
        position: TrackedPosition,
        policy: ExitPolicy | None,
        *,
        as_of: datetime | None = None,
    ) -> RiskAssessment:
        now = as_of or datetime.now(tz=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        warnings: list[str] = []
        rules: list[RiskRuleResult] = []
        loss_pct: float | None = None
        holding_hours: float | None = None
        liquidation_distance_pct: float | None = None

        if policy is None:
            warnings.append("missing_exit_policy")
        elif policy.symbol != position.symbol:
            warnings.append("policy_symbol_mismatch")
        else:
            if policy.risk_budget:
                loss_pct = -position.unrealized_pnl / policy.risk_budget

            if policy.opened_at:
                holding_hours = _hours_between(policy.opened_at, now)

            if policy.thesis_status.value == "invalid":
                rules.append(
                    RiskRuleResult(
                        "thesis_invalid",
                        True,
                        DecisionSeverity.HIGH,
                        "manual thesis status is invalid",
                    )
                )

            if position.mark_price <= 0:
                warnings.append("invalid_mark_price")
            else:
                if policy.stop_loss_price is not None:
                    breached = (
                        position.mark_price <= policy.stop_loss_price
                        if position.side is PositionSide.LONG
                        else position.mark_price >= policy.stop_loss_price
                    )
                    rules.append(
                        RiskRuleResult(
                            "stop_loss",
                            breached,
                            DecisionSeverity.CRITICAL,
                            "mark price breached the configured stop loss"
                            if breached
                            else "mark price remains above the long stop or below the short stop",
                            value=position.mark_price,
                            threshold=policy.stop_loss_price,
                        )
                    )

                if policy.take_profit_price is not None:
                    reached = (
                        position.mark_price >= policy.take_profit_price
                        if position.side is PositionSide.LONG
                        else position.mark_price <= policy.take_profit_price
                    )
                    rules.append(
                        RiskRuleResult(
                            "take_profit",
                            reached,
                            DecisionSeverity.HIGH,
                            "mark price reached the configured take profit"
                            if reached
                            else "mark price has not reached the configured take profit",
                            value=position.mark_price,
                            threshold=policy.take_profit_price,
                        )
                    )

            if policy.max_loss_amount is not None:
                breached = position.unrealized_pnl <= -policy.max_loss_amount
                rules.append(
                    RiskRuleResult(
                        "max_loss_amount",
                        breached,
                        DecisionSeverity.CRITICAL,
                        "unrealized loss exceeded the configured amount"
                        if breached
                        else "unrealized loss is within the configured amount",
                        value=position.unrealized_pnl,
                        threshold=-policy.max_loss_amount,
                    )
                )

            if policy.max_loss_pct is not None and loss_pct is not None:
                breached = loss_pct >= policy.max_loss_pct
                rules.append(
                    RiskRuleResult(
                        "max_loss_pct",
                        breached,
                        DecisionSeverity.CRITICAL,
                        "loss percentage exceeded the configured risk budget"
                        if breached
                        else "loss percentage is within the configured risk budget",
                        value=loss_pct,
                        threshold=policy.max_loss_pct,
                    )
                )

            if policy.max_holding_hours is not None and holding_hours is not None:
                breached = holding_hours >= policy.max_holding_hours
                rules.append(
                    RiskRuleResult(
                        "max_holding_time",
                        breached,
                        DecisionSeverity.HIGH,
                        "position exceeded the configured maximum holding time"
                        if breached
                        else "position remains within the configured holding time",
                        value=holding_hours,
                        threshold=policy.max_holding_hours,
                    )
                )

            if position.liquidation_price and position.mark_price > 0:
                liquidation_distance_pct = (
                    (position.mark_price - position.liquidation_price) / position.mark_price
                    if position.side is PositionSide.LONG
                    else (position.liquidation_price - position.mark_price) / position.mark_price
                )
                if policy.min_liquidation_distance_pct is not None:
                    breached = liquidation_distance_pct <= policy.min_liquidation_distance_pct
                    rules.append(
                        RiskRuleResult(
                            "liquidation_distance",
                            breached,
                            DecisionSeverity.CRITICAL,
                            "mark price is too close to liquidation"
                            if breached
                            else "liquidation distance remains above the configured minimum",
                            value=liquidation_distance_pct,
                            threshold=policy.min_liquidation_distance_pct,
                        )
                    )
            elif policy.min_liquidation_distance_pct is not None and position.category in {
                "linear",
                "inverse",
            }:
                warnings.append("liquidation_price_unavailable")
        return RiskAssessment(
            symbol=position.symbol,
            unrealized_pnl=position.unrealized_pnl,
            loss_pct=loss_pct,
            liquidation_distance_pct=liquidation_distance_pct,
            holding_hours=holding_hours,
            rules=tuple(rules),
            warnings=tuple(warnings),
        )


class ExitDecisionEngine:
    """Turns risk facts into CLOSE, HOLD, or REVIEW without side effects."""

    def __init__(self, risk_monitor: RiskMonitor | None = None) -> None:
        self.risk_monitor = risk_monitor or RiskMonitor()

    def decide(
        self,
        position: TrackedPosition,
        policy: ExitPolicy | None,
        *,
        as_of: datetime | None = None,
    ) -> ExitDecision:
        assessment = self.risk_monitor.assess(position, policy, as_of=as_of)
        reasons = [rule.rule for rule in assessment.triggered_rules]
        reasons.extend(assessment.warnings)

        if assessment.triggered_rules:
            severity = max(
                (rule.severity for rule in assessment.triggered_rules),
                key=lambda item: {"info": 0, "medium": 1, "high": 2, "critical": 3}[item.value],
            )
            return ExitDecision(
                symbol=position.symbol,
                action=DecisionAction.CLOSE,
                severity=severity,
                reasons=tuple(reasons),
                assessment=assessment,
                manual_close_instruction=self._close_instruction(position),
            )

        if assessment.warnings:
            return ExitDecision(
                symbol=position.symbol,
                action=DecisionAction.REVIEW,
                severity=DecisionSeverity.HIGH,
                reasons=tuple(reasons),
                assessment=assessment,
            )

        return ExitDecision(
            symbol=position.symbol,
            action=DecisionAction.HOLD,
            severity=DecisionSeverity.INFO,
            reasons=("no_exit_condition_met",),
            assessment=assessment,
        )

    @staticmethod
    def _close_instruction(position: TrackedPosition) -> dict[str, object]:
        return {
            "mode": "manual_review_required",
            "category": position.category,
            "symbol": position.symbol,
            "side": "sell" if position.side is PositionSide.LONG else "buy",
            "quantity": position.quantity,
            "reduce_only": True,
            "close_on_trigger": position.category in {"linear", "inverse"},
            "reason": "exit decision engine requested a human-reviewed close",
        }
