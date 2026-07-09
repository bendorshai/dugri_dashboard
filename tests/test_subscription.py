"""Tests for subscription page and Green Invoice integration.

Covers:
- Subscription page renders correctly for each subscription_status
- Subscribe flow redirects to GI payment form
- Cancel flow sets status to 'cancelled', preserves subscription_expires_at
- Webhook handler activates subscription on IPN
- Success/failure redirects show flash messages
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest


def _login(client, email="test@example.com"):
    with client.session_transaction() as sess:
        sess["user_email"] = email
        sess["user_name"] = "Test"


def _make_user(status="trial_active", **overrides):
    user = {
        "_id": "test@example.com",
        "name": "Test",
        "subscription_status": status,
        "subscription_expires_at": None,
        "subscription_token_id": None,
        "subscription_started_at": None,
        "subscription_cancelled_at": None,
        "subscription_last_charged_at": None,
        "subscription_expiry_message_sent": False,
    }
    user.update(overrides)
    return user


class TestSubscriptionPage:
    """GET /dashboard/subscription renders correct state."""

    @patch("dashboard_views.DashboardStorage")
    def test_trial_active_shows_subscribe_button(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = _make_user("trial_active")
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "14 יום ניסיון חינם".encode("utf-8") in resp.data
        assert "subscription/start".encode("utf-8") in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_trial_ended_shows_urgent_subscribe(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = _make_user("trial_ended")
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "תקופת הניסיון הסתיימה".encode("utf-8") in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_paid_shows_active_and_cancel(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = _make_user(
            "paid", subscription_expires_at="2026-07-17T00:00:00+00:00",
        )
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "מנוי פעיל".encode("utf-8") in resp.data
        assert "ביטול מנוי".encode("utf-8") in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_cancelled_shows_expiry_date(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = _make_user(
            "cancelled", subscription_expires_at="2026-07-17T00:00:00+00:00",
        )
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "המנוי בוטל".encode("utf-8") in resp.data
        assert "17/07/2026".encode("utf-8") in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_subscription_ended_shows_resubscribe(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = _make_user("subscription_ended")
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "המנוי שלך הסתיים".encode("utf-8") in resp.data


class TestSubscriptionStart:
    """POST /dashboard/subscription/start redirects to GI form."""

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_redirects_to_gi_form(self, mock_storage_cls, mock_gi_cls, client):
        mock_storage_cls.return_value.get_user.return_value = _make_user("trial_ended")
        mock_gi = MagicMock()
        mock_gi.get_payment_form_url.return_value = "https://sandbox.d.greeninvoice.co.il/form/123"
        mock_gi_cls.return_value = mock_gi
        _login(client)

        resp = client.post("/dashboard/subscription/start")
        assert resp.status_code == 302
        assert "greeninvoice" in resp.headers["Location"]
        mock_gi.get_payment_form_url.assert_called_once()

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_gi_error_shows_flash(self, mock_storage_cls, mock_gi_cls, client):
        from services.green_invoice import GreenInvoiceError
        mock_storage_cls.return_value.get_user.return_value = _make_user("trial_ended")
        mock_gi = MagicMock()
        mock_gi.get_payment_form_url.side_effect = GreenInvoiceError("fail")
        mock_gi_cls.return_value = mock_gi
        _login(client)

        resp = client.post("/dashboard/subscription/start", follow_redirects=True)
        assert resp.status_code == 200
        assert "התשלום לא הושלם".encode("utf-8") in resp.data


class TestSubscriptionCancel:
    """POST /dashboard/subscription/cancel sets status to cancelled."""

    @patch("dashboard_views.DashboardStorage")
    def test_cancel_updates_status(self, mock_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = _make_user(
            "paid", subscription_expires_at="2026-07-17T00:00:00+00:00",
        )
        mock_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/dashboard/subscription/cancel")
        assert resp.status_code == 302

        call_args = mock_storage.update_user_profile.call_args[0]
        assert call_args[0] == "test@example.com"
        assert call_args[1]["subscription_status"] == "cancelled"
        assert "subscription_cancelled_at" in call_args[1]

    @patch("dashboard_views.DashboardStorage")
    def test_cancel_ignored_if_not_paid(self, mock_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = _make_user("trial_active")
        mock_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/dashboard/subscription/cancel")
        assert resp.status_code == 302
        mock_storage.update_user_profile.assert_not_called()


class TestSubscriptionWebhook:
    """POST /dashboard/subscription/webhook handles GI IPN."""

    @patch("dashboard_views.DashboardStorage")
    def test_ipn_activates_subscription(self, mock_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = _make_user("trial_ended")
        mock_cls.return_value = mock_storage

        resp = client.post(
            "/dashboard/subscription/webhook?gi-type=ipn",
            json={"custom": "test@example.com", "tokenId": "tok_abc123"},
        )
        assert resp.status_code == 200

        call_args = mock_storage.update_user_profile.call_args[0]
        assert call_args[0] == "test@example.com"
        data = call_args[1]
        assert data["subscription_status"] == "paid"
        assert data["subscription_token_id"] == "tok_abc123"
        assert data["subscription_started_at"] is not None
        assert data["subscription_expires_at"] is not None

    @patch("dashboard_views.DashboardStorage")
    def test_non_ipn_ignored(self, mock_cls, client):
        resp = client.post(
            "/dashboard/subscription/webhook?gi-type=success",
            json={"custom": "test@example.com"},
        )
        assert resp.status_code == 200
        mock_cls.return_value.update_user_profile.assert_not_called()

    @patch("dashboard_views.DashboardStorage")
    def test_missing_email_returns_400(self, mock_cls, client):
        resp = client.post(
            "/dashboard/subscription/webhook?gi-type=ipn",
            json={"tokenId": "tok_abc"},
        )
        assert resp.status_code == 400

    @patch("dashboard_views.DashboardStorage")
    def test_unknown_user_returns_404(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = None
        resp = client.post(
            "/dashboard/subscription/webhook?gi-type=ipn",
            json={"custom": "unknown@example.com", "tokenId": "tok_abc"},
        )
        assert resp.status_code == 404


class TestSuccessFailureRedirects:
    @patch("dashboard_views.DashboardStorage")
    def test_success_redirect_flashes(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = _make_user("paid")
        _login(client)
        resp = client.get("/dashboard/subscription/success", follow_redirects=True)
        assert resp.status_code == 200
        assert "המנוי הופעל בהצלחה".encode("utf-8") in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_failure_redirect_flashes(self, mock_cls, client):
        mock_cls.return_value.get_user.return_value = _make_user("trial_ended")
        _login(client)
        resp = client.get("/dashboard/subscription/failure", follow_redirects=True)
        assert resp.status_code == 200
        assert "התשלום לא הושלם".encode("utf-8") in resp.data
