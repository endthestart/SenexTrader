"""Management command to manually trigger automated trading workflow."""

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import TradingAccount
from services.management.utils import AsyncCommand, aget_user_from_options
from trading.models import Trade
from trading.services.automated_trading_service import AutomatedTradingService

User = get_user_model()


class Command(AsyncCommand):
    help = "Manually trigger automated trading workflow for specific user(s)"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--user", type=str, help="User email address")
        group.add_argument("--user-id", type=int, help="User ID")
        group.add_argument("--all", action="store_true", help="Process all eligible users")

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without executing",
        )

    async def async_handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No trades will be executed"))

        if options["all"]:
            users = await self._get_all_eligible_users()
            self.stdout.write(f"Found {len(users)} eligible user(s)")
        else:
            users = [await self._get_single_user(options)]

        if not users:
            raise CommandError("No eligible users found")

        service = AutomatedTradingService()
        results = {"succeeded": 0, "failed": 0, "skipped": 0}

        try:
            for user in users:
                self.stdout.write("\n" + "=" * 60)
                self.stdout.write(f"Processing: {user.email} (ID: {user.id})")
                self.stdout.write("=" * 60)

                account = await self._get_eligible_account(user)
                if not account:
                    self.stdout.write(self.style.WARNING("User not eligible"))
                    results["skipped"] += 1
                    continue

                today = timezone.now().date()
                if (
                    await Trade.objects.filter(
                        user=user,
                        submitted_at__date=today,
                    )
                    .exclude(status__in=["cancelled", "rejected", "expired"])
                    .aexists()
                ):
                    self.stdout.write(self.style.WARNING("Already has trade today"))
                    results["skipped"] += 1
                    continue

                if dry_run:
                    self.stdout.write(self.style.SUCCESS("Would process automated trade"))
                    continue

                result = await service.a_process_account(account)
                self._display_result(result)

                status = result.get("status")
                if status == "success":
                    results["succeeded"] += 1
                elif status == "skipped":
                    results["skipped"] += 1
                else:
                    results["failed"] += 1
        finally:
            from streaming.services.stream_manager import GlobalStreamManager

            for user in users:
                await GlobalStreamManager.remove_user_manager(user.id)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Succeeded: {results['succeeded']}")
        self.stdout.write(f"Skipped: {results['skipped']}")
        self.stdout.write(f"Failed: {results['failed']}")

    async def _get_single_user(self, options):
        return await aget_user_from_options(
            options, require_user=True, allow_superuser_fallback=False
        )

    async def _get_all_eligible_users(self):
        accounts = TradingAccount.objects.filter(
            is_active=True,
            trading_preferences__is_automated_trading_enabled=True,
        ).select_related("user", "trading_preferences")
        return [account.user async for account in accounts]

    async def _get_eligible_account(self, user):
        return (
            await TradingAccount.objects.filter(
                user=user,
                is_primary=True,
                is_active=True,
                trading_preferences__is_automated_trading_enabled=True,
            )
            .select_related("user", "trading_preferences")
            .afirst()
        )

    def _display_result(self, result):
        status = result.get("status")
        if status == "success":
            self.stdout.write(self.style.SUCCESS("Success!"))
            self.stdout.write(f"   Symbol: {result.get('symbol')}")
            self.stdout.write(f"   Suggestion ID: {result.get('suggestion_id')}")
            self.stdout.write(f"   Position ID: {result.get('position_id')}")
        elif status == "skipped":
            reason = result.get("reason", "unknown")
            self.stdout.write(self.style.WARNING(f"Skipped: {reason}"))
        else:
            reason = result.get("reason", "unknown")
            self.stdout.write(self.style.ERROR(f"Failed: {reason}"))
