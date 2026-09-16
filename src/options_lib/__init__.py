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
    OpportunityLeg,
    RejectedCandidate,
    ScanRequest,
    ScanResult,
    scan_opportunities,
)
from .payoff_metrics import (
    PayoffAssumptions,
    PayoffMetrics,
    PayoffPoint,
    calculate_payoff_metrics,
    estimate_payoff_metrics,
)
from .portfolio_greeks import (
    OptionPositionGreeks,
    OptionsPortfolioGreeks,
    compute_option_greeks,
    compute_options_portfolio_greeks,
)
from .pricing import OptionMetrics, OptionSpec, ProfessionalOptionsEngine
from .scenario_engine import (
    ExecutionAssumptions,
    MarketScenario,
    OptionLeg,
    ScenarioGreeks,
    ScenarioReport,
    ScenarioResult,
    ScenarioSet,
    ScenarioValidationError,
    StrategyDefinition,
    evaluate_scenarios,
)
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
    'ExecutionAssumptions',
    'ExtrapolationError',
    'HistoricalTradeSample',
    'InsufficientDataError',
    'MarketScenario',
    'Opportunity',
    'OpportunityLeg',
    'OptionLeg',
    'OptionMetrics',
    'OptionPositionGreeks',
    'OptionSpec',
    'OptionsPortfolioGreeks',
    'PayoffAssumptions',
    'PayoffMetrics',
    'PayoffPoint',
    'ProfessionalOptionsEngine',
    'RejectedCandidate',
    'ScanRequest',
    'ScanResult',
    'ScenarioGreeks',
    'ScenarioReport',
    'ScenarioResult',
    'ScenarioSet',
    'ScenarioValidationError',
    'StrategyAnalyzer',
    'StrategyClassifier',
    'StrategyDefinition',
    'StrategyMetrics',
    'StrategyType',
    'SurfaceConfig',
    'ValidationConfig',
    'VolatilityObservation',
    'VolatilitySurface',
    'VolatilitySurfaceResult',
    'build_volatility_surface',
    'calculate_payoff_metrics',
    'compute_option_greeks',
    'compute_options_portfolio_greeks',
    'estimate_payoff_metrics',
    'evaluate_scenarios',
    'parse_bybit_option_symbol',
    'scan_opportunities',
    'validate_backtest',
]
