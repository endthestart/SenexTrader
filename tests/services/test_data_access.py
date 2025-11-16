"""
Tests for the data_access service.
"""

from django.contrib.auth import get_user_model

import pytest
from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.core.data_access import get_primary_tastytrade_account

User = get_user_model()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_primary_tastytrade_account_with_user_object():
    """
    Regression test to ensure get_primary_tastytrade_account
    correctly handles a User object instead of a user_id.
    """
    # 1. Create a user
    user = await sync_to_async(User.objects.create_user)(username="testuser", password="password")

    # 2. Create a primary trading account for that user
    primary_account = await TradingAccount.objects.acreate(
        user=user,
        account_number="TEST12345",
        connection_type="TASTYTRADE",
        is_primary=True,
        is_active=True,
    )

    # 3. Create a non-primary account to ensure we get the right one
    await TradingAccount.objects.acreate(
        user=user,
        account_number="TEST67890",
        connection_type="TASTYTRADE",
        is_primary=False,
        is_active=True,
    )

    # 4. Call the function with the user object
    retrieved_account = await get_primary_tastytrade_account(user)

    # 5. Assert that the correct primary account is returned
    assert retrieved_account is not None
    assert retrieved_account.id == primary_account.id
    assert retrieved_account.account_number == "TEST12345"
    assert retrieved_account.is_primary is True
