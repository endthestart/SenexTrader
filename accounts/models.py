from datetime import timedelta

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from encrypted_model_fields.fields import EncryptedTextField

from services.core.exceptions import MissingSecretError, TokenExpiredError


class User(AbstractUser):
    email = models.EmailField(unique=True, verbose_name="Email Address")
    first_name = models.CharField(max_length=30, verbose_name="First Name")
    last_name = models.CharField(max_length=30, verbose_name="Last Name")

    email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "first_name", "last_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def email_preference(self):
        return self.preferences.email_preference

    @email_preference.setter
    def email_preference(self, value):
        self.preferences.email_preference = value
        self.preferences.save(update_fields=["email_preference"])

    @property
    def email_daily_trade_suggestion(self):
        return self.preferences.email_daily_trade_suggestion

    @email_daily_trade_suggestion.setter
    def email_daily_trade_suggestion(self, value):
        self.preferences.email_daily_trade_suggestion = value
        self.preferences.save(update_fields=["email_daily_trade_suggestion"])


class UserPreferences(models.Model):
    EMAIL_PREFERENCE_CHOICES = [
        ("none", "No Emails"),
        ("immediate", "Emails for All Activity"),
        ("summary", "Summary Email End of Day"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")

    email_preference = models.CharField(
        max_length=20,
        choices=EMAIL_PREFERENCE_CHOICES,
        default="summary",
        help_text="Email notification preference for trading activity",
    )
    email_daily_trade_suggestion = models.BooleanField(
        default=False,
        help_text="Send daily trade suggestion email at 10:00 AM ET (market open)",
    )
    privacy_mode = models.BooleanField(
        default=False,
        help_text="Hide account balance on dashboard when enabled",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Preferences"
        verbose_name_plural = "User Preferences"

    def __str__(self):
        return f"{self.user.email} - Preferences"


class TradingAccountPreferences(models.Model):
    account = models.OneToOneField(
        "TradingAccount", on_delete=models.CASCADE, related_name="trading_preferences"
    )

    is_automated_trading_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Enable daily automated trading for this account " "(executes 30 min after market open)"
        ),
    )
    automated_entry_offset_cents = models.PositiveIntegerField(
        default=0,
        help_text="Limit price offset (in cents) when automation submits credit trades",
    )
    auto_profit_targets_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Automatically create profit target orders when spread positions open. "
            "Does not affect Senex Trident which always uses its own algorithm."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Trading Account Preferences"
        verbose_name_plural = "Trading Account Preferences"

    def __str__(self):
        return f"{self.account.account_number} - Trading Preferences"


class TradingAccount(models.Model):
    CONNECTION_TYPES = [
        ("TASTYTRADE", "TastyTrade"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trading_accounts")
    connection_type = models.CharField(
        max_length=20, choices=CONNECTION_TYPES, default="TASTYTRADE"
    )

    account_number = models.CharField(max_length=50)
    account_nickname = models.CharField(max_length=100, blank=True)

    # TODO: access_token field is unused and can be removed.
    # We always use the TastyTrade SDK which takes refresh_token and internally
    # calls /oauth/token to get a fresh access_token (which it renames to session_token).
    # We never make direct API calls - the SDK handles everything.
    # The only reason we store access_token is historical; is_configured checks it
    # but should check refresh_token instead. See: 2025-12-03 security review.
    access_token = EncryptedTextField(blank=True)
    refresh_token = EncryptedTextField(blank=True)
    # NOTE: token_type removed - always "Bearer" in OAuth 2.0
    # NOTE: scope removed - never used
    token_expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    is_active = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    is_test = models.BooleanField(
        default=False,
        help_text=(
            "Use TastyTrade sandbox environment instead of production. "
            "Requires separate OAuth credentials for sandbox accounts. "
            "All orders are executed normally in the selected environment."
        ),
    )
    is_token_valid = models.BooleanField(
        default=True,
        help_text="Whether refresh token is valid - False means user needs to re-authenticate",
    )

    last_authenticated = models.DateTimeField(null=True, blank=True)
    # NOTE: token_refresh_count removed - unused telemetry
    # NOTE: last_token_rotation removed - unused telemetry
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["user", "account_number", "connection_type"]
        indexes = [
            models.Index(fields=["user", "is_primary"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __init__(self, *args, **kwargs):
        self._pending_trading_pref_updates: dict[str, int | bool] = {}
        self._extract_trading_pref_kwargs(kwargs)
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} - {self.account_number} ({self.connection_type})"

    def save(self, *args, **kwargs):
        if self.is_primary:
            TradingAccount.objects.filter(
                user=self.user, connection_type=self.connection_type, is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)
        self._apply_pending_trading_preferences()

    @property
    def is_configured(self) -> bool:
        return bool(self.account_number and self.access_token)

    @property
    def is_automated_trading_enabled(self):
        pending = getattr(self, "_pending_trading_pref_updates", {})
        if not self.pk and "is_automated_trading_enabled" in pending:
            return pending["is_automated_trading_enabled"]
        prefs = self._ensure_trading_preferences(auto_create=self.pk is not None)
        if prefs:
            return prefs.is_automated_trading_enabled
        return False

    @is_automated_trading_enabled.setter
    def is_automated_trading_enabled(self, value):
        self._set_trading_pref_value("is_automated_trading_enabled", value)

    @property
    def automated_entry_offset_cents(self):
        pending = getattr(self, "_pending_trading_pref_updates", {})
        if not self.pk and "automated_entry_offset_cents" in pending:
            return pending["automated_entry_offset_cents"]
        prefs = self._ensure_trading_preferences(auto_create=self.pk is not None)
        if prefs:
            return prefs.automated_entry_offset_cents
        return 0

    @automated_entry_offset_cents.setter
    def automated_entry_offset_cents(self, value):
        self._set_trading_pref_value("automated_entry_offset_cents", value)

    @property
    def privacy_mode(self):
        return self.user.preferences.privacy_mode

    @privacy_mode.setter
    def privacy_mode(self, value):
        self.user.preferences.privacy_mode = value
        self.user.preferences.save(update_fields=["privacy_mode"])

    def should_refresh_token(self) -> bool:
        if not self.token_expires_at:
            return False
        return timezone.now() >= (self.token_expires_at - timedelta(minutes=5))

    def rotate_refresh_token(
        self,
        new_access_token: str,
        new_refresh_token: str,
        expires_in_seconds: int | None = None,
    ):
        """Rotate tokens with new values, encrypt them, and save to database."""
        self.access_token = new_access_token
        if new_refresh_token:
            self.refresh_token = new_refresh_token
        if expires_in_seconds:
            self.token_expires_at = timezone.now() + timedelta(seconds=expires_in_seconds)
        self.save()

    def get_oauth_session(self):
        """
        Get fresh OAuth session for TastyTrade streaming.

        CRITICAL: Always calls session.refresh() to fix the 15-minute token
        expiry issue.
        This is the root fix for streaming failures identified in POC documentation.

        NOTE: We do NOT cache the session object itself because it contains
        thread locks that cannot be pickled. Creating a fresh session is fast
        and ensures we always have valid credentials.
        """
        from django.conf import settings

        from tastytrade import Session

        if not self.refresh_token:
            raise TokenExpiredError(user_id=self.user_id)

        # Create new session with production credentials
        provider_secret = getattr(settings, "TASTYTRADE_CLIENT_SECRET", None)
        if not provider_secret:
            raise MissingSecretError("TASTYTRADE_CLIENT_SECRET")

        session = Session(
            provider_secret=provider_secret,
            refresh_token=self.refresh_token,
            is_test=self.is_test,
        )

        # CRITICAL FIX: Always refresh to get fresh access token
        # This solves the "OAuth session expired" streaming failures
        session.refresh()

        self.last_authenticated = timezone.now()
        self.save(update_fields=["last_authenticated"])

        return session

    def _extract_trading_pref_kwargs(self, kwargs):
        pref_fields = ("is_automated_trading_enabled", "automated_entry_offset_cents")
        for field in pref_fields:
            if field in kwargs:
                self._pending_trading_pref_updates[field] = kwargs.pop(field)

    def _apply_pending_trading_preferences(self):
        if not getattr(self, "_pending_trading_pref_updates", None):
            return
        if not self.pk:
            return
        prefs = self._ensure_trading_preferences(auto_create=True)
        if not prefs:
            return
        update_fields = []
        for field, value in self._pending_trading_pref_updates.items():
            setattr(prefs, field, value)
            update_fields.append(field)
        if update_fields:
            prefs.save(update_fields=update_fields)
        self._pending_trading_pref_updates.clear()

    def _queue_trading_pref_update(self, field: str, value):
        if not hasattr(self, "_pending_trading_pref_updates"):
            self._pending_trading_pref_updates = {}
        self._pending_trading_pref_updates[field] = value

    def _set_trading_pref_value(self, field: str, value):
        if not self.pk:
            self._queue_trading_pref_update(field, value)
            return
        prefs = self._ensure_trading_preferences(auto_create=True)
        if not prefs:
            return
        setattr(prefs, field, value)
        prefs.save(update_fields=[field])

    def _ensure_trading_preferences(self, auto_create: bool = False):
        try:
            return self.trading_preferences
        except TradingAccountPreferences.DoesNotExist:
            if not auto_create or not self.pk:
                return None
        prefs, _created = TradingAccountPreferences.objects.get_or_create(
            account=self,
            defaults={
                "is_automated_trading_enabled": False,
                "automated_entry_offset_cents": 0,
            },
        )
        return prefs


class OptionsAllocation(models.Model):
    """User's risk management settings - Enhanced version with templates"""

    ALLOCATION_METHODS = [
        ("conservative", "Conservative (40% Risk Tolerance)"),
        ("moderate", "Moderate (50% Risk Tolerance)"),
        ("aggressive", "Aggressive (60% Risk Tolerance)"),
        ("user_defined", "User Defined Risk Tolerance"),
    ]

    # Risk Tolerance Templates
    RISK_TOLERANCE_TEMPLATES = {
        "conservative": {
            "normal_tolerance": 0.40,
            "stressed_tolerance": 0.60,
            "warning_threshold_high": 0.80,
            "warning_threshold_medium": 0.65,
        },
        "moderate": {
            "normal_tolerance": 0.50,
            "stressed_tolerance": 0.70,
            "warning_threshold_high": 0.85,
            "warning_threshold_medium": 0.70,
        },
        "aggressive": {
            "normal_tolerance": 0.60,
            "stressed_tolerance": 0.80,
            "warning_threshold_high": 0.90,
            "warning_threshold_medium": 0.75,
        },
    }

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="options_allocation")

    # Core settings
    allocation_method = models.CharField(
        max_length=20, choices=ALLOCATION_METHODS, default="conservative"
    )

    # Risk tolerance (percentage of tradeable capital)
    risk_tolerance = models.FloatField(
        default=0.40,  # 40% conservative
        validators=[MinValueValidator(0.01), MaxValueValidator(0.80)],
        help_text="Normal market risk tolerance (0.01-0.80)",
    )
    stressed_risk_tolerance = models.FloatField(
        default=0.60,  # 60% stressed
        validators=[MinValueValidator(0.01), MaxValueValidator(0.80)],
        help_text="Stressed market risk tolerance (0.01-0.80)",
    )

    # Risk warning thresholds (percentage of strategy power)
    warning_threshold_high = models.FloatField(
        default=0.80,
        validators=[MinValueValidator(0.50), MaxValueValidator(0.95)],
        help_text="High warning threshold for risk utilization (0.50-0.95)",
    )
    warning_threshold_medium = models.FloatField(
        default=0.65,
        validators=[MinValueValidator(0.40), MaxValueValidator(0.90)],
        help_text="Medium warning threshold for risk utilization (0.40-0.90)",
    )

    # Calculated values (cached for performance)
    strategy_power = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Risk Budget: Risk Tolerance × Tradeable Capital",
    )

    last_calculated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.get_allocation_method_display()}"

    def calculate_strategy_max(self):
        """
        Calculate Strategy Max: Stressed Risk Tolerance × Tradeable Capital
        Used when market is stressed to capture higher premiums
        """
        from decimal import Decimal

        from services.risk.manager import EnhancedRiskManager

        risk_manager = EnhancedRiskManager(self.user)
        tradeable_capital, is_available = risk_manager.get_tradeable_capital()

        if not is_available:
            return Decimal("0")

        return tradeable_capital * Decimal(str(self.stressed_risk_tolerance))


class AccountSnapshot(models.Model):
    """Periodic snapshots of account state for audit and analytics"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="account_snapshots")
    account_number = models.CharField(max_length=20)

    # Account state at snapshot time
    buying_power = models.DecimalField(
        max_digits=15, decimal_places=2, help_text="Available buying power"
    )
    balance = models.DecimalField(
        max_digits=15, decimal_places=2, help_text="Total account balance"
    )
    source = models.CharField(
        max_length=20,
        choices=[
            ("stream", "Real-time stream"),
            ("sdk", "Direct SDK call"),
            ("manual", "Manual entry"),
        ],
        default="sdk",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "account_number", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.account_number} - {self.created_at}"
