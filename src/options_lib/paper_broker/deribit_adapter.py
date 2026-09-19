"""Deribit Testnet Broker Adapter for Strategy Engines.

Bridges PaperAccount and strategy bots (Iron Condor, Calendar Spread, etc.)
with real Deribit Testnet execution.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from ..deribit_client import (
    DeribitClient,
    DeribitClientError,
    DeribitOrder,
    DeribitOrderState,
)
from .account import PaperAccount, PaperPosition, PaperTrade
from .matching_engine import OrderType, PaperOrder, PaperOrderResult

logger = logging.getLogger(__name__)


def normalize_deribit_instrument(symbol: str) -> str:
    """Normalize symbol to Deribit instrument format (e.g. BTC-26SEP26-80000-C)."""
    clean = re.sub(r"-USDT$", "", symbol, flags=re.IGNORECASE)
    clean = re.sub(r"-USDC$", "", clean, flags=re.IGNORECASE)
    return clean


class DeribitBrokerAdapter:
    """Adapter facilitating direct Deribit Testnet execution for paper bots."""

    def __init__(
        self,
        client: DeribitClient | None = None,
        testnet: bool = True,
    ) -> None:
        self.client = client or DeribitClient(testnet=testnet)

    def execute_order(
        self,
        order: PaperOrder,
        spot: float = 0.0,
    ) -> PaperOrderResult:
        """Execute a PaperOrder directly on Deribit Testnet."""
        instrument = normalize_deribit_instrument(order.symbol)
        side_lower = order.side.lower()
        is_limit = order.order_type in (OrderType.LIMIT, "Limit", "limit")
        order_type_str = "limit" if is_limit else "market"

        # Deribit options require amount to be a multiple of min_trade_amount (0.1 for BTC, 1.0 for ETH)
        if instrument.startswith("BTC-"):
            amount = max(0.1, round(order.qty * 10) / 10)
        elif instrument.startswith("ETH-"):
            amount = max(1.0, round(order.qty))
        else:
            amount = order.qty

        try:
            if side_lower == "buy":
                deribit_order = self.client.buy(
                    instrument_name=instrument,
                    amount=amount,
                    order_type=order_type_str,
                    price=order.price if is_limit else None,
                    label=order.strategy_id or "bot_order",
                )
            elif side_lower == "sell":
                deribit_order = self.client.sell(
                    instrument_name=instrument,
                    amount=amount,
                    order_type=order_type_str,
                    price=order.price if is_limit else None,
                    label=order.strategy_id or "bot_order",
                )
            else:
                return PaperOrderResult(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    status="Rejected",
                    message=f"Invalid order side: {order.side}",
                )

            # Map to PaperOrderResult
            status = "Filled" if deribit_order.is_filled else "Pending"
            filled_qty = deribit_order.filled_amount
            filled_price = deribit_order.average_price or (deribit_order.price or 0.0)

            return PaperOrderResult(
                order_id=deribit_order.order_id,
                symbol=order.symbol,
                side=order.side,
                status=status,
                filled_qty=filled_qty,
                filled_price=filled_price,
                fee=deribit_order.fee,
                timestamp=datetime.now(UTC).isoformat(),
                message=f"Deribit order state: {deribit_order.order_state}",
            )

        except DeribitClientError as e:
            logger.error("Deribit order execution error: %s", e)
            return PaperOrderResult(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                status="Rejected",
                message=str(e),
            )

    def sync_account(
        self,
        account: PaperAccount,
        currency: str = "BTC",
    ) -> None:
        """Synchronize open positions and balance from Deribit into PaperAccount."""
        try:
            # Sync summary & balance
            summary = self.client.get_account_summary(currency=currency)
            account.cash_balance = summary.balance

            # Sync open positions
            positions = self.client.get_positions(currency=currency, kind="option")
            account.positions.clear()

            for pos in positions:
                if pos.size <= 0:
                    continue
                side = "Buy" if pos.direction == "buy" else "Sell"
                p_pos = PaperPosition(
                    symbol=pos.instrument_name,
                    side=side,
                    qty=pos.size,
                    entry_price=pos.average_price,
                    current_mark_price=pos.mark_price,
                    unrealized_pnl=pos.floating_profit_loss,
                    realized_pnl=pos.realized_profit_loss,
                )
                account.positions[pos.instrument_name] = p_pos

            logger.info(
                "Synced account %s with Deribit: balance=%f, positions=%d",
                account.account_id,
                account.cash_balance,
                len(account.positions),
            )
        except Exception as e:
            logger.error("Failed to sync account with Deribit: %s", e)

