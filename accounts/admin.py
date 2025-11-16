from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import TradingAccount, TradingAccountPreferences, UserPreferences

User = get_user_model()


class UserPreferencesInline(admin.StackedInline):
    model = UserPreferences
    can_delete = False
    verbose_name_plural = "Preferences"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "username",
        "first_name",
        "last_name",
        "is_staff",
        "email_verified",
        "created_at",
    )
    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "email_verified",
        "created_at",
    )
    search_fields = ("email", "username", "first_name", "last_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Email Verification",
            {"fields": ("email_verified", "email_verification_token")},
        ),
        (
            "Important dates",
            {"fields": ("last_login", "date_joined", "created_at", "updated_at")},
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "first_name",
                    "last_name",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    readonly_fields = ("created_at", "updated_at")
    inlines = [UserPreferencesInline]


class TradingAccountPreferencesInline(admin.StackedInline):
    model = TradingAccountPreferences
    can_delete = False
    verbose_name_plural = "Trading Preferences"


@admin.register(TradingAccount)
class TradingAccountAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "account_number",
        "connection_type",
        "is_primary",
        "is_active",
        "last_authenticated",
    )
    list_filter = ("connection_type", "is_primary", "is_active", "created_at")
    search_fields = ("user__email", "account_number", "account_nickname")
    readonly_fields = ("created_at", "updated_at", "last_authenticated")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "connection_type",
                    "account_number",
                    "account_nickname",
                )
            },
        ),
        ("Status", {"fields": ("is_active", "is_primary")}),
        ("Timestamps", {"fields": ("last_authenticated", "created_at", "updated_at")}),
    )
    inlines = [TradingAccountPreferencesInline]
