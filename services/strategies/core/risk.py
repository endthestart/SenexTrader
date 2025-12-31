"""
Risk Management Module for Strategy Trading

Provides risk classification (DEFINED vs UNDEFINED), automation eligibility,
and margin checking for trading strategies.

Risk Classification:
- DEFINED: Maximum loss is known upfront (spreads, long options)
- UNDEFINED: Potential for unlimited/undefined loss (naked shorts, short straddles)
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any


class RiskProfile(Enum):
    """Risk profile classification for trading strategies."""

    DEFINED = "defined"
    UNDEFINED = "undefined"


# Strategy to risk profile mapping
STRATEGY_RISK_MAP: dict[str, RiskProfile] = {
    # Vertical spreads - defined risk (spread width limits loss)
    "short_put_vertical": RiskProfile.DEFINED,
    "short_call_vertical": RiskProfile.DEFINED,
    "long_call_vertical": RiskProfile.DEFINED,
    "long_put_vertical": RiskProfile.DEFINED,

    # Iron condors/butterflies - defined risk
    "iron_condor": RiskProfile.DEFINED,
    "short_iron_condor": RiskProfile.DEFINED,
    "long_iron_condor": RiskProfile.DEFINED,
    "iron_butterfly": RiskProfile.DEFINED,

    # Covered positions - defined risk (stock/cash provides cover)
    "covered_call": RiskProfile.DEFINED,
    "cash_secured_put": RiskProfile.DEFINED,

    # Long options - defined risk (premium paid is max loss)
    "long_call": RiskProfile.DEFINED,
    "long_put": RiskProfile.DEFINED,
    "long_straddle": RiskProfile.DEFINED,
    "long_strangle": RiskProfile.DEFINED,

    # Calendar spreads - defined risk
    "calendar_spread": RiskProfile.DEFINED,
    "call_calendar": RiskProfile.DEFINED,
    "put_calendar": RiskProfile.DEFINED,

    # Senex Trident - defined risk (2 short put verticals + 1 short call vertical)
    "senex_trident": RiskProfile.DEFINED,

    # Naked positions - UNDEFINED risk
    "naked_call": RiskProfile.UNDEFINED,  # Unlimited upside risk
    "naked_put": RiskProfile.UNDEFINED,   # Stock can go to zero
    "short_call": RiskProfile.UNDEFINED,
    "short_put": RiskProfile.UNDEFINED,

    # Short straddles/strangles - UNDEFINED risk
    "short_straddle": RiskProfile.UNDEFINED,
    "short_strangle": RiskProfile.UNDEFINED,
    "straddle": RiskProfile.UNDEFINED,  # Default to short (more common)
    "strangle": RiskProfile.UNDEFINED,  # Default to short (more common)
}


class RiskClassifier:
    """Classifies strategies by risk profile."""

    def __init__(self, custom_mappings: dict[str, RiskProfile] | None = None):
        """Initialize with optional custom mappings."""
        self._mappings = dict(STRATEGY_RISK_MAP)
        if custom_mappings:
            self._mappings.update(custom_mappings)

    def classify(self, strategy_type: str) -> RiskProfile:
        """
        Classify a strategy type by risk profile.
        
        Args:
            strategy_type: Strategy identifier (e.g., "short_put_vertical")
            
        Returns:
            RiskProfile.DEFINED or RiskProfile.UNDEFINED
            
        Raises:
            ValueError: If strategy type is unknown
        """
        normalized = strategy_type.lower().replace("-", "_").replace(" ", "_")

        if normalized in self._mappings:
            return self._mappings[normalized]

        raise ValueError(f"Unknown strategy type: {strategy_type}")

    def is_defined_risk(self, strategy_type: str) -> bool:
        """Check if strategy has defined risk."""
        return self.classify(strategy_type) == RiskProfile.DEFINED

    def is_undefined_risk(self, strategy_type: str) -> bool:
        """Check if strategy has undefined risk."""
        return self.classify(strategy_type) == RiskProfile.UNDEFINED


@dataclass
class RiskRequirements:
    """Requirements based on risk profile."""

    risk_profile: RiskProfile

    @property
    def automation_eligible(self) -> bool:
        """Whether strategy can be automated by default."""
        return self.risk_profile == RiskProfile.DEFINED

    @property
    def requires_confirmation(self) -> bool:
        """Whether strategy requires user confirmation before execution."""
        return self.risk_profile == RiskProfile.UNDEFINED

    @property
    def requires_margin_check(self) -> bool:
        """Whether strategy requires dry_run margin check."""
        return self.risk_profile == RiskProfile.UNDEFINED

    @property
    def warning_message(self) -> str | None:
        """Warning message for undefined risk strategies."""
        if self.risk_profile == RiskProfile.UNDEFINED:
            return (
                "WARNING: This strategy has UNDEFINED risk. "
                "Potential losses may be unlimited or significantly exceed the premium received. "
                "A margin check will be performed before order submission."
            )
        return None


class AutomationEligibility:
    """Manages automation eligibility for strategies."""

    def __init__(self):
        """Initialize with default classifier."""
        self._classifier = RiskClassifier()
        self._opted_in: set[str] = set()

    def is_eligible(self, strategy_type: str) -> bool:
        """
        Check if strategy is eligible for automation.
        
        Defined risk strategies are always eligible.
        Undefined risk strategies require explicit opt-in.
        """
        normalized = strategy_type.lower().replace("-", "_").replace(" ", "_")

        # Check if opted in
        if normalized in self._opted_in:
            return True

        # Check default eligibility based on risk
        try:
            return self._classifier.is_defined_risk(normalized)
        except ValueError:
            return False

    def opt_in(self, strategy_type: str, acknowledged: bool = False) -> None:
        """
        Opt-in to automation for undefined risk strategy.
        
        Args:
            strategy_type: Strategy identifier
            acknowledged: Must be True to confirm understanding of risks
            
        Raises:
            ValueError: If acknowledgment not provided
        """
        if not acknowledged:
            raise ValueError(
                "Risk acknowledgment required: Set acknowledged=True to confirm "
                "you understand the risks of automating undefined risk strategies."
            )

        normalized = strategy_type.lower().replace("-", "_").replace(" ", "_")
        self._opted_in.add(normalized)

    def opt_out(self, strategy_type: str) -> None:
        """Opt-out of automation for a strategy."""
        normalized = strategy_type.lower().replace("-", "_").replace(" ", "_")
        self._opted_in.discard(normalized)

    def get_opted_in_strategies(self) -> set[str]:
        """Get set of strategies opted in for automation."""
        return self._opted_in.copy()


class MarginChecker:
    """Checks margin requirements using TastyTrade dry_run."""

    def __init__(self, session: Any, account: Any):
        """
        Initialize margin checker.
        
        Args:
            session: TastyTrade session
            account: TastyTrade account
        """
        self.session = session
        self.account = account

    async def check_margin(self, legs: list[Any]) -> dict[str, Any]:
        """
        Check margin requirements for order legs.
        
        Args:
            legs: List of order legs to check
            
        Returns:
            Dict with buying_power_effect, margin_requirement, is_valid, and optional rejection_reason
        """
        return await self._execute_dry_run(legs)

    async def _execute_dry_run(self, legs: list[Any]) -> dict[str, Any]:
        """
        Execute dry_run order to get margin impact.
        
        This method should be overridden or mocked in tests.
        Real implementation will call TastyTrade API.
        """
        # Placeholder - real implementation will use:
        # from tastytrade import Order
        # order = Order(legs=legs)
        # result = await self.session.place_order(self.account, order, dry_run=True)
        # return parse_dry_run_result(result)

        return {
            "buying_power_effect": Decimal("0"),
            "margin_requirement": Decimal("0"),
            "is_valid": True,
        }


def get_risk_requirements(strategy_type: str) -> RiskRequirements:
    """
    Get risk requirements for a strategy type.
    
    Convenience function combining classification and requirements.
    """
    classifier = RiskClassifier()
    risk_profile = classifier.classify(strategy_type)
    return RiskRequirements(risk_profile)
