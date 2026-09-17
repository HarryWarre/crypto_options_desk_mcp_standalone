from datetime import UTC, datetime

import pytest

from bybit_api.models import Position
from mcp_trading.orchestrator import MCPOrchestrator
from mcp_trading.server import ExitPolicyParams, MonitorPositionsParams
from position_monitoring import JsonlSnapshotHistory

AS_OF = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class FakeMonitoringApi:
    def __init__(self, *, private_access: bool = True) -> None:
        self.private_access = private_access

    def has_private_access(self) -> bool:
        return self.private_access

    async def get_positions(self, category: str, **kwargs):
        if category != "option":
            return []
        return [
            Position(
                symbol="BTC-25SEP26-100000-C",
                side="Buy",
                size=1,
                avg_price=100,
                mark_price=110,
                unrealised_pnl=10,
                realised_pnl=0,
                category="option",
                exchange="bybit",
            )
        ]

    async def get_open_orders(self, category: str, **kwargs):
        return []

    async def get_order_history(self, category: str, **kwargs):
        return []


@pytest.mark.asyncio
async def test_orchestrator_returns_manual_close_decision_and_never_execution_permission() -> None:
    orchestrator = MCPOrchestrator()
    orchestrator.api = FakeMonitoringApi()

    result = await orchestrator.monitor_positions(
        "BTC",
        "option",
        [ExitPolicyParams(symbol="BTC-25SEP26-100000-C", take_profit_price=105).to_domain()],
        persist=False,
    )

    assert result["success"] is True
    assert result["execution_allowed"] is False
    assert result["requires_human_confirmation"] is True
    assert result["data"]["decisions"][0]["action"] == "close"
    assert result["data"]["decisions"][0]["manual_close_instruction"]["side"] == "sell"


@pytest.mark.asyncio
async def test_missing_private_credentials_is_structured_and_read_only() -> None:
    orchestrator = MCPOrchestrator()
    orchestrator.api = FakeMonitoringApi(private_access=False)

    result = await orchestrator.monitor_positions("BTC", "option", [])

    assert result["success"] is False
    assert result["context"] == "position_monitoring"
    assert "BYBIT_API_KEY" in result["hint"]


@pytest.mark.asyncio
async def test_monitoring_persists_and_exposes_snapshot_diff(tmp_path) -> None:
    orchestrator = MCPOrchestrator()
    orchestrator.api = FakeMonitoringApi()
    orchestrator.position_snapshot_history = JsonlSnapshotHistory(tmp_path / "history.jsonl")
    policies = [ExitPolicyParams(symbol="BTC-25SEP26-100000-C", take_profit_price=105).to_domain()]

    first = await orchestrator.monitor_positions("BTC", "option", policies, persist=True)
    second = await orchestrator.monitor_positions("BTC", "option", policies, persist=True)
    history = orchestrator.get_position_monitoring_history(limit=10)

    assert first["persistence"]["status"] == "saved"
    assert (
        second["persistence"]["diff"]["previous_snapshot_id"] == first["persistence"]["snapshot_id"]
    )
    assert history["success"] is True
    assert len(history["data"]["records"]) == 2
    assert (
        history["data"]["latest_diff"]["current_snapshot_id"]
        == second["persistence"]["snapshot_id"]
    )


def test_policy_model_requires_risk_budget_for_percentage_loss() -> None:
    policy = ExitPolicyParams(
        symbol="BTC-25SEP26-100000-C",
        max_loss_pct=0.2,
    )

    with pytest.raises(ValueError, match="risk_budget"):
        policy.to_domain()


def test_monitor_request_rejects_unknown_fields_and_invalid_category() -> None:
    with pytest.raises(ValueError):
        MonitorPositionsParams(position_type="unknown")

    with pytest.raises(ValueError):
        MonitorPositionsParams.model_validate({"base_coin": "BTC", "unexpected": True})
