"""Professional options pricing and Greeks calculation using py-vollib."""

import math
import logging
import py_vollib.black_scholes as bs
import py_vollib.black_scholes.greeks.analytical as greeks
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass

from ..symbol_parser import parse_bybit_option_symbol

logger = logging.getLogger(__name__)


@dataclass
class OptionSpec:
    """Specification for an option contract."""
    symbol: str
    underlying_price: float
    strike: float
    expiration_date: datetime
    option_type: str  # 'call' or 'put'
    risk_free_rate: float = 0.05
    implied_volatility: Optional[float] = None


@dataclass
class OptionMetrics:
    """Comprehensive option pricing metrics."""
    theoretical_price: float
    delta: float
    gamma: float
    theta: float  # Per day
    vega: float  # Per 1% vol change
    rho: float
    time_to_expiration: float  # In years
    intrinsic_value: float
    time_value: float


class ProfessionalOptionsEngine:
    """Professional options pricing engine using py-vollib Black-Scholes implementation."""
    
    def __init__(self, risk_free_rate: float = 0.05):
        """
        Initialize the pricing engine.
        
        Args:
            risk_free_rate: Risk-free interest rate (default 5%)
        """
        self.risk_free_rate = self._validate_finite(
            "risk_free_rate", risk_free_rate
        )
    
    def parse_option_symbol(self, symbol: str) -> Optional[Dict]:
        """Parse Bybit option symbol format: BTC-30DEC24-70000-C"""
        parsed = parse_bybit_option_symbol(symbol)
        if parsed is None:
            return None
        return {
            'asset': parsed['asset'],
            'expiration_date': parsed['expiry_date'],
            'strike': parsed['strike'],
            'option_type': parsed['option_type_long'],
        }
    
    def calculate_time_to_expiration(self, expiration_date: datetime, 
                                   current_date: Optional[datetime] = None) -> float:
        """
        Calculate time to expiration in years with proper handling.
        
        Args:
            expiration_date: Option expiration date
            current_date: Current date (defaults to now)
            
        Returns:
            Time to expiration in years
        """
        self._validate_datetime("expiration_date", expiration_date)
        if current_date is None:
            current_date = datetime.now(tz=expiration_date.tzinfo)
        else:
            self._validate_datetime("current_date", current_date)

        expiration_is_aware = expiration_date.utcoffset() is not None
        current_is_aware = current_date.utcoffset() is not None
        if expiration_is_aware != current_is_aware:
            raise ValueError(
                "expiration_date and current_date must both be timezone-naive "
                "or both be timezone-aware"
            )
            
        if expiration_date <= current_date:
            return 0.0
            
        # Calculate time difference in years
        time_diff = expiration_date - current_date
        years = time_diff.total_seconds() / (365.25 * 24 * 3600)
        return max(0.0, years)
    
    def calculate_option_metrics(self, spec: OptionSpec, 
                               current_date: Optional[datetime] = None) -> OptionMetrics:
        """
        Calculate comprehensive option metrics using py-vollib.
        
        Args:
            spec: Option specification
            current_date: Current date for time calculation
            
        Returns:
            OptionMetrics with all Greeks and pricing data
        """
        if not isinstance(spec, OptionSpec):
            raise TypeError("spec must be an OptionSpec")

        underlying_price = self._validate_finite(
            "underlying_price", spec.underlying_price
        )
        strike = self._validate_finite("strike", spec.strike)
        if underlying_price <= 0:
            raise ValueError("underlying_price must be greater than zero")
        if strike <= 0:
            raise ValueError("strike must be greater than zero")

        option_type = spec.option_type.lower() if isinstance(spec.option_type, str) else ""
        if option_type in {"call", "c"}:
            flag = "c"
        elif option_type in {"put", "p"}:
            flag = "p"
        else:
            raise ValueError("option_type must be one of: call, c, put, p")

        risk_free_rate = self._validate_finite(
            "risk_free_rate", spec.risk_free_rate
        )
        if spec.implied_volatility is None:
            implied_volatility = None
        else:
            implied_volatility = self._validate_finite(
                "implied_volatility", spec.implied_volatility
            )
            if implied_volatility <= 0:
                raise ValueError("implied_volatility must be greater than zero")

        # Calculate time to expiration
        time_to_exp = self.calculate_time_to_expiration(spec.expiration_date, current_date)
        
        # Handle expired options
        if time_to_exp <= 0:
            intrinsic = self._calculate_intrinsic_value(
                underlying_price, strike, flag
            )
            
            # For expired options, delta is 1 if ITM call or 0 otherwise
            if flag == 'c':
                delta_val = 1.0 if underlying_price > strike else 0.0
            else:
                delta_val = -1.0 if underlying_price < strike else 0.0
            
            return OptionMetrics(
                theoretical_price=intrinsic,
                delta=delta_val,
                gamma=0.0, theta=0.0, vega=0.0, rho=0.0,
                time_to_expiration=0.0,
                intrinsic_value=intrinsic,
                time_value=0.0
            )
        
        if implied_volatility is None:
            raise ValueError(
                "implied_volatility is required for options that have not expired"
            )

        iv = implied_volatility

        try:
            # Calculate price using py-vollib Black-Scholes
            price = bs.black_scholes(
                flag, underlying_price, strike,
                time_to_exp, risk_free_rate, iv
            )
            
            # Calculate Greeks using py-vollib
            delta_val = greeks.delta(
                flag, underlying_price, strike,
                time_to_exp, risk_free_rate, iv
            )
            
            gamma_val = greeks.gamma(
                flag, underlying_price, strike,
                time_to_exp, risk_free_rate, iv
            )
            
            # Theta per day — py-vollib's analytical.theta already returns
            # per-day values (it divides by 365 internally). The earlier
            # code double-divided by 365.25, making theta 365x too small
            # and collapsing theta P&L to near-zero in PnL attribution.
            theta_val = greeks.theta(
                flag, underlying_price, strike,
                time_to_exp, risk_free_rate, iv
            )

            # Vega per 1 percentage point of IV — py-vollib's analytical.vega
            # already returns dPrice per 0.01 change in sigma (i.e. per 1 pp).
            # The earlier /100 made vega 100x too small.
            vega_val = greeks.vega(
                flag, underlying_price, strike,
                time_to_exp, risk_free_rate, iv
            )

            # Rho per 1 percentage point of rate — py-vollib's analytical.rho
            # already returns dPrice per 0.01 change in r. The earlier /100
            # made rho 100x too small.
            rho_val = greeks.rho(
                flag, underlying_price, strike,
                time_to_exp, risk_free_rate, iv
            )
            
            # Calculate intrinsic and time value
            intrinsic = self._calculate_intrinsic_value(
                underlying_price, strike, flag
            )
            time_value = max(0.0, price - intrinsic)
            
            # Validate results
            result_values = {
                "price": price,
                "delta": delta_val,
                "gamma": gamma_val,
                "theta": theta_val,
                "vega": vega_val,
                "rho": rho_val,
            }
            non_finite = [
                name for name, value in result_values.items()
                if not math.isfinite(value)
            ]
            if non_finite:
                raise ValueError(
                    "Pricing returned non-finite values: " + ", ".join(non_finite)
                )
            
            return OptionMetrics(
                theoretical_price=max(0.0, price),
                delta=delta_val,
                gamma=max(0.0, gamma_val),
                theta=theta_val,  # Can be negative
                vega=max(0.0, vega_val),
                rho=rho_val,  # Can be negative
                time_to_expiration=time_to_exp,
                intrinsic_value=max(0.0, intrinsic),
                time_value=max(0.0, time_value)
            )
            
        except Exception:
            logger.exception("Error calculating metrics for %s", spec.symbol)
            raise

    @staticmethod
    def _validate_finite(name: str, value: float) -> float:
        """Return a finite numeric value or raise a clear validation error."""
        if isinstance(value, (str, bytes, bool)) or value is None:
            raise ValueError(f"{name} must be a finite number")
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be a finite number") from exc
        if not math.isfinite(numeric_value):
            raise ValueError(f"{name} must be a finite number")
        return numeric_value

    @staticmethod
    def _validate_datetime(name: str, value: datetime) -> None:
        """Validate datetime inputs before arithmetic/comparison."""
        if not isinstance(value, datetime):
            raise ValueError(f"{name} must be a datetime")
    
    def _calculate_intrinsic_value(self, S: float, K: float, flag: str) -> float:
        """Calculate intrinsic value for call or put."""
        if flag == 'c':
            return max(0.0, S - K)
        else:
            return max(0.0, K - S)
    
