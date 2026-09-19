"""Bot Manager Service for Live Desk.

Provides in-process orchestration of the IronCondorBot:
- Starts and stops background evaluation loop.
- Manages WebSocket subscriptions for real-time portfolio streaming.
- Handles manual triggers (Run Cycle, Emergency Close All, Reset Account).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from options_lib.paper_broker.deribit_adapter import DeribitBrokerAdapter
from options_lib.paper_broker.equity_history import EquityHistoryStore
from options_lib.research.market_regime import MarketRegimeAgent
from options_lib.risk.portfolio_risk_engine import PortfolioRiskEngine
from options_lib.strategy.iron_condor_bot import IronCondorBot, IronCondorConfig
from options_lib.swarm.trader_pool import TraderPool
from options_lib.verdict.verdict_agent import VerdictAgent

logger = logging.getLogger(__name__)

_GLOBAL_BOT_MANAGER: BotManager | None = None


class BotManager:
    """Orchestrates automated options bots and streams status to UI clients."""

    def __init__(
        self,
        asset: str = "BTC",
        paper_mode: bool = True,
        initial_capital: float = 10000.0,
        interval_seconds: int = 60,
    ) -> None:
        self.asset = asset
        self.paper_mode = paper_mode
        self.interval_seconds = interval_seconds
        self.is_running = False
        self._background_task: asyncio.Task[None] | None = None
        self._subscribers: set[WebSocket] = set()

        self.last_cycle_time: str | None = None
        self.last_cycle_status: str = "IDLE"
        self.last_action_message: str = "Bot initialized"

        # Instantiate bot
        self.config = IronCondorConfig(
            asset=asset,
            paper_mode=paper_mode,
            initial_capital=initial_capital,
            poll_interval_seconds=interval_seconds,
        )
        self.bot = IronCondorBot(self.config)

        # Multi-Agent Swarm Components
        self.research_agent = MarketRegimeAgent()
        self.trader_pool = TraderPool()
        self.risk_engine = PortfolioRiskEngine()
        self.verdict_agent = VerdictAgent()
        self.equity_history = EquityHistoryStore(db_path=self.config.db_path)
        self.deribit_adapter = DeribitBrokerAdapter(testnet=True)
        self.last_swarm_result: dict[str, Any] | None = None

    def get_status(self) -> dict[str, Any]:
        """Construct a comprehensive state snapshot for UI widgets."""
        acc = self.bot.paper_account
        calc = self.bot.margin_calculator
        margin_sum = calc.evaluate_portfolio(acc.positions, acc.equity, 0.0)

        # Active condor details
        active_condor = None
        if self.bot._active_condor_id and self.bot._active_legs:
            unrealized = sum(
                acc.positions[l.symbol].unrealized_pnl
                for l in self.bot._active_legs
                if l.symbol in acc.positions
            )
            active_condor = {
                "condor_id": self.bot._active_condor_id,
                "entry_credit": round(self.bot._entry_credit, 4),
                "unrealized_pnl": round(unrealized, 4),
                "target_profit_50": round(
                    self.bot._entry_credit * self.config.target_profit_pct, 4
                ),
                "stop_loss_limit": round(
                    -self.bot._entry_credit * self.config.max_loss_multiplier, 4
                ),
                "legs": [l.to_dict() for l in self.bot._active_legs],
            }

        return {
            "type": "bot_status",
            "timestamp": datetime.now(UTC).isoformat(),
            "control": {
                "asset": self.asset,
                "paper_mode": self.paper_mode,
                "is_running": self.is_running,
                "interval_seconds": self.interval_seconds,
                "last_cycle_time": self.last_cycle_time,
                "last_cycle_status": self.last_cycle_status,
                "last_action_message": self.last_action_message,
            },
            "portfolio": {
                "initial_capital": acc.initial_capital,
                "cash_balance": round(acc.cash_balance, 2),
                "equity": round(acc.equity, 2),
                "total_unrealized_pnl": round(acc.total_unrealized_pnl, 2),
                "total_compounded_profit": round(
                    self.bot._total_compounded_profit, 2
                ),
                "position_count": len(acc.positions),
            },
            "margin": margin_sum.to_dict(),
            "active_condor": active_condor,
            "open_positions": [p.to_dict() for p in acc.positions.values()],
            "recent_trades": [
                t.to_dict() for t in reversed(acc.trade_history[-10:])
            ],
            "deribit_telemetry": self._get_deribit_telemetry(acc, margin_sum),
            "swarm": self.last_swarm_result,
        }

    def _get_deribit_telemetry(self, acc: Any, margin_sum: Any) -> dict[str, Any]:
        """Fetch live Deribit telemetry or generate synchronized fallback."""
        default_spots = {"BTC": 60000.0, "ETH": 3000.0, "SOL": 150.0}
        spot = default_spots.get(self.asset.upper(), 50000.0)
        telemetry: dict[str, Any] = {
            "connected": False,
            "currency": self.asset,
            "equity_usd": round(acc.equity, 2),
            "equity_crypto": round(acc.equity / spot, 4),
            "balance_crypto": round(acc.cash_balance / spot, 4),
            "margin_balance_usd": round(acc.equity, 2),
            "initial_margin_usd": round(margin_sum.initial_margin, 2),
            "maintenance_margin_usd": round(margin_sum.maintenance_margin, 2),
            "margin_utilization_pct": round(margin_sum.margin_utilization_pct, 2),
            "open_orders_count": 0,
            "open_positions_count": len(acc.positions),
            "portfolio_delta": round(
                sum(p.qty * (1 if p.side == "Buy" else -1) for p in acc.positions.values()), 4
            ),
        }
        try:
            summary = self.deribit_adapter.client.get_account_summary(currency=self.asset)
            if summary:
                telemetry["connected"] = True
                telemetry["equity_crypto"] = round(summary.equity, 4)
                telemetry["equity_usd"] = round(summary.equity * spot, 2)
                telemetry["balance_crypto"] = round(summary.balance, 4)
                telemetry["initial_margin_usd"] = round(summary.initial_margin * spot, 2)
                telemetry["maintenance_margin_usd"] = round(summary.maintenance_margin * spot, 2)
                telemetry["margin_utilization_pct"] = round(summary.margin_utilization_pct, 2)
        except Exception:
            pass
        return telemetry

    async def register_subscriber(self, ws: WebSocket) -> None:
        """Add WebSocket subscriber and send initial snapshot."""
        self._subscribers.add(ws)
        try:
            await ws.send_json(self.get_status())
        except Exception:
            self._subscribers.discard(ws)

    def unregister_subscriber(self, ws: WebSocket) -> None:
        """Remove WebSocket subscriber."""
        self._subscribers.discard(ws)

    async def broadcast(self, data: dict[str, Any] | None = None) -> None:
        """Broadcast state payload to all active WebSocket clients."""
        payload = data or self.get_status()
        dead_clients = set()
        for ws in self._subscribers:
            try:
                await ws.send_json(payload)
            except Exception:
                dead_clients.add(ws)
        self._subscribers.difference_update(dead_clients)

    async def run_cycle(self) -> str:
        """Execute a single multi-agent swarm evaluation cycle and broadcast state."""
        self.last_cycle_time = datetime.now(UTC).isoformat()
        try:
            # 1. Fetch live market contracts & spot
            try:
                contracts, spot = await self.bot.fetch_live_data()
            except Exception as e:
                logger.warning("Could not fetch live data: %s", e)
                contracts, spot = [], 0.0

            # 2. Research Agent (Market Regime)
            regime_report = None
            if contracts and spot > 0:
                try:
                    regime_report = self.research_agent.analyze(
                        asset=self.asset,
                        contracts=contracts,
                        historical_volatility=None,
                        spot_price=spot,
                    )
                except Exception as e:
                    logger.warning("Research agent analysis error: %s", e)

            # 3. Trader Pool (Multi-Strategy Candidate Generation)
            candidates = []
            if regime_report and contracts:
                try:
                    candidates = self.trader_pool.generate_candidates(
                        report=regime_report,
                        contracts=contracts,
                        spot_price=spot,
                    )
                except Exception as e:
                    logger.warning("Trader pool candidate generation error: %s", e)

            # 4. Risk Engine Assessment & Verdict Agent Execution
            last_verdict = None
            if candidates:
                best_cand = candidates[0]
                acc = self.bot.paper_account
                calc = self.bot.margin_calculator
                margin_sum = calc.evaluate_portfolio(acc.positions, acc.equity, spot)
                risk_res = self.risk_engine.evaluate_candidate(
                    candidate=best_cand,
                    current_equity=acc.equity,
                    current_margin_used=margin_sum.initial_margin,
                    current_open_positions_count=len(acc.positions),
                )
                last_verdict = self.verdict_agent.process_candidate(
                    candidate=best_cand,
                    risk_res=risk_res,
                    broker=self.deribit_adapter,
                )

            # 5. Position Management & Lifecycle
            status = await self.bot.run_cycle()
            self.last_cycle_status = status
            self.last_action_message = f"Cycle finished with status: {status}"

            # 6. Record equity snapshot for 1D/1W/1M charts
            acc = self.bot.paper_account
            calc = self.bot.margin_calculator
            margin_sum = calc.evaluate_portfolio(acc.positions, acc.equity, spot)
            net_delta = sum(p.qty * (1 if p.side == "Buy" else -1) for p in acc.positions.values())
            self.equity_history.record_snapshot(
                currency=self.asset,
                equity_usd=acc.equity,
                balance_crypto=acc.cash_balance / max(1.0, spot) if spot > 0 else 0.0,
                margin_used=margin_sum.initial_margin,
                margin_utilization_pct=margin_sum.margin_utilization_pct,
                net_delta=net_delta,
            )

            # 7. Store Swarm telemetry for UI
            self.last_swarm_result = {
                "regime": regime_report.to_dict() if regime_report else None,
                "candidates_count": len(candidates),
                "candidates": [c.to_dict() for c in candidates[:5]],
                "last_verdict": last_verdict.to_dict() if last_verdict else None,
            }

        except Exception as e:
            logger.exception("Error executing bot swarm cycle: %s", e)
            self.last_cycle_status = "ERROR"
            self.last_action_message = f"Error: {e}"

        await self.broadcast()
        return self.last_cycle_status

    async def _loop(self) -> None:
        """Internal background loop running periodic cycles."""
        logger.info("BotManager background loop started (interval: %ss)", self.interval_seconds)
        while self.is_running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error("Unexpected error in bot loop: %s", e)

            # Sleep interval with interruptibility
            for _ in range(self.interval_seconds):
                if not self.is_running:
                    break
                await asyncio.sleep(1)

        logger.info("BotManager background loop stopped")

    async def start(self, interval: int | None = None) -> dict[str, Any]:
        """Start the automated bot daemon."""
        if interval:
            self.interval_seconds = max(10, interval)
            self.config.poll_interval_seconds = self.interval_seconds

        if self.is_running:
            return {"status": "already_running", "message": "Bot is already running"}

        self.is_running = True
        self.last_action_message = "Bot started"
        self._background_task = asyncio.create_task(self._loop())
        await self.broadcast()
        return {"status": "started", "message": "Bot started successfully"}

    async def stop(self) -> dict[str, Any]:
        """Stop the automated bot daemon."""
        if not self.is_running:
            return {"status": "not_running", "message": "Bot is not running"}

        self.is_running = False
        self.last_action_message = "Bot stopped"
        if self._background_task:
            self._background_task.cancel()
            self._background_task = None

        await self.broadcast()
        return {"status": "stopped", "message": "Bot stopped successfully"}

    async def emergency_close_all(self) -> dict[str, Any]:
        """Liquidate all open positions in paper account immediately."""
        try:
            contracts, spot = await self.bot.fetch_live_data()
        except Exception:
            contracts, spot = [], 0.0

        pnl = self.bot.execute_close_condor(
            reason="EMERGENCY_USER_CLOSE",
            spot=spot,
            current_chain=contracts,
        )
        self.last_action_message = f"Emergency closed all positions. Realized PnL: ${pnl:,.2f}"
        await self.broadcast()
        return {
            "status": "closed",
            "message": self.last_action_message,
            "realized_pnl": pnl,
        }

    async def reset_account(self, capital: float = 10000.0) -> dict[str, Any]:
        """Reset virtual paper trading balance and wipe open positions."""
        acc = self.bot.paper_account
        acc.initial_capital = float(capital)
        acc.cash_balance = float(capital)
        acc.positions.clear()
        acc.trade_history.clear()
        self.bot._active_condor_id = None
        self.bot._active_legs.clear()
        self.bot._entry_credit = 0.0
        self.bot._total_compounded_profit = 0.0

        # Save to database
        self.bot.storage.save_account(acc)
        self.last_action_message = f"Paper account reset to ${capital:,.2f}"
        await self.broadcast()
        return {
            "status": "reset",
            "message": self.last_action_message,
            "capital": capital,
        }


def get_bot_manager(asset: str = "BTC") -> BotManager:
    """Retrieve or create the singleton BotManager instance."""
    global _GLOBAL_BOT_MANAGER
    if _GLOBAL_BOT_MANAGER is None:
        _GLOBAL_BOT_MANAGER = BotManager(asset=asset)
    return _GLOBAL_BOT_MANAGER
