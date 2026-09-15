"""
options-lib - Crypto options pricing, flow analysis, and strategy classification.
"""

from .ev_validation import (
    BacktestMetrics,
    BacktestReport,
    BacktestStatus,
    CostSensitivityPoint,
    HistoricalTradeSample,
    ValidationConfig,
    validate_backtest,
)
from .opportunity_scanner import (
    AssetScanFailure,
    Opportunity,
    RejectedCandidate,
    ScanRequest,
    ScanResult,
    scan_opportunities,
)
from .portfolio_greeks import (
    OptionPositionGreeks,
    OptionsPortfolioGreeks,
    compute_option_greeks,
    compute_options_portfolio_greeks,
)
from .pricing import OptionMetrics, OptionSpec, ProfessionalOptionsEngine
from .strategy import StrategyAnalyzer, StrategyClassifier, StrategyMetrics, StrategyType
from .symbol_parser import parse_bybit_option_symbol
from .volatility_surface import (
    ExtrapolationError,
    InsufficientDataError,
    SurfaceConfig,
    VolatilityObservation,
    VolatilitySurface,
    VolatilitySurfaceResult,
    build_volatility_surface,
)

__all__ = [
    'AssetScanFailure',
    'BacktestMetrics',
    'BacktestReport',
    'BacktestStatus',
    'CostSensitivityPoint',
    'ExtrapolationError',
    'HistoricalTradeSample',
    'InsufficientDataError',
    'Opportunity',
    'OptionMetrics',
    'OptionPositionGreeks',
    'OptionSpec',
    'OptionsPortfolioGreeks',
    'ProfessionalOptionsEngine',
    'RejectedCandidate',
    'ScanRequest',
    'ScanResult',
    'StrategyAnalyzer',
    'StrategyClassifier',
    'StrategyMetrics',
    'StrategyType',
    'SurfaceConfig',
    'ValidationConfig',
    'VolatilityObservation',
    'VolatilitySurface',
    'VolatilitySurfaceResult',
    'build_volatility_surface',
    'compute_option_greeks',
    'compute_options_portfolio_greeks',
    'parse_bybit_option_symbol',
    'scan_opportunities',
    'validate_backtest',
]
