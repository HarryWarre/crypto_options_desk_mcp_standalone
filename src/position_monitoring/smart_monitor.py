"""Smart Position Monitor — evaluates notebook positions and generates action recommendations.

Provides Vietnamese-language recommendations:
- CHỐT LỜI (TAKE_PROFIT): When profit reaches target (e.g. 50%+), or credit captures majority value.
- BỎ / CẮT LỖ (CUT_LOSS): When loss reaches stop threshold (e.g. -50%+) or risk limits exceeded.
- GIỮ (HOLD): Position within normal risk parameters and thesis remains intact.
- XEM XÉT (REVIEW): Close to expiry, high gamma, or significant Greek drift.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from options_lib.pricing.fair_value import FairValueRequest, price_fair_value
from position_monitoring.notebook import TrackedNotebookPosition


@dataclass
class SmartMonitorDecision:
    """Actionable recommendation for a tracked position."""

    action: str  # "TAKE_PROFIT" | "CUT_LOSS" | "HOLD" | "REVIEW"
    action_vn: str  # "CHỐT LỜI" | "BỎ / CẮT LỖ" | "GIỮ" | "XEM XÉT"
    headline: str
    reason: str
    urgency: str  # "low" | "medium" | "high"
    current_pnl: float
    pnl_pct: float
    entry_cost: float
    current_value: float
    days_to_expiry: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SmartPositionEvaluation:
    """Complete evaluation report for a tracked position."""

    position_id: str
    asset: str
    strategy_type: str
    status: str
    entry_spot: float
    current_spot: float
    spot_change_pct: float
    target_profit_pct: float
    stop_loss_pct: float
    entry_cost: float
    current_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    greeks: dict[str, float]
    decision: SmartMonitorDecision
    legs_status: list[dict[str, Any]]
    evaluated_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.to_dict()
        return d


class SmartPositionMonitor:
    """Evaluates tracked positions against market data and gives smart exit advice."""

    def __init__(self, risk_free_rate: float = 0.05) -> None:
        self.risk_free_rate = risk_free_rate

    def evaluate_position(
        self,
        position: TrackedNotebookPosition,
        current_spot: float | None = None,
        contracts_map: dict[str, dict[str, Any]] | None = None,
        valuation_time: datetime | None = None,
    ) -> SmartPositionEvaluation:
        """Evaluate a single notebook position and produce recommendations.

        Parameters
        ----------
        position:
            The tracked notebook position.
        current_spot:
            Current spot price of the underlying. If None, uses position.entry_spot.
        contracts_map:
            Optional map of symbol -> contract data (bid, ask, mark_price, iv).
        valuation_time:
            Valuation timestamp (defaults to UTC now).
        """
        now = valuation_time or datetime.now(UTC)
        contracts_map = contracts_map or {}
        spot = current_spot if (current_spot is not None and current_spot > 0) else position.entry_spot
        if spot <= 0:
            spot = 1.0

        spot_change_pct = ((spot - position.entry_spot) / position.entry_spot * 100.0) if position.entry_spot > 0 else 0.0

        # Calculate entry cost & current value across legs
        entry_cost = 0.0
        current_value = 0.0
        legs_status: list[dict[str, Any]] = []

        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0

        min_days_to_expiry = 999.0

        for leg in position.legs:
            symbol = leg.get("symbol", "")
            option_type = leg.get("option_type", "call")
            strike = float(leg.get("strike", spot))
            pos_sign = int(leg.get("position", 1))  # +1 long, -1 short
            qty = int(leg.get("quantity", 1))

            entry_price = float(leg.get("entry_price") or leg.get("mid_price") or 0.0)
            entry_leg_cost = entry_price * pos_sign * qty
            entry_cost += entry_leg_cost

            # Parse expiry
            expiry_raw = leg.get("expiry", "")
            try:
                if isinstance(expiry_raw, datetime):
                    expiry_dt = expiry_raw
                elif "T" in str(expiry_raw):
                    expiry_dt = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
                else:
                    expiry_dt = datetime.fromisoformat(f"{expiry_raw}T08:00:00+00:00")
            except Exception:
                expiry_dt = now

            dte = max((expiry_dt - now).total_seconds() / 86400.0, 0.0)
            if dte < min_days_to_expiry:
                min_days_to_expiry = dte

            # Current price: check contracts_map first, fallback to fair_value pricing
            cur_price: float = 0.0
            d = g = t = v = 0.0

            contract_quote = contracts_map.get(symbol)
            if contract_quote:
                bid = float(contract_quote.get("bid", 0) or 0)
                ask = float(contract_quote.get("ask", 0) or 0)
                cur_price = (bid + ask) / 2.0 if (bid + ask) > 0 else float(contract_quote.get("mark_price", 0) or 0)
                iv = float(contract_quote.get("iv", 0.80) or 0.80)
            else:
                iv = float(leg.get("iv", 0.80) or 0.80)
                # Compute current theoretical price
                try:
                    res = price_fair_value(
                        FairValueRequest(
                            option_type=option_type,
                            strike=strike,
                            expiry=expiry_dt,
                            valuation_time=now,
                            iv=iv,
                            risk_free_rate=self.risk_free_rate,
                            spot=spot,
                        )
                    )
                    cur_price = res.fair_price
                    d = res.delta * pos_sign * qty
                    g = res.gamma * abs(pos_sign) * qty
                    t = res.theta * pos_sign * qty
                    v = res.vega * pos_sign * qty
                except Exception:
                    # Intrinsic value fallback
                    if option_type == "call":
                        cur_price = max(spot - strike, 0.0)
                    else:
                        cur_price = max(strike - spot, 0.0)

            total_delta += d
            total_gamma += g
            total_theta += t
            total_vega += v

            cur_leg_value = cur_price * pos_sign * qty
            current_value += cur_leg_value

            legs_status.append({
                "symbol": symbol,
                "option_type": option_type,
                "strike": strike,
                "position": pos_sign,
                "quantity": qty,
                "entry_price": entry_price,
                "current_price": round(cur_price, 4),
                "unrealized_pnl": round(cur_leg_value - entry_leg_cost, 4),
                "days_to_expiry": round(dte, 1),
            })

        # Calculate unrealized PnL
        unrealized_pnl = current_value - entry_cost

        # Determine PnL% based on capital at risk:
        # If debit trade (entry_cost > 0), capital at risk is entry_cost.
        # If credit trade (entry_cost < 0), max profit is |entry_cost|, capital at risk is margin/spread width.
        capital_at_risk = abs(entry_cost) if abs(entry_cost) > 1e-6 else spot * 0.10
        pnl_pct = (unrealized_pnl / capital_at_risk) * 100.0

        # Decision rule engine
        target_tp = position.target_profit_pct
        target_sl = position.stop_loss_pct

        action: str
        action_vn: str
        headline: str
        reason: str
        urgency: str

        if pnl_pct >= target_tp:
            action = "TAKE_PROFIT"
            action_vn = "CHỐT LỜI"
            headline = f"Đạt mục tiêu lợi nhuận +{pnl_pct:.1f}% (mục tiêu {target_tp:.0f}%)"
            reason = (
                f"Vị thế đã đạt lợi nhuận {unrealized_pnl:+.2f} USD (+{pnl_pct:.1f}%). "
                f"Khuyến nghị chốt lời để bảo toàn lợi nhuận theo kế hoạch ban đầu."
            )
            urgency = "high"
        elif pnl_pct <= -target_sl:
            action = "CUT_LOSS"
            action_vn = "BỎ / CẮT LỖ"
            headline = f"Chạm ngưỡng cắt lỗ {pnl_pct:.1f}% (ngưỡng -{target_sl:.0f}%)"
            reason = (
                f"Vị thế đang lỗ {unrealized_pnl:.2f} USD ({pnl_pct:.1f}%). "
                f"Đã chạm ngưỡng quản trị rủi ro tối đa. Khuyến nghị cắt lỗ/đóng vị thế ngay."
            )
            urgency = "high"
        elif min_days_to_expiry <= 1.0 and position.status == "open":
            action = "REVIEW"
            action_vn = "XEM XÉT"
            headline = f"Sắp đáo hạn ({min_days_to_expiry:.1f} ngày) - Rủi ro Gamma tăng cao"
            reason = (
                f"Thời gian đáo hạn chỉ còn {min_days_to_expiry:.1f} ngày. "
                f"Rủi ro gán quyền (pin risk/gamma) rất cao. Nên cân nhắc đóng hoặc rollover."
            )
            urgency = "medium"
        elif pnl_pct >= target_tp * 0.75:
            action = "HOLD"
            action_vn = "GIỮ"
            headline = f"Lợi nhuận đang tốt (+{pnl_pct:.1f}%), tiến gần mục tiêu"
            reason = (
                f"Vị thế đang có lãi +{pnl_pct:.1f}%, sắp chạm mục tiêu {target_tp:.0f}%. "
                f"Tiếp tục giữ nhưng có thể đặt trailing stop để bảo vệ thành quả."
            )
            urgency = "low"
        else:
            action = "HOLD"
            action_vn = "GIỮ"
            headline = "Vị thế an toàn - Tiếp tục theo dõi"
            reason = (
                f"Lợi nhuận hiện tại {pnl_pct:+.1f}%, nằm trong vùng biến động an toàn. "
                f"Thời gian đáo hạn còn {min_days_to_expiry:.1f} ngày. Khuyến nghị tiếp tục nắm giữ."
            )
            urgency = "low"

        decision = SmartMonitorDecision(
            action=action,
            action_vn=action_vn,
            headline=headline,
            reason=reason,
            urgency=urgency,
            current_pnl=round(unrealized_pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            entry_cost=round(entry_cost, 4),
            current_value=round(current_value, 4),
            days_to_expiry=round(min_days_to_expiry, 1),
        )

        return SmartPositionEvaluation(
            position_id=position.id,
            asset=position.asset,
            strategy_type=position.strategy_type,
            status=position.status,
            entry_spot=position.entry_spot,
            current_spot=round(spot, 2),
            spot_change_pct=round(spot_change_pct, 2),
            target_profit_pct=target_tp,
            stop_loss_pct=target_sl,
            entry_cost=round(entry_cost, 4),
            current_value=round(current_value, 4),
            unrealized_pnl=round(unrealized_pnl, 4),
            unrealized_pnl_pct=round(pnl_pct, 2),
            greeks={
                "delta": round(total_delta, 4),
                "gamma": round(total_gamma, 4),
                "theta": round(total_theta, 4),
                "vega": round(total_vega, 4),
            },
            decision=decision,
            legs_status=legs_status,
            evaluated_at=now.isoformat(),
        )

    def evaluate_all(
        self,
        positions: list[TrackedNotebookPosition],
        spot_map: dict[str, float] | None = None,
        contracts_map: dict[str, dict[str, Any]] | None = None,
        valuation_time: datetime | None = None,
    ) -> list[SmartPositionEvaluation]:
        """Evaluate a list of tracked positions."""
        spot_map = spot_map or {}
        contracts_map = contracts_map or {}
        results: list[SmartPositionEvaluation] = []
        for pos in positions:
            spot = spot_map.get(pos.asset)
            evaluation = self.evaluate_position(
                pos,
                current_spot=spot,
                contracts_map=contracts_map,
                valuation_time=valuation_time,
            )
            results.append(evaluation)
        return results
