"""Provenance metadata for strategy-head decisions and research signals."""

from .models import (
    PROVENANCE_KEY,
    SIGNAL_DISCLAIMER,
    SIGNAL_PROVENANCE_KEY,
    DecisionAction,
    DecisionSource,
    DecisionType,
    SignalProvenance,
    StrategyRanking,
    attach_provenance,
    get_signal_provenance,
)

__all__ = [
    "PROVENANCE_KEY",
    "SIGNAL_DISCLAIMER",
    "SIGNAL_PROVENANCE_KEY",
    "DecisionAction",
    "DecisionSource",
    "DecisionType",
    "SignalProvenance",
    "StrategyRanking",
    "attach_provenance",
    "get_signal_provenance",
]
