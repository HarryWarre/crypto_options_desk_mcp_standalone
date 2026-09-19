"""
Portfolio Strategy Transformer - Handles portfolio strategy transformations

Contains StrategyTransformer class for converting between different option strategies
like risk-reversal to seagull, straddle to strangle, etc.
"""

from datetime import datetime, timezone
from .types import Portfolio, Position
from .utils import parse_option_symbol, create_option_symbol


class StrategyTransformer:
    """Handles portfolio strategy transformations"""
    
    def risk_reversal_to_seagull(self, portfolio: Portfolio, short_call_strike: float) -> Portfolio:
        """Add short call above long call strike to convert risk reversal to seagull
        
        Args:
            portfolio: Source portfolio containing risk reversal
            short_call_strike: Strike price for the short call wing
            
        Returns:
            New portfolio with seagull structure
            
        Raises:
            ValueError: If no long call found or invalid parameters
        """
        new_positions = portfolio.positions.copy()
        
        # Find the long call in the risk reversal
        long_calls = [
            (symbol, pos) for symbol, pos in new_positions.items() 
            if pos.quantity > 0 and parse_option_symbol(symbol).is_call
        ]
        
        if not long_calls:
            raise ValueError("No long call found in portfolio for seagull transformation")
        
        # Use the first long call as reference
        reference_symbol, reference_position = long_calls[0]
        call_info = parse_option_symbol(reference_symbol)
        
        # Create short call symbol
        short_call_symbol = create_option_symbol(
            call_info.base_coin,
            call_info.expiry_date,
            short_call_strike,
            'C'
        )
        
        # Add short call position
        new_positions[short_call_symbol] = Position(
            symbol=short_call_symbol,
            quantity=-1.0,  # Short position
            entry_price=None
        )
        
        return Portfolio(
            name=f"{portfolio.name}_seagull",
            positions=new_positions,
            metadata={**portfolio.metadata, "transformation": "risk_reversal_to_seagull"},
            created_at=datetime.now(timezone.utc)
        )
    
    def straddle_to_strangle(self, portfolio: Portfolio, strike_width: float) -> Portfolio:
        """Move strikes away from ATM to convert straddle to strangle
        
        Args:
            portfolio: Source portfolio containing straddle
            strike_width: Distance to move strikes from ATM
            
        Returns:
            New portfolio with strangle structure
        """
        new_positions = {}
        
        for symbol, position in portfolio.positions.items():
            try:
                option_info = parse_option_symbol(symbol)
                current_strike = option_info.strike
                
                if option_info.is_call:
                    # Move call strike higher
                    new_strike = current_strike + strike_width
                else:
                    # Move put strike lower
                    new_strike = current_strike - strike_width
                
                # Create new symbol with adjusted strike
                new_symbol = create_option_symbol(
                    option_info.base_coin,
                    option_info.expiry_date,
                    new_strike,
                    option_info.option_type
                )
                
                new_positions[new_symbol] = Position(
                    symbol=new_symbol,
                    quantity=position.quantity,
                    entry_price=position.entry_price,
                    entry_iv=position.entry_iv
                )
            except ValueError:
                # Keep non-option positions unchanged
                new_positions[symbol] = position
        
        return Portfolio(
            name=f"{portfolio.name}_strangle",
            positions=new_positions,
            metadata={**portfolio.metadata, "transformation": "straddle_to_strangle"},
            created_at=datetime.now(timezone.utc)
        )
    
    def condor_adjustment(self, portfolio: Portfolio, adjustment_type: str, **kwargs) -> Portfolio:
        """Handle breached iron condor adjustments
        
        Args:
            portfolio: Source portfolio containing iron condor
            adjustment_type: Type of adjustment ('roll_untested', 'close_tested')
            **kwargs: Additional parameters:
                breached_side: 'call' or 'put' (default: 'call')
                roll_strike_offset: strike difference to shift untested side (default: 1000.0)
                
        Returns:
            Adjusted portfolio
        """
        breached_side = kwargs.get("breached_side", "call").lower()
        new_positions = portfolio.positions.copy()
        
        calls = []
        puts = []
        for symbol, pos in list(new_positions.items()):
            try:
                opt = parse_option_symbol(symbol)
                if opt.is_call:
                    calls.append((symbol, pos, opt))
                else:
                    puts.append((symbol, pos, opt))
            except ValueError:
                continue

        if adjustment_type == "close_tested":
            # Remove tested side legs
            to_remove = calls if breached_side == "call" else puts
            for symbol, _, _ in to_remove:
                new_positions.pop(symbol, None)
            return Portfolio(
                name=f"{portfolio.name}_condor_close_tested",
                positions=new_positions,
                metadata={**portfolio.metadata, "transformation": "condor_close_tested", "breached_side": breached_side},
                created_at=datetime.now(timezone.utc),
            )

        elif adjustment_type == "roll_untested":
            offset = float(kwargs.get("roll_strike_offset", 1000.0))
            untested_legs = puts if breached_side == "call" else calls
            
            # Remove old untested legs
            for symbol, _, _ in untested_legs:
                new_positions.pop(symbol, None)
                
            # Create rolled untested legs
            for _, pos, opt in untested_legs:
                if breached_side == "call":
                    new_strike = opt.strike + offset
                else:
                    new_strike = opt.strike - offset
                
                new_sym = create_option_symbol(
                    opt.base_coin,
                    opt.expiry_date,
                    new_strike,
                    opt.option_type
                )
                new_positions[new_sym] = Position(
                    symbol=new_sym,
                    quantity=pos.quantity,
                    entry_price=pos.entry_price,
                    entry_iv=pos.entry_iv,
                )
                
            return Portfolio(
                name=f"{portfolio.name}_condor_roll_untested",
                positions=new_positions,
                metadata={**portfolio.metadata, "transformation": "condor_roll_untested", "breached_side": breached_side},
                created_at=datetime.now(timezone.utc),
            )
        else:
            raise ValueError(f"Unknown adjustment_type: {adjustment_type}")
    
    def butterfly_to_broken_wing(self, portfolio: Portfolio, bias: str) -> Portfolio:
        """Convert butterfly for directional bias
        
        Args:
            portfolio: Source portfolio containing butterfly
            bias: Direction of bias ('bullish' or 'bearish')
            
        Returns:
            Portfolio with broken wing butterfly structure
        """
        new_positions = portfolio.positions.copy()
        options = []
        for symbol, pos in new_positions.items():
            try:
                opt = parse_option_symbol(symbol)
                options.append((symbol, pos, opt))
            except ValueError:
                continue

        options.sort(key=lambda x: x[2].strike)
        if len(options) < 3:
            raise ValueError("Portfolio does not contain at least 3 option strikes for butterfly")

        if bias.lower() == "bullish":
            upper_sym, upper_pos, upper_opt = options[-1]
            new_positions.pop(upper_sym, None)
            new_strike = upper_opt.strike + 1000.0
            new_sym = create_option_symbol(upper_opt.base_coin, upper_opt.expiry_date, new_strike, upper_opt.option_type)
            new_positions[new_sym] = Position(symbol=new_sym, quantity=upper_pos.quantity, entry_price=upper_pos.entry_price)
        else:
            lower_sym, lower_pos, lower_opt = options[0]
            new_positions.pop(lower_sym, None)
            new_strike = lower_opt.strike - 1000.0
            new_sym = create_option_symbol(lower_opt.base_coin, lower_opt.expiry_date, new_strike, lower_opt.option_type)
            new_positions[new_sym] = Position(symbol=new_sym, quantity=lower_pos.quantity, entry_price=lower_pos.entry_price)

        return Portfolio(
            name=f"{portfolio.name}_broken_wing",
            positions=new_positions,
            metadata={**portfolio.metadata, "transformation": "butterfly_to_broken_wing", "bias": bias},
            created_at=datetime.now(timezone.utc),
        )