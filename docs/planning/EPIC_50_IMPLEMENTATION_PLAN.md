# Epic 50: Unified Strategy Architecture - Implementation Plan

**Created**: 2025-12-08
**Branch**: `epic-50`
**Base**: v0.3.0 (production)
**Approach**: In-place refactoring with comprehensive testing

---

## Executive Summary

This plan transforms the current 14 strategy implementations into a unified, parametric architecture where **all vertical spreads are the same thing with different parameters**. The goal is maximum flexibility for future algorithms (Trident, Wheel, ML) while maintaining production stability.

### Core Insight

A credit put spread, credit call spread, debit put spread, and debit call spread are **identical structures** differentiated only by:
- **Direction**: Bullish vs Bearish
- **Option Type**: Put vs Call  
- **Position Side**: Which leg is short vs long (determines credit vs debit)

```
Credit Put Spread:  SHORT near_put + LONG far_put   (bullish, credit)
Debit Put Spread:   LONG near_put + SHORT far_put   (bearish, debit)
Credit Call Spread: SHORT near_call + LONG far_call (bearish, credit)
Debit Call Spread:  LONG near_call + SHORT far_call (bullish, debit)
```

### Why In-Place (Not v2 Parallel)

1. **Current codebase is clean** - v0.3.0 with squashed migrations
2. **Existing base classes already unified** - `CreditSpreadStrategy` and `DebitSpreadStrategy` use direction parameter
3. **Registry uses strings** - No class references to break
4. **Tests exist** - Can validate each step
5. **Lower complexity** - One code path to maintain

---

## Current State Analysis

### What We Have (Good Foundation)

| Component | Status | Location |
|-----------|--------|----------|
| Parameter System | ✅ Complete | `services/strategies/parameters.py` |
| Exit Framework | ✅ Complete | `services/exit_strategies/` |
| Credit Spread Base | ✅ Unified | `services/strategies/credit_spread_base.py` |
| Debit Spread Base | ✅ Unified | `services/strategies/debit_spread_base.py` |
| Strategy Registry | ✅ Working | `services/strategies/registry.py` |
| Greeks Service | ✅ Working | `services/market_data/greeks.py` |

### Current Strategy Count: 12,334 lines across 18 files

**Vertical Spreads (target for unification):**
- `credit_spread_strategy.py` (369 lines) - Bull Put + Bear Call
- `debit_spread_strategy.py` (572 lines) - Bull Call + Bear Put
- `credit_spread_base.py` (675 lines) - Shared credit logic
- `debit_spread_base.py` (654 lines) - Shared debit logic

**Multi-Leg (future unification):**
- `short_iron_condor_strategy.py` (863 lines)
- `long_iron_condor_strategy.py` (932 lines)
- `iron_butterfly_strategy.py` (904 lines)

**Single-Leg:**
- `cash_secured_put_strategy.py` (735 lines)
- `covered_call_strategy.py` (682 lines)

**Volatility:**
- `long_straddle_strategy.py` (724 lines)
- `long_strangle_strategy.py` (791 lines)

**Other:**
- `calendar_spread_strategy.py` (880 lines)
- `call_backspread_strategy.py` (770 lines)
- `senex_trident_strategy.py` (1141 lines) - Algorithm, not strategy

### What's Missing

| Component | Impact | Priority |
|-----------|--------|----------|
| Parametric Builder | Core flexibility | P0 |
| Leg Composition System | Building block | P0 |
| Greeks Fetcher (stress bypass) | Delta selection | P1 |
| Quality Scoring System | Always-generate | P1 |
| Put Backspread Strategy | Feature gap | P2 |
| Delta Strike Selector | Advanced selection | P2 |

---

## Implementation Phases

### Phase 1: Core Primitives (Foundation)
**Goal**: Create the building blocks for parametric strategy construction
**Effort**: 8-10 hours
**Risk**: Low (new code, no changes to existing)

### Phase 2: Vertical Spread Builder
**Goal**: Single builder for all 4 vertical spread types
**Effort**: 6-8 hours
**Risk**: Medium (replaces existing strategies)

### Phase 3: Quality & Greeks Infrastructure
**Goal**: Enable delta-based selection and always-generate pattern
**Effort**: 6-8 hours
**Risk**: Low (additive features)

### Phase 4: Strategy Migration
**Goal**: Migrate all strategies to use builders
**Effort**: 10-12 hours
**Risk**: Medium (touching production code)

### Phase 5: Multi-Leg Builders
**Goal**: Iron Condor, Butterfly, Straddle/Strangle builders
**Effort**: 8-10 hours
**Risk**: Medium

### Phase 6: Validation & Cleanup
**Goal**: Parity testing, documentation, remove deprecated code
**Effort**: 4-6 hours
**Risk**: Low

**Total Estimate**: 42-54 hours

---

## Phase 1: Core Primitives

### Task 1.1: Create Type System
**File**: `services/strategies/core/types.py`
**Effort**: 1 hour

```python
"""Core type definitions for strategy architecture."""

from decimal import Decimal
from enum import Enum
from typing import TypeAlias

# Type aliases for clarity
Strike: TypeAlias = Decimal
Premium: TypeAlias = Decimal
Delta: TypeAlias = float
Quantity: TypeAlias = int


class Direction(Enum):
    """Market direction bias."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class OptionType(Enum):
    """Option instrument type."""
    CALL = "call"
    PUT = "put"


class Side(Enum):
    """Position side (long/short)."""
    LONG = "long"    # Bought, own the option
    SHORT = "short"  # Sold, obligation


class PriceEffect(Enum):
    """Net effect on account."""
    CREDIT = "credit"  # Receive premium
    DEBIT = "debit"    # Pay premium


class StrikeSelection(Enum):
    """Method for selecting strikes."""
    DELTA = "delta"           # Target delta (e.g., 0.30)
    OTM_PERCENT = "otm_pct"   # Percentage OTM (e.g., 3%)
    FIXED_WIDTH = "width"     # Fixed dollar width
    ATM_OFFSET = "atm"        # Points from ATM
```

**Acceptance Criteria**:
- [ ] All enums defined with string values for serialization
- [ ] Type aliases for Decimal fields
- [ ] Unit tests for enum serialization

---

### Task 1.2: Create Option Primitive
**File**: `services/strategies/core/primitives.py`
**Effort**: 2 hours

```python
"""Option primitive - the atomic unit of all strategies."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from services.strategies.core.types import OptionType, Strike


@dataclass(frozen=True)
class OptionContract:
    """
    Immutable option contract specification.
    
    This is the atomic unit - every strategy is built from these.
    Frozen for hashability and to prevent accidental mutation.
    """
    symbol: str              # Underlying symbol (e.g., "SPY")
    option_type: OptionType  # CALL or PUT
    strike: Strike           # Strike price
    expiration: date         # Expiration date
    
    @property
    def occ_symbol(self) -> str:
        """Generate OCC option symbol."""
        # SPY   251219C00585000
        # Symbol(6) + Date(6) + Type(1) + Strike(8)
        symbol_part = self.symbol.ljust(6)
        date_part = self.expiration.strftime("%y%m%d")
        type_part = "C" if self.option_type == OptionType.CALL else "P"
        strike_part = f"{int(self.strike * 1000):08d}"
        return f"{symbol_part}{date_part}{type_part}{strike_part}"
    
    def intrinsic_value(self, spot_price: Decimal) -> Decimal:
        """Calculate intrinsic value at given spot price."""
        if self.option_type == OptionType.CALL:
            return max(Decimal("0"), spot_price - self.strike)
        else:  # PUT
            return max(Decimal("0"), self.strike - spot_price)
    
    def is_itm(self, spot_price: Decimal) -> bool:
        """Check if option is in-the-money."""
        return self.intrinsic_value(spot_price) > 0
    
    def moneyness(self, spot_price: Decimal) -> Decimal:
        """Calculate moneyness (strike / spot for calls, spot / strike for puts)."""
        if self.option_type == OptionType.CALL:
            return self.strike / spot_price
        else:
            return spot_price / self.strike
```

**Acceptance Criteria**:
- [ ] OCC symbol generation matches TastyTrade format
- [ ] Intrinsic value calculations correct for both types
- [ ] Frozen dataclass (immutable)
- [ ] Unit tests for all methods

---

### Task 1.3: Create Leg Composition
**File**: `services/strategies/core/legs.py`
**Effort**: 2 hours

```python
"""Option leg - combines contract with position details."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from services.strategies.core.primitives import OptionContract
from services.strategies.core.types import Side, Premium, Quantity, OptionType


@dataclass
class OptionLeg:
    """
    Single option position within a strategy.
    
    Combines an option contract with trading details (side, premium, quantity).
    This is what gets converted to TastyTrade Leg objects for order submission.
    """
    contract: OptionContract  # The underlying option
    side: Side                # LONG or SHORT
    quantity: Quantity        # Number of contracts
    premium: Premium | None = None  # Entry price (None until filled)
    
    # Optional tracking
    leg_id: str | None = None     # Internal identifier
    occ_symbol: str | None = None # Cached OCC symbol
    
    def __post_init__(self):
        """Cache OCC symbol on creation."""
        if self.occ_symbol is None:
            self.occ_symbol = self.contract.occ_symbol
    
    @property
    def is_long(self) -> bool:
        return self.side == Side.LONG
    
    @property
    def is_short(self) -> bool:
        return self.side == Side.SHORT
    
    def cash_flow(self) -> Decimal:
        """
        Calculate cash flow for this leg.
        
        Returns:
            Positive for credits (short), negative for debits (long)
        """
        if self.premium is None:
            return Decimal("0")
        
        multiplier = Decimal("100") * self.quantity
        if self.side == Side.SHORT:
            return self.premium * multiplier  # Receive premium
        else:
            return -self.premium * multiplier  # Pay premium
    
    def payoff_at_expiry(self, spot_price: Decimal) -> Decimal:
        """
        Calculate P&L at expiration.
        
        Args:
            spot_price: Underlying price at expiration
            
        Returns:
            Total P&L including premium paid/received
        """
        intrinsic = self.contract.intrinsic_value(spot_price)
        multiplier = Decimal("100") * self.quantity
        
        if self.side == Side.LONG:
            # Long: profit if intrinsic > premium paid
            pnl = (intrinsic - (self.premium or Decimal("0"))) * multiplier
        else:
            # Short: profit if premium received > intrinsic
            pnl = ((self.premium or Decimal("0")) - intrinsic) * multiplier
        
        return pnl
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage."""
        return {
            "symbol": self.contract.symbol,
            "option_type": self.contract.option_type.value,
            "strike": str(self.contract.strike),
            "expiration": self.contract.expiration.isoformat(),
            "side": self.side.value,
            "quantity": self.quantity,
            "premium": str(self.premium) if self.premium else None,
            "occ_symbol": self.occ_symbol,
            "leg_id": self.leg_id,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OptionLeg":
        """Deserialize from JSON."""
        contract = OptionContract(
            symbol=data["symbol"],
            option_type=OptionType(data["option_type"]),
            strike=Decimal(data["strike"]),
            expiration=date.fromisoformat(data["expiration"]),
        )
        return cls(
            contract=contract,
            side=Side(data["side"]),
            quantity=data["quantity"],
            premium=Decimal(data["premium"]) if data.get("premium") else None,
            occ_symbol=data.get("occ_symbol"),
            leg_id=data.get("leg_id"),
        )
```

**Acceptance Criteria**:
- [ ] Cash flow calculations correct (credit = positive, debit = negative)
- [ ] Payoff calculations match existing implementations
- [ ] Serialization round-trip works
- [ ] Unit tests for long/short scenarios

---

### Task 1.4: Create Strategy Composition
**File**: `services/strategies/core/composite.py`
**Effort**: 2 hours

```python
"""Composite strategy - multi-leg position."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from services.strategies.core.legs import OptionLeg
from services.strategies.core.types import Direction, PriceEffect, Side


@dataclass
class CompositeStrategy:
    """
    Multi-leg options strategy.
    
    Aggregates multiple OptionLeg objects and provides calculations
    across the entire position. This is the output of all builders.
    """
    name: str                          # Human-readable name
    strategy_type: str                 # Registry key (e.g., "short_put_vertical")
    legs: list[OptionLeg]              # Component legs
    direction: Direction = Direction.NEUTRAL
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def price_effect(self) -> PriceEffect:
        """Determine if strategy is net credit or debit."""
        net = self.net_premium()
        return PriceEffect.CREDIT if net > 0 else PriceEffect.DEBIT
    
    def net_premium(self) -> Decimal:
        """
        Calculate net premium (credit - debit).
        
        Returns:
            Positive for net credit, negative for net debit
        """
        return sum(leg.cash_flow() for leg in self.legs)
    
    def max_profit(self) -> Decimal:
        """
        Calculate theoretical maximum profit.
        
        Tests payoff at key price points (0, strikes, 2x max strike).
        """
        if not self.legs:
            return Decimal("0")
        
        strikes = [leg.contract.strike for leg in self.legs]
        test_points = [Decimal("0")] + strikes + [max(strikes) * 2]
        
        payoffs = [self.total_payoff(price) for price in test_points]
        return max(payoffs)
    
    def max_loss(self) -> Decimal:
        """
        Calculate theoretical maximum loss.
        
        Returns absolute value (positive number).
        """
        if not self.legs:
            return Decimal("0")
        
        strikes = [leg.contract.strike for leg in self.legs]
        test_points = [Decimal("0")] + strikes + [max(strikes) * 2]
        
        payoffs = [self.total_payoff(price) for price in test_points]
        return abs(min(payoffs))
    
    def total_payoff(self, spot_price: Decimal) -> Decimal:
        """Calculate total P&L at given spot price."""
        return sum(leg.payoff_at_expiry(spot_price) for leg in self.legs)
    
    def breakeven_points(self) -> list[Decimal]:
        """Calculate breakeven price(s)."""
        if not self.legs:
            return []
        
        strikes = [float(leg.contract.strike) for leg in self.legs]
        min_price = min(strikes) * 0.5
        max_price = max(strikes) * 1.5
        
        # Sample 1000 points and find zero crossings
        step = (max_price - min_price) / 1000
        breakevens = []
        
        prev_payoff = None
        for i in range(1001):
            price = Decimal(str(min_price + i * step))
            payoff = float(self.total_payoff(price))
            
            if prev_payoff is not None and prev_payoff * payoff < 0:
                # Sign change - interpolate
                breakevens.append(price)
            
            prev_payoff = payoff
        
        return breakevens
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage/transmission."""
        return {
            "name": self.name,
            "strategy_type": self.strategy_type,
            "direction": self.direction.value,
            "legs": [leg.to_dict() for leg in self.legs],
            "metadata": self.metadata,
            "calculated": {
                "net_premium": str(self.net_premium()),
                "max_profit": str(self.max_profit()),
                "max_loss": str(self.max_loss()),
                "price_effect": self.price_effect.value,
            }
        }
```

**Acceptance Criteria**:
- [ ] Net premium calculation matches existing strategies
- [ ] Max profit/loss calculations correct
- [ ] Breakeven detection works
- [ ] Integration test with real spread parameters

---

### Task 1.5: Create Core Module Init
**File**: `services/strategies/core/__init__.py`
**Effort**: 0.5 hours

```python
"""
Core strategy primitives and composition system.

This module provides the building blocks for all strategies:
- OptionContract: Atomic option specification
- OptionLeg: Contract + position details
- CompositeStrategy: Multi-leg aggregation
- Type enums: Direction, OptionType, Side, etc.

Usage:
    from services.strategies.core import (
        OptionContract, OptionLeg, CompositeStrategy,
        Direction, OptionType, Side, PriceEffect
    )
"""

from services.strategies.core.types import (
    Direction,
    OptionType,
    Side,
    PriceEffect,
    StrikeSelection,
    Strike,
    Premium,
    Delta,
    Quantity,
)
from services.strategies.core.primitives import OptionContract
from services.strategies.core.legs import OptionLeg
from services.strategies.core.composite import CompositeStrategy

__all__ = [
    # Types
    "Direction",
    "OptionType", 
    "Side",
    "PriceEffect",
    "StrikeSelection",
    "Strike",
    "Premium",
    "Delta",
    "Quantity",
    # Classes
    "OptionContract",
    "OptionLeg",
    "CompositeStrategy",
]
```

---

### Phase 1 Validation

**Run after completing Phase 1:**

```bash
# Create and run tests
pytest tests/services/strategies/core/ -v

# Verify imports work
python -c "from services.strategies.core import OptionContract, OptionLeg, CompositeStrategy, Direction, OptionType, Side"
```

**Phase 1 Deliverables:**
- [ ] `services/strategies/core/types.py`
- [ ] `services/strategies/core/primitives.py`
- [ ] `services/strategies/core/legs.py`
- [ ] `services/strategies/core/composite.py`
- [ ] `services/strategies/core/__init__.py`
- [ ] `tests/services/strategies/core/test_types.py`
- [ ] `tests/services/strategies/core/test_primitives.py`
- [ ] `tests/services/strategies/core/test_legs.py`
- [ ] `tests/services/strategies/core/test_composite.py`

---

## Phase 2: Vertical Spread Builder

### Task 2.1: Create Builder Parameters
**File**: `services/strategies/builders/parameters.py`
**Effort**: 1 hour

```python
"""Builder parameters - configuration for strategy construction."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from services.strategies.core import Direction, OptionType, StrikeSelection


@dataclass
class VerticalSpreadParams:
    """
    Parameters for building any vertical spread.
    
    This single parameter class replaces the need for 4 separate strategy classes.
    The combination of direction + option_type determines the spread type:
    
    - BULLISH + PUT = Bull Put Spread (credit)
    - BEARISH + PUT = Bear Put Spread (debit)
    - BULLISH + CALL = Bull Call Spread (debit)
    - BEARISH + CALL = Bear Call Spread (credit)
    """
    # Required: What kind of spread
    direction: Direction      # BULLISH or BEARISH
    option_type: OptionType   # PUT or CALL
    
    # Strike selection
    selection_method: StrikeSelection = StrikeSelection.OTM_PERCENT
    
    # Method-specific parameters
    otm_percent: Decimal = Decimal("0.03")  # 3% OTM default
    target_delta: float | None = None        # For delta-based selection
    spread_width: Decimal = Decimal("5")     # $5 wide default
    
    # Risk/reward constraints
    min_credit: Decimal | None = None        # Minimum acceptable credit
    max_debit: Decimal | None = None         # Maximum acceptable debit
    max_risk: Decimal | None = None          # Maximum loss allowed
    
    # DTE constraints
    min_dte: int = 30
    max_dte: int = 45
    target_dte: int = 45
    
    # Quantity
    quantity: int = 1
    
    # Metadata for tracking
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_credit_spread(self) -> bool:
        """Determine if this configuration produces a credit spread."""
        # Credit spreads: Bull Put (sell higher, buy lower) or Bear Call (sell lower, buy higher)
        if self.direction == Direction.BULLISH and self.option_type == OptionType.PUT:
            return True
        if self.direction == Direction.BEARISH and self.option_type == OptionType.CALL:
            return True
        return False
    
    @property
    def strategy_type(self) -> str:
        """Generate registry key for this configuration."""
        # Map to current naming convention
        if self.direction == Direction.BULLISH:
            if self.option_type == OptionType.PUT:
                return "short_put_vertical"  # Bull put = credit
            else:
                return "long_call_vertical"  # Bull call = debit
        else:  # BEARISH
            if self.option_type == OptionType.PUT:
                return "long_put_vertical"   # Bear put = debit
            else:
                return "short_call_vertical" # Bear call = credit
    
    @property
    def human_name(self) -> str:
        """Generate human-readable strategy name."""
        direction = "Bull" if self.direction == Direction.BULLISH else "Bear"
        option = "Put" if self.option_type == OptionType.PUT else "Call"
        return f"{direction} {option} Spread"
```

**Acceptance Criteria**:
- [ ] `is_credit_spread` correctly identifies all 4 types
- [ ] `strategy_type` matches existing registry keys
- [ ] Default values match current strategy defaults

---

### Task 2.2: Create Vertical Spread Builder
**File**: `services/strategies/builders/vertical.py`
**Effort**: 3 hours

```python
"""
Vertical Spread Builder - Parametric construction of all vertical spreads.

This builder replaces 4 separate strategy classes with one parametric implementation:
- Bull Put Spread (short_put_vertical)
- Bear Put Spread (long_put_vertical)
- Bull Call Spread (long_call_vertical)
- Bear Call Spread (short_call_vertical)

The key insight: these are ALL the same structure with different parameters.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from services.core.logging import get_logger
from services.strategies.core import (
    OptionContract, OptionLeg, CompositeStrategy,
    Direction, OptionType, Side, PriceEffect, StrikeSelection
)
from services.strategies.builders.parameters import VerticalSpreadParams

logger = get_logger(__name__)


class VerticalSpreadBuilder:
    """
    Builder for all vertical spread variations.
    
    Usage:
        params = VerticalSpreadParams(
            direction=Direction.BULLISH,
            option_type=OptionType.PUT,
            spread_width=Decimal("5"),
        )
        spread = VerticalSpreadBuilder.build(
            params=params,
            symbol="SPY",
            expiration=date(2025, 1, 17),
            short_strike=Decimal("580"),
            long_strike=Decimal("575"),
            short_premium=Decimal("2.50"),
            long_premium=Decimal("1.50"),
        )
    """
    
    @classmethod
    def build(
        cls,
        params: VerticalSpreadParams,
        symbol: str,
        expiration: date,
        short_strike: Decimal,
        long_strike: Decimal,
        short_premium: Decimal | None = None,
        long_premium: Decimal | None = None,
    ) -> CompositeStrategy:
        """
        Build a vertical spread from parameters and strikes.
        
        Args:
            params: Spread configuration
            symbol: Underlying symbol
            expiration: Option expiration date
            short_strike: Strike price for short leg
            long_strike: Strike price for long leg
            short_premium: Premium for short leg (optional)
            long_premium: Premium for long leg (optional)
            
        Returns:
            CompositeStrategy with 2 legs configured
            
        Raises:
            ValueError: If strikes don't match spread direction
        """
        # Validate strike relationship
        cls._validate_strikes(params, short_strike, long_strike)
        
        # Build the two legs
        legs = cls._build_legs(
            params=params,
            symbol=symbol,
            expiration=expiration,
            short_strike=short_strike,
            long_strike=long_strike,
            short_premium=short_premium,
            long_premium=long_premium,
        )
        
        # Create composite strategy
        strategy = CompositeStrategy(
            name=params.human_name,
            strategy_type=params.strategy_type,
            legs=legs,
            direction=params.direction,
            metadata={
                "spread_width": float(abs(short_strike - long_strike)),
                "is_credit": params.is_credit_spread,
                "params": {
                    "direction": params.direction.value,
                    "option_type": params.option_type.value,
                    "selection_method": params.selection_method.value,
                }
            }
        )
        
        logger.info(
            f"Built {params.human_name}: "
            f"short {short_strike} @ {short_premium}, "
            f"long {long_strike} @ {long_premium}, "
            f"net {strategy.net_premium():.2f}"
        )
        
        return strategy
    
    @classmethod
    def _validate_strikes(
        cls,
        params: VerticalSpreadParams,
        short_strike: Decimal,
        long_strike: Decimal,
    ) -> None:
        """Validate strike prices match spread type."""
        if params.option_type == OptionType.PUT:
            # Put spreads: short strike should be higher for credit (bull put)
            if params.is_credit_spread and short_strike <= long_strike:
                raise ValueError(
                    f"Bull put spread requires short_strike > long_strike, "
                    f"got {short_strike} <= {long_strike}"
                )
            if not params.is_credit_spread and short_strike >= long_strike:
                raise ValueError(
                    f"Bear put spread requires short_strike < long_strike, "
                    f"got {short_strike} >= {long_strike}"
                )
        else:  # CALL
            # Call spreads: short strike should be lower for credit (bear call)
            if params.is_credit_spread and short_strike >= long_strike:
                raise ValueError(
                    f"Bear call spread requires short_strike < long_strike, "
                    f"got {short_strike} >= {long_strike}"
                )
            if not params.is_credit_spread and short_strike <= long_strike:
                raise ValueError(
                    f"Bull call spread requires short_strike > long_strike, "
                    f"got {short_strike} <= {long_strike}"
                )
    
    @classmethod
    def _build_legs(
        cls,
        params: VerticalSpreadParams,
        symbol: str,
        expiration: date,
        short_strike: Decimal,
        long_strike: Decimal,
        short_premium: Decimal | None,
        long_premium: Decimal | None,
    ) -> list[OptionLeg]:
        """Build the two option legs for the spread."""
        # Short leg
        short_contract = OptionContract(
            symbol=symbol,
            option_type=params.option_type,
            strike=short_strike,
            expiration=expiration,
        )
        short_leg = OptionLeg(
            contract=short_contract,
            side=Side.SHORT,
            quantity=params.quantity,
            premium=short_premium,
            leg_id="short",
        )
        
        # Long leg
        long_contract = OptionContract(
            symbol=symbol,
            option_type=params.option_type,
            strike=long_strike,
            expiration=expiration,
        )
        long_leg = OptionLeg(
            contract=long_contract,
            side=Side.LONG,
            quantity=params.quantity,
            premium=long_premium,
            leg_id="long",
        )
        
        return [short_leg, long_leg]
    
    @classmethod
    def from_market_data(
        cls,
        params: VerticalSpreadParams,
        symbol: str,
        expiration: date,
        underlying_price: Decimal,
        option_chain: dict[str, Any],
    ) -> CompositeStrategy | None:
        """
        Build spread by selecting strikes from option chain.
        
        This method handles strike selection based on params.selection_method:
        - OTM_PERCENT: Select strikes at X% out of the money
        - DELTA: Select strikes at target delta
        - FIXED_WIDTH: Select ATM-ish with fixed width
        
        Args:
            params: Spread configuration
            symbol: Underlying symbol
            expiration: Target expiration
            underlying_price: Current underlying price
            option_chain: Option chain data with strikes and greeks
            
        Returns:
            CompositeStrategy if strikes found, None otherwise
        """
        # Select strikes based on method
        strikes = cls._select_strikes(
            params=params,
            underlying_price=underlying_price,
            option_chain=option_chain,
        )
        
        if not strikes:
            logger.warning(f"Could not select strikes for {params.human_name}")
            return None
        
        short_strike, long_strike = strikes
        
        # Get premiums from chain
        short_premium = cls._get_premium(option_chain, short_strike, params.option_type, "ask")
        long_premium = cls._get_premium(option_chain, long_strike, params.option_type, "bid")
        
        return cls.build(
            params=params,
            symbol=symbol,
            expiration=expiration,
            short_strike=short_strike,
            long_strike=long_strike,
            short_premium=short_premium,
            long_premium=long_premium,
        )
    
    @classmethod
    def _select_strikes(
        cls,
        params: VerticalSpreadParams,
        underlying_price: Decimal,
        option_chain: dict[str, Any],
    ) -> tuple[Decimal, Decimal] | None:
        """
        Select short and long strikes based on selection method.
        
        Returns:
            (short_strike, long_strike) tuple or None if not found
        """
        if params.selection_method == StrikeSelection.OTM_PERCENT:
            return cls._select_by_otm_percent(params, underlying_price, option_chain)
        elif params.selection_method == StrikeSelection.DELTA:
            return cls._select_by_delta(params, option_chain)
        elif params.selection_method == StrikeSelection.FIXED_WIDTH:
            return cls._select_by_width(params, underlying_price, option_chain)
        else:
            logger.warning(f"Unknown selection method: {params.selection_method}")
            return None
    
    @classmethod
    def _select_by_otm_percent(
        cls,
        params: VerticalSpreadParams,
        underlying_price: Decimal,
        option_chain: dict[str, Any],
    ) -> tuple[Decimal, Decimal] | None:
        """Select strikes at X% out of the money."""
        otm_distance = underlying_price * params.otm_percent
        
        if params.option_type == OptionType.PUT:
            # Put spreads: below current price
            if params.is_credit_spread:
                # Bull put: short higher, long lower
                short_strike = underlying_price - otm_distance
                long_strike = short_strike - params.spread_width
            else:
                # Bear put: long higher, short lower
                long_strike = underlying_price - otm_distance
                short_strike = long_strike - params.spread_width
        else:  # CALL
            # Call spreads: above current price
            if params.is_credit_spread:
                # Bear call: short lower, long higher
                short_strike = underlying_price + otm_distance
                long_strike = short_strike + params.spread_width
            else:
                # Bull call: long lower, short higher
                long_strike = underlying_price + otm_distance
                short_strike = long_strike + params.spread_width
        
        # Round to valid strikes
        short_strike = cls._round_to_valid_strike(short_strike, option_chain)
        long_strike = cls._round_to_valid_strike(long_strike, option_chain)
        
        return (short_strike, long_strike)
    
    @classmethod
    def _select_by_delta(
        cls,
        params: VerticalSpreadParams,
        option_chain: dict[str, Any],
    ) -> tuple[Decimal, Decimal] | None:
        """Select strikes at target delta."""
        # TODO: Implement delta-based selection in Phase 3
        # This requires Greeks data in option chain
        logger.warning("Delta-based selection not yet implemented")
        return None
    
    @classmethod
    def _select_by_width(
        cls,
        params: VerticalSpreadParams,
        underlying_price: Decimal,
        option_chain: dict[str, Any],
    ) -> tuple[Decimal, Decimal] | None:
        """Select strikes with fixed width around ATM."""
        # Find ATM strike
        atm = cls._round_to_valid_strike(underlying_price, option_chain)
        
        if params.option_type == OptionType.PUT:
            if params.is_credit_spread:
                short_strike = atm
                long_strike = atm - params.spread_width
            else:
                long_strike = atm
                short_strike = atm - params.spread_width
        else:  # CALL
            if params.is_credit_spread:
                short_strike = atm
                long_strike = atm + params.spread_width
            else:
                long_strike = atm
                short_strike = atm + params.spread_width
        
        return (short_strike, long_strike)
    
    @staticmethod
    def _round_to_valid_strike(target: Decimal, option_chain: dict[str, Any]) -> Decimal:
        """Round to nearest valid strike in chain."""
        # Get available strikes from chain
        available = option_chain.get("strikes", [])
        if not available:
            # Default to $1 increments
            return Decimal(str(round(float(target))))
        
        # Find closest
        closest = min(available, key=lambda s: abs(Decimal(str(s)) - target))
        return Decimal(str(closest))
    
    @staticmethod
    def _get_premium(
        option_chain: dict[str, Any],
        strike: Decimal,
        option_type: OptionType,
        side: str,  # "bid" or "ask"
    ) -> Decimal | None:
        """Get premium from option chain."""
        chain_key = "puts" if option_type == OptionType.PUT else "calls"
        strike_data = option_chain.get(chain_key, {}).get(str(strike))
        
        if strike_data:
            return Decimal(str(strike_data.get(side, 0)))
        return None
```

**Acceptance Criteria**:
- [ ] Can build all 4 vertical spread types
- [ ] Strike validation catches invalid configurations
- [ ] OTM percent selection matches existing strategy logic
- [ ] Premium extraction from option chain works
- [ ] Parity test with existing strategies passes

---

### Task 2.3: Create Builder Module Init
**File**: `services/strategies/builders/__init__.py`
**Effort**: 0.5 hours

```python
"""
Strategy builders - Parametric construction of options strategies.

Builders replace multiple strategy classes with single parametric implementations:
- VerticalSpreadBuilder: 4 strategies → 1 builder
- (Future) IronCondorBuilder: 2 strategies → 1 builder
- (Future) ButterflyBuilder: 2 strategies → 1 builder
"""

from services.strategies.builders.parameters import VerticalSpreadParams
from services.strategies.builders.vertical import VerticalSpreadBuilder

__all__ = [
    "VerticalSpreadParams",
    "VerticalSpreadBuilder",
]
```

---

### Task 2.4: Create Builder Integration Tests
**File**: `tests/services/strategies/builders/test_vertical.py`
**Effort**: 2 hours

See separate test file for full implementation. Key tests:
- All 4 spread types produce correct structure
- Credit/debit classification correct
- Strike validation works
- Max profit/loss calculations match
- Parity with existing strategies

---

### Phase 2 Validation

**Run after completing Phase 2:**

```bash
# Run builder tests
pytest tests/services/strategies/builders/ -v

# Run parity tests (once existing strategy comparison is added)
pytest tests/services/strategies/builders/test_vertical.py::TestVerticalSpreadBuilderParity -v
```

**Phase 2 Deliverables:**
- [ ] `services/strategies/builders/__init__.py`
- [ ] `services/strategies/builders/parameters.py`
- [ ] `services/strategies/builders/vertical.py`
- [ ] `tests/services/strategies/builders/test_vertical.py`
- [ ] All 4 spread types working
- [ ] Parity with existing strategies validated

---

## Phase 3: Quality & Greeks Infrastructure

### Task 3.1: Port Quality Scoring System
**File**: `services/strategies/quality.py`
**Effort**: 2 hours
**Source**: `epic-50-unified-strategy-architecture:services/strategies/quality.py`

This implements the "always generate" pattern - never return None, always provide quality scores with warnings.

**Key Components:**
- `QualityScore` dataclass (0-100 score with metrics breakdown)
- `QualityLevel` enum (excellent/good/fair/poor)
- Scoring for: market alignment, strike deviation, DTE optimality, liquidity

---

### Task 3.2: Port Greeks Fetcher
**File**: `services/market_data/greeks_fetcher.py`
**Effort**: 2 hours
**Source**: `epic-50-unified-strategy-architecture:services/market_data/greeks_fetcher.py`

**Key Features:**
- 90-second cache TTL
- Market stress bypass at >70 threshold
- Streaming + historical fallback

---

### Task 3.3: Create Delta Strike Selector
**File**: `services/strategies/strike_selection/delta_selector.py`
**Effort**: 2 hours

**Key Features:**
- Select strikes by target delta
- Use Greeks fetcher for real delta values
- Fallback to OTM percent if Greeks unavailable

---

### Task 3.4: Integrate Quality into Builder
**Effort**: 2 hours

Update `VerticalSpreadBuilder.from_market_data()` to:
1. Return `QualityScore` alongside `CompositeStrategy`
2. Always generate (never return None)
3. Include warnings for suboptimal conditions

---

## Phase 4: Strategy Migration

### Task 4.1: Create Unified Vertical Strategy
**File**: `services/strategies/vertical_spread_strategy.py`
**Effort**: 3 hours

Replace the 4 registered strategies with one parametric strategy that uses the builder internally.

```python
@register_strategy("short_put_vertical")
@register_strategy("short_call_vertical")
@register_strategy("long_call_vertical")
@register_strategy("long_put_vertical")
class VerticalSpreadStrategy(BaseStrategy):
    """Unified vertical spread strategy using parametric builder."""
    
    def __init__(self, user, strategy_type: str):
        super().__init__(user)
        self._strategy_type = strategy_type
        self._params = self._params_from_type(strategy_type)
    
    @staticmethod
    def _params_from_type(strategy_type: str) -> VerticalSpreadParams:
        """Convert registry key to builder parameters."""
        mapping = {
            "short_put_vertical": (Direction.BULLISH, OptionType.PUT),
            "short_call_vertical": (Direction.BEARISH, OptionType.CALL),
            "long_call_vertical": (Direction.BULLISH, OptionType.CALL),
            "long_put_vertical": (Direction.BEARISH, OptionType.PUT),
        }
        direction, option_type = mapping[strategy_type]
        return VerticalSpreadParams(direction=direction, option_type=option_type)
```

---

### Task 4.2: Update Registry Pattern
**Effort**: 1 hour

Modify `register_strategy` decorator to support multiple registrations and strategy instantiation with type parameter.

---

### Task 4.3: Migrate Credit Spreads
**Effort**: 2 hours

Replace `credit_spread_strategy.py` implementation to use `VerticalSpreadStrategy`.

---

### Task 4.4: Migrate Debit Spreads
**Effort**: 2 hours

Replace `debit_spread_strategy.py` implementation to use `VerticalSpreadStrategy`.

---

### Task 4.5: Update Tests
**Effort**: 2 hours

Update existing strategy tests to work with new unified implementation.

---

## Phase 5: Multi-Leg Builders

### Task 5.1: Iron Condor Builder
**File**: `services/strategies/builders/iron_condor.py`
**Effort**: 3 hours

Unify `short_iron_condor` and `long_iron_condor` into one parametric builder.

---

### Task 5.2: Butterfly Builder
**File**: `services/strategies/builders/butterfly.py`
**Effort**: 2 hours

---

### Task 5.3: Straddle/Strangle Builder
**File**: `services/strategies/builders/volatility.py`
**Effort**: 2 hours

---

### Task 5.4: Backspread Builder
**File**: `services/strategies/builders/backspread.py`
**Effort**: 2 hours

Add put backspread using same pattern as call backspread.

---

## Phase 6: Validation & Cleanup

### Task 6.1: Comprehensive Parity Testing
**Effort**: 2 hours

Property-based tests comparing old vs new implementations.

---

### Task 6.2: Performance Benchmarks
**Effort**: 1 hour

Ensure builder approach doesn't regress performance.

---

### Task 6.3: Documentation Update
**Effort**: 2 hours

- Update AGENTS.md with new architecture
- Create builder usage guide
- Update strategy development guide

---

### Task 6.4: Remove Deprecated Code
**Effort**: 1 hour

After validation, remove:
- Old base classes (if fully replaced)
- Duplicate logic
- Unused imports

---

## Execution Checklist

### Phase 1: Core Primitives
- [ ] Task 1.1: Create type system
- [ ] Task 1.2: Create option primitive
- [ ] Task 1.3: Create leg composition
- [ ] Task 1.4: Create strategy composition
- [ ] Task 1.5: Create module init
- [ ] **Validation**: All Phase 1 tests pass

### Phase 2: Vertical Spread Builder
- [ ] Task 2.1: Create builder parameters
- [ ] Task 2.2: Create vertical spread builder
- [ ] Task 2.3: Create module init
- [ ] Task 2.4: Create integration tests
- [ ] **Validation**: All 4 spread types work, parity verified

### Phase 3: Quality & Greeks
- [ ] Task 3.1: Port quality scoring
- [ ] Task 3.2: Port Greeks fetcher
- [ ] Task 3.3: Create delta selector
- [ ] Task 3.4: Integrate quality into builder
- [ ] **Validation**: Quality scores returned, delta selection works

### Phase 4: Strategy Migration
- [ ] Task 4.1: Create unified vertical strategy
- [ ] Task 4.2: Update registry pattern
- [ ] Task 4.3: Migrate credit spreads
- [ ] Task 4.4: Migrate debit spreads
- [ ] Task 4.5: Update tests
- [ ] **Validation**: All existing tests pass

### Phase 5: Multi-Leg Builders
- [ ] Task 5.1: Iron condor builder
- [ ] Task 5.2: Butterfly builder
- [ ] Task 5.3: Straddle/strangle builder
- [ ] Task 5.4: Backspread builder
- [ ] **Validation**: All multi-leg strategies work

### Phase 6: Cleanup
- [ ] Task 6.1: Parity testing
- [ ] Task 6.2: Performance benchmarks
- [ ] Task 6.3: Documentation
- [ ] Task 6.4: Remove deprecated code
- [ ] **Validation**: Full test suite passes

---

## Success Criteria

1. **Single Builder for Verticals**: One `VerticalSpreadBuilder` creates all 4 spread types
2. **Parametric Control**: DTE, width, delta, OTM%, quantity all configurable
3. **Quality Scoring**: Always returns a strategy with quality score (never None)
4. **Greeks Integration**: Delta-based strike selection available
5. **Backward Compatible**: All existing tests pass
6. **Code Reduction**: ~40% fewer lines in strategy implementations
7. **Algorithm Ready**: Trident, Wheel, ML can easily compose strategies

---

## Notes

- **In-place approach chosen** over v2 parallel because existing base classes already use direction parameter pattern
- **Registry unchanged** - still uses string keys, just routes to unified implementations
- **Incremental validation** - each phase has explicit validation step before proceeding
- **Rollback safe** - if any phase fails, previous phases still work

---

**Ready to begin?** Start with Phase 1, Task 1.1: Create Type System.
