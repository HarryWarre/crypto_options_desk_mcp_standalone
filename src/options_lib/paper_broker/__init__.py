"""Paper Trading Broker for Bybit Options.

Provides virtual account simulation, realistic matching engine using live
orderbook / ticker data, Bybit Portfolio Margin approximation, and SQLite
persistence.
"""

from .account import PaperAccount, PaperPosition, PaperTrade
from .deribit_adapter import DeribitBrokerAdapter
from .margin_calculator import MarginCalculator, MarginSummary
from .matching_engine import MatchingEngine, OrderType, PaperOrder, PaperOrderResult
from .storage import PaperStorage

__all__ = [
    "PaperAccount",
    "PaperPosition",
    "PaperTrade",
    "MatchingEngine",
    "PaperOrder",
    "PaperOrderResult",
    "OrderType",
    "MarginCalculator",
    "MarginSummary",
    "PaperStorage",
    "DeribitBrokerAdapter",
]

