from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from django.conf import settings
from django.utils import timezone as django_timezone

from services.core.utils.decimal_utils import to_decimal

DEFAULT_MAX_AGE = getattr(settings, "SENEX_PRICING_MAX_AGE", 60)


@dataclass(slots=True)
class UnderlyingSnapshot:
    symbol: str
    last: Decimal | None
    reference: Decimal | None
    as_of: datetime
    source: str = "dxfeed_stream"

    @classmethod
    def from_cache(cls, symbol: str, payload: dict) -> UnderlyingSnapshot:
        timestamp = payload.get("updated_at") or payload.get("timestamp")
        if isinstance(timestamp, str):
            try:
                parsed = datetime.fromisoformat(timestamp)
            except ValueError:
                parsed = django_timezone.now()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = django_timezone.now()
        return cls(
            symbol=symbol,
            last=to_decimal(payload.get("last")),
            reference=to_decimal(payload.get("reference")),
            as_of=parsed,
            source=payload.get("source", "dxfeed_stream"),
        )

    @property
    def age_seconds(self) -> float:
        return (django_timezone.now() - self.as_of).total_seconds()

    @property
    def is_fresh(self) -> bool:
        return self.age_seconds <= DEFAULT_MAX_AGE


@dataclass(slots=True)
class SenexOccBundle:
    underlying: str
    expiration: datetime
    legs: dict[str, str] = field(default_factory=dict)

    def add_leg(self, label: str, occ_symbol: str) -> None:
        self.legs[label] = occ_symbol

    @property
    def leg_symbols(self) -> list[str]:
        return list(self.legs.values())

    @property
    def put_symbols(self) -> list[str]:
        return [
            self.legs[key]
            for key in ("put_short", "put_long", "put_short_2", "put_long_2")
            if key in self.legs
        ]

    @property
    def call_symbols(self) -> list[str]:
        return [self.legs[key] for key in ("call_short", "call_long") if key in self.legs]

    def to_dict(self) -> dict:
        """Serializes the bundle to a dictionary for channel layer transport."""
        return {
            "underlying": self.underlying,
            "expiration": self.expiration.isoformat(),
            "legs": self.legs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SenexOccBundle:
        """Deserializes a dictionary back into a SenexOccBundle instance."""

        return cls(
            underlying=data["underlying"],
            expiration=datetime.fromisoformat(data["expiration"]).date(),
            legs=data["legs"],
        )

    def symbol_for(self, label: str) -> str | None:
        return self.legs.get(label)


@dataclass(slots=True)
class SenexPricing:
    # Natural credit (conservative for risk calculations)
    put_credit: Decimal
    call_credit: Decimal
    total_credit: Decimal

    # Mid-price credit (realistic pricing for UI display)
    put_mid_credit: Decimal
    call_mid_credit: Decimal
    total_mid_credit: Decimal

    # Raw quote data for accurate UI display
    snapshots: dict[str, dict]
    source: str = "dxfeed_stream"
    last_updated: datetime = field(default_factory=django_timezone.now)

    # Service metadata (previously in PricingResult)
    has_real_pricing: bool = True

    @property
    def latency_ms(self) -> int:
        if not self.snapshots:
            return 0  # No data available, assume zero latency for testing
        newest = max(_parse_timestamp(data) for data in self.snapshots.values())
        delta = django_timezone.now() - newest
        return int(delta.total_seconds() * 1000)

    @property
    def is_fresh(self) -> bool:
        return self.latency_ms <= DEFAULT_MAX_AGE * 1000


@dataclass(slots=True)
class OptionGreeks:
    """
    Option Greeks snapshot from streaming data.

    Epic 28 Task 008: Greeks data for risk analysis and strategy scoring.
    """

    occ_symbol: str
    delta: Decimal | None
    gamma: Decimal | None
    theta: Decimal | None
    vega: Decimal | None
    rho: Decimal | None
    implied_volatility: Decimal | None
    as_of: datetime
    source: str = "dxfeed_stream"

    @classmethod
    def from_cache(cls, occ_symbol: str, payload: dict) -> OptionGreeks:
        """Create OptionGreeks from cached payload."""
        timestamp = payload.get("updated_at") or payload.get("timestamp")
        if isinstance(timestamp, str):
            try:
                parsed = datetime.fromisoformat(timestamp)
            except ValueError:
                parsed = django_timezone.now()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = django_timezone.now()

        return cls(
            occ_symbol=occ_symbol,
            delta=to_decimal(payload.get("delta")),
            gamma=to_decimal(payload.get("gamma")),
            theta=to_decimal(payload.get("theta")),
            vega=to_decimal(payload.get("vega")),
            rho=to_decimal(payload.get("rho")),
            implied_volatility=to_decimal(payload.get("volatility")),  # SDK calls it 'volatility'
            as_of=parsed,
            source=payload.get("source", "dxfeed_stream"),
        )

    @property
    def age_seconds(self) -> float:
        """Calculate age in seconds."""
        return (django_timezone.now() - self.as_of).total_seconds()

    @property
    def is_fresh(self) -> bool:
        """Check if Greeks data is fresh (within max age)."""
        return self.age_seconds <= DEFAULT_MAX_AGE


def _parse_timestamp(payload: dict) -> datetime:
    raw = payload.get("updated_at") or payload.get("timestamp")
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            dt = django_timezone.now()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    return django_timezone.now()
