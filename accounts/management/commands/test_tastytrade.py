"""
Management command to test TastyTrade connection and account data retrieval.
"""

# ruff: noqa: PLC0415, RUF001, PLR0912

from django.contrib.auth import get_user_model
from django.utils import timezone as dj_timezone

from accounts.models import TradingAccount
from services.account.state import AccountStateService
from services.brokers.tastytrade.session import TastyTradeSessionService
from services.management.utils import AsyncCommand, add_user_arguments, aget_user_from_options

User = get_user_model()


class Command(AsyncCommand):
    help = "Test TastyTrade connection and account data retrieval"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=True)

    async def async_handle(self, *args, **options):
        # Get user using utility function
        user = await aget_user_from_options(options, require_user=True)

        self.stdout.write(self.style.SUCCESS(f"\n{'=' * 60}"))
        self.stdout.write(self.style.SUCCESS(" TastyTrade Connection Test"))
        self.stdout.write(self.style.SUCCESS(f"{'=' * 60}"))
        self.stdout.write(f"Testing user: {user.email}")
        self.stdout.write(f"Timestamp: {dj_timezone.now()}\n")

        # Run the tests
        await self.run_tests(user)

    async def test_user_lookup(self, user):
        """Test 1: Verify user"""
        self.stdout.write(self.style.WARNING("\nTEST 1: User Verification"))
        self.stdout.write(f"User: {user.email}")
        self.stdout.write(self.style.SUCCESS(f"✅ User verified: {user.email} (ID: {user.id})"))
        return user

    async def test_trading_account(self, user):
        """Test 2: Check TradingAccount configuration"""
        self.stdout.write(self.style.WARNING("\nTEST 2: Trading Account Configuration"))

        if not user:
            self.stdout.write(self.style.ERROR("❌ No user provided"))
            return None

        try:
            from asgiref.sync import sync_to_async

            trading_account = await sync_to_async(
                TradingAccount.objects.filter(
                    user=user, is_primary=True, connection_type="TASTYTRADE"
                ).first
            )()

            if not trading_account:
                self.stdout.write(self.style.ERROR("❌ No primary TastyTrade account found"))
                return None

            self.stdout.write(
                self.style.SUCCESS(f"✅ Found trading account: {trading_account.account_number}")
            )
            self.stdout.write(f"   - Nickname: {getattr(trading_account, 'nickname', 'N/A')}")
            self.stdout.write(f"   - Is Primary: {trading_account.is_primary}")
            self.stdout.write(f"   - Connection Type: {trading_account.connection_type}")

            if trading_account.refresh_token:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ Refresh token exists (length: "
                        f"{len(trading_account.refresh_token)})"
                    )
                )
            else:
                self.stdout.write(self.style.ERROR("❌ No refresh token found"))
                return None

            return trading_account

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error checking trading account: {e}"))
            return None

    def test_oauth_session(self, trading_account):
        """Test 3: Create OAuth session"""
        self.stdout.write(self.style.WARNING("\nTEST 3: OAuth Session Creation"))

        if not trading_account:
            self.stdout.write(self.style.ERROR("❌ No trading account provided"))
            return None

        try:
            session_service = TastyTradeSessionService()
            self.stdout.write("ℹ️  TastyTradeSessionService created")

            session_result = session_service.create_session(trading_account.refresh_token)

            if session_result.get("success"):
                self.stdout.write(self.style.SUCCESS("✅ OAuth session created successfully"))
                session = session_result.get("session")
                self.stdout.write(f"   - Session type: {type(session).__name__}")
                return session
            self.stdout.write(
                self.style.ERROR(
                    f"❌ OAuth session creation failed: " f"{session_result.get('error')}"
                )
            )
            return None

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error creating OAuth session: {e}"))
            return None

    async def test_account_data_fetch(self, session, account_number):
        """Test 4: Fetch account data via TastyTrade SDK"""
        self.stdout.write(self.style.WARNING("\nTEST 4: Account Data Fetch"))

        if not session:
            self.stdout.write(self.style.ERROR("❌ No session provided"))
            return None

        try:
            from tastytrade import Account as TTAccount

            self.stdout.write(f"ℹ️  Attempting to fetch account: {account_number}")

            # Try async method first
            try:
                account = await TTAccount.a_get(session, account_number)
                self.stdout.write(self.style.SUCCESS("✅ Account fetched via async method"))
            except AttributeError:
                # Fallback to sync method
                self.stdout.write("ℹ️  Async method not available, trying sync...")
                account = TTAccount.get(session, account_number)
                self.stdout.write(self.style.SUCCESS("✅ Account fetched via sync method"))

            if isinstance(account, list):
                account = account[0] if account else None

            if not account:
                self.stdout.write(self.style.ERROR("❌ No account returned"))
                return None

            self.stdout.write(
                self.style.SUCCESS(f"✅ Account object retrieved: {type(account).__name__}")
            )
            self.stdout.write(f"   - Account number: {getattr(account, 'account_number', 'N/A')}")

            return account

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error fetching account data: {e}"))
            return None

    async def test_balance_fetch(self, session, account, account_number):
        """Test 5: Fetch balance and buying power"""
        self.stdout.write(self.style.WARNING("\nTEST 5: Balance and Buying Power Fetch"))

        if not session or not account:
            self.stdout.write(self.style.ERROR("❌ No session or account provided"))
            return None

        try:
            balances = None

            # Method 1: Account instance method
            if hasattr(account, "a_get_balances"):
                try:
                    balances = await account.a_get_balances(session)
                    self.stdout.write(
                        self.style.SUCCESS("✅ Balances fetched via account.a_get_balances()")
                    )
                except Exception as e:
                    self.stdout.write(f"ℹ️  account.a_get_balances() failed: {e}")

            # Method 2: Account class method
            if not balances and hasattr(account.__class__, "a_get_balances"):
                try:
                    balances = await account.__class__.a_get_balances(session, account_number)
                    self.stdout.write(
                        self.style.SUCCESS("✅ Balances fetched via Account.a_get_balances()")
                    )
                except Exception as e:
                    self.stdout.write(f"ℹ️  Account.a_get_balances() failed: {e}")

            # Method 3: Sync method with sync_to_async
            if not balances and hasattr(account, "get_balances"):
                try:
                    from asgiref.sync import sync_to_async

                    balances = await sync_to_async(account.get_balances)(session)
                    self.stdout.write(
                        self.style.SUCCESS(
                            "✅ Balances fetched via sync_to_async(account.get_balances)"
                        )
                    )
                except Exception as e:
                    self.stdout.write(f"ℹ️  sync_to_async(account.get_balances) failed: {e}")

            if not balances:
                self.stdout.write(self.style.ERROR("❌ No balances returned from any method"))
                return None

            # Extract key financial data
            buying_power = getattr(balances, "buying_power", None)
            net_liquidating_value = getattr(balances, "net_liquidating_value", None)

            self.stdout.write(self.style.SUCCESS("✅ Balance data retrieved:"))
            if buying_power:
                self.stdout.write(f"   - Buying Power: ${buying_power:,.2f}")
            else:
                self.stdout.write("   - Buying Power: N/A")

            if net_liquidating_value:
                self.stdout.write(f"   - Net Liquidating Value: ${net_liquidating_value:,.2f}")
            else:
                self.stdout.write("   - Net Liquidating Value: N/A")

            return {
                "buying_power": float(buying_power) if buying_power else None,
                "balance": (float(net_liquidating_value) if net_liquidating_value else None),
                "balances_object": balances,
            }

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error fetching balances: {e}"))
            return None

    def test_account_state_service(self, user):
        """Test 6: AccountStateService integration"""
        self.stdout.write(self.style.WARNING("\nTEST 6: AccountStateService Integration"))

        if not user:
            self.stdout.write(self.style.ERROR("❌ No user provided"))
            return None

        try:
            service = AccountStateService()
            self.stdout.write("ℹ️  AccountStateService created")

            # Get account state
            state = service.get(user)

            self.stdout.write("ℹ️  Account state response:")
            self.stdout.write(f"   - Available: {state.get('available', False)}")
            self.stdout.write(f"   - Source: {state.get('source', 'unknown')}")
            self.stdout.write(f"   - Stale: {state.get('stale', True)}")

            if state.get("available") and state.get("buying_power") is not None:
                self.stdout.write(self.style.SUCCESS("✅ AccountStateService working!"))
                self.stdout.write(f"   - Buying Power: ${state['buying_power']:,.2f}")
                if state.get("balance"):
                    self.stdout.write(f"   - Balance: ${state['balance']:,.2f}")
            else:
                self.stdout.write(
                    self.style.ERROR("❌ AccountStateService not returning valid data")
                )
                if "error" in state:
                    self.stdout.write(self.style.ERROR(f"   - Error: {state['error']}"))

            return state

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error testing AccountStateService: {e}"))
            return None

    async def run_tests(self, user):
        """Run complete test suite"""
        # Test 1: User verification
        user = await self.test_user_lookup(user)
        if not user:
            return

        # Test 2: Trading account
        trading_account = await self.test_trading_account(user)
        if not trading_account:
            return

        # Test 3: OAuth session
        session = self.test_oauth_session(trading_account)
        if not session:
            return

        # Test 4: Account data fetch
        account = await self.test_account_data_fetch(session, trading_account.account_number)
        if not account:
            return

        # Test 5: Balance fetch
        balance_data = await self.test_balance_fetch(
            session, account, trading_account.account_number
        )
        if not balance_data:
            return

        # Test 6: AccountStateService
        state = self.test_account_state_service(user)

        # Summary
        self.stdout.write(self.style.SUCCESS(f"\n{'=' * 60}"))
        self.stdout.write(self.style.SUCCESS(" TEST SUMMARY"))
        self.stdout.write(self.style.SUCCESS(f"{'=' * 60}"))

        if balance_data and state and state.get("available"):
            self.stdout.write(self.style.SUCCESS("🎉 ALL TESTS PASSED!"))
            self.stdout.write(self.style.SUCCESS("TastyTrade connection is working correctly"))
            if balance_data.get("buying_power"):
                self.stdout.write(f"💰 Buying Power: ${balance_data['buying_power']:,.2f}")
        else:
            self.stdout.write(self.style.ERROR("❌ SOME TESTS FAILED"))
            self.stdout.write(self.style.ERROR("TastyTrade connection needs debugging"))
