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
from options_lib.strategy.iron_condor_bot import IronCondorBot, IronCondorConfig

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
        }

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
        """Execute a single evaluation cycle and broadcast state."""
        self.last_cycle_time = datetime.now(UTC).isoformat()
        try:
            status = await self.bot.run_cycle()
            self.last_cycle_status = status
            self.last_action_message = f"Cycle finished with status: {status}"
        except Exception as e:
            logger.exception("Error executing bot cycle: %s", e)
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
