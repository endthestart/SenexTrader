"""Tests for automated trading API endpoints."""

import json

from django.urls import reverse

import pytest

from accounts.models import TradingAccount


@pytest.mark.django_db
def test_toggle_updates_offset_and_state(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="auto",
        email="auto@example.com",
        password="secret123",
    )
    client.force_login(user)

    account = TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="ACC1",
        is_active=True,
        is_primary=True,
        is_automated_trading_enabled=False,
        automated_entry_offset_cents=0,
    )

    response = client.post(
        reverse("accounts:api_automated_trading_toggle"),
        data=json.dumps({"is_enabled": True, "offset_cents": 4}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["is_enabled"] is True
    assert payload["offset_cents"] == 4

    account.refresh_from_db()
    assert account.is_automated_trading_enabled is True
    assert account.automated_entry_offset_cents == 4


@pytest.mark.django_db
def test_offset_update_without_toggle_preserves_state(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="auto2",
        email="auto2@example.com",
        password="secret123",
    )
    client.force_login(user)

    account = TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="ACC2",
        is_active=True,
        is_primary=True,
        is_automated_trading_enabled=True,
        automated_entry_offset_cents=2,
    )

    response = client.post(
        reverse("accounts:api_automated_trading_toggle"),
        data=json.dumps({"offset_cents": 5}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_enabled"] is True
    assert payload["offset_cents"] == 5

    account.refresh_from_db()
    assert account.is_automated_trading_enabled is True
    assert account.automated_entry_offset_cents == 5


@pytest.mark.django_db
def test_invalid_offset_rejected(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="auto3",
        email="auto3@example.com",
        password="secret123",
    )
    client.force_login(user)

    TradingAccount.objects.create(
        user=user,
        connection_type="TASTYTRADE",
        account_number="ACC3",
        is_active=True,
        is_primary=True,
        is_automated_trading_enabled=True,
        automated_entry_offset_cents=0,
    )

    response = client.post(
        reverse("accounts:api_automated_trading_toggle"),
        data=json.dumps({"offset_cents": 40}),
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "offset_cents" in payload["error"].lower()
