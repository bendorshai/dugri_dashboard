"""Tests for subscription page and Green Invoice integration.

Covers:
- Subscription page renders correctly for each subscription_status
- Subscribe flow redirects to GI payment form
- Cancel flow sets status to 'cancelled', preserves subscription_expires_at
- Webhook handler activates subscription ONLY on a GI-verified payment document
  (email + amount taken from the authoritative GI document, never the IPN body),
  and always records the raw call to webhook_logs for diagnosis.
- Success/failure redirects show flash messages
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_trial_active_shows_subscribe_button(self, mock_cls, mock_gi, client):
        mock_cls.return_value.get_user.return_value = _make_user("trial_active")
        mock_gi.return_value.find_recent_receipt.return_value = None  # no reconcile
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        # No trial_expiry_at on the fixture -> falls back to the generic heading.
        assert "14 יום ניסיון חינם".encode("utf-8") in resp.data
        assert "subscription/start".encode("utf-8") in resp.data

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_trial_ended_shows_urgent_subscribe(self, mock_cls, mock_gi, client):
        mock_cls.return_value.get_user.return_value = _make_user("trial_ended")
        mock_gi.return_value.find_recent_receipt.return_value = None
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

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_subscription_ended_shows_resubscribe(self, mock_cls, mock_gi, client):
        mock_cls.return_value.get_user.return_value = _make_user("subscription_ended")
        mock_gi.return_value.find_recent_receipt.return_value = None
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "המנוי שלך הסתיים".encode("utf-8") in resp.data


class TestTrialDaysDisplay:
    """The trial heading shows days remaining, not a static '14 days'."""

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_shows_days_remaining(self, mock_cls, mock_gi, client):
        expiry = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        mock_cls.return_value.get_user.return_value = _make_user(
            "trial_active", trial_expiry_at=expiry)
        mock_gi.return_value.find_recent_receipt.return_value = None
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "נשארו לך 5 ימים".encode("utf-8") in resp.data

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_shows_last_day(self, mock_cls, mock_gi, client):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        mock_cls.return_value.get_user.return_value = _make_user(
            "trial_active", trial_expiry_at=expiry)
        mock_gi.return_value.find_recent_receipt.return_value = None
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "היום האחרון".encode("utf-8") in resp.data

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_no_expiry_falls_back_to_generic(self, mock_cls, mock_gi, client):
        # trial_pending has no trial_expiry_at -> generic heading, no crash.
        mock_cls.return_value.get_user.return_value = _make_user("trial_pending")
        mock_gi.return_value.find_recent_receipt.return_value = None
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "14 יום ניסיון חינם".encode("utf-8") in resp.data


class TestSubscriptionReconcile:
    """Non-paid users are activated by confirming a settled GI receipt, without
    relying on GI's (undelivered) IPN push."""

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_reconcile_activates_from_gi_receipt(self, mock_cls, mock_gi, client):
        storage = MagicMock()
        # get_user is called before reconcile (trial) and after (paid).
        storage.get_user.side_effect = [
            _make_user("trial_active"),
            _make_user("paid", subscription_expires_at="2026-08-20T00:00:00+00:00"),
        ]
        mock_cls.return_value = storage
        mock_gi.return_value.find_recent_receipt.return_value = {
            "id": "doc_x", "amount": 1, "client": {"emails": ["test@example.com"]},
        }
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200

        data = storage.update_user_profile.call_args[0][1]
        assert data["subscription_status"] == "paid"
        assert data["subscription_gi_document_id"] == "doc_x"
        assert data["subscription_price_paid"] == 100  # 1 shekel -> agorot
        # Page reflects the activated state.
        assert "מנוי פעיל".encode("utf-8") in resp.data

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_reconcile_skipped_for_paid_user(self, mock_cls, mock_gi, client):
        storage = MagicMock()
        storage.get_user.return_value = _make_user(
            "paid", subscription_expires_at="2026-08-20T00:00:00+00:00")
        mock_cls.return_value = storage
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        mock_gi.return_value.find_recent_receipt.assert_not_called()
        storage.update_user_profile.assert_not_called()

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_no_receipt_no_activation(self, mock_cls, mock_gi, client):
        storage = MagicMock()
        storage.get_user.return_value = _make_user("trial_active")
        mock_cls.return_value = storage
        mock_gi.return_value.find_recent_receipt.return_value = None
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        storage.update_user_profile.assert_not_called()


class TestGiEnvironmentRouting:
    """_get_gi_service routes to the sandbox vs realdeal GI account per user."""

    def test_sandbox_routes_to_sandbox_keys_and_base(self, app):
        from dashboard_views import _get_gi_service
        with app.app_context():
            svc = _get_gi_service(True)
        assert svc._api_id == "sandbox-gi-id"
        assert svc._base_url == "https://sandbox.d.greeninvoice.co.il"

    def test_realdeal_routes_to_realdeal_keys_and_base(self, app):
        from dashboard_views import _get_gi_service
        with app.app_context():
            svc = _get_gi_service(False)
        assert svc._api_id == "realdeal-gi-id"
        assert svc._base_url == "https://api.greeninvoice.co.il"

    def test_legacy_flat_config_fallback(self, app):
        from dashboard_views import _get_gi_service
        with app.app_context():
            # Simulate the pre-migration flat config shape.
            app.config["APP_CONFIG"]["green_invoice"] = {
                "api_id": "flat-id", "api_secret": "flat-secret", "sandbox": True,
                "subscription_price_ils": 1,
            }
            svc = _get_gi_service(False)
        assert svc._api_id == "flat-id"
        # Flat config carries its own sandbox bool.
        assert svc._base_url == "https://sandbox.d.greeninvoice.co.il"

    def test_user_is_sandbox_defaults_false(self):
        from dashboard_views import _user_is_sandbox
        assert _user_is_sandbox({"_id": "a@b.com"}) is False
        assert _user_is_sandbox({"_id": "a@b.com", "sandbox": True}) is True
        assert _user_is_sandbox(None) is False


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
    """POST /dashboard/subscription/webhook.

    A user is flipped to `paid` ONLY when the IPN carries a document id that
    VERIFIES against GI's authenticated API, the document's client email matches
    a known user, and its amount equals the plan price (test config price = 1).
    The untrusted IPN body is never trusted for email/amount. Every call is
    logged to webhook_logs. The endpoint always returns 200 (GI must not retry-
    storm), signalling the outcome in the JSON body.
    """

    def _doc(self, email="test@example.com", amount=1):
        return {"id": "doc_1", "amount": amount, "client": {"emails": [email]}}

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_verified_payment_activates_subscription(self, mock_cls, mock_gi, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = _make_user("trial_ended")
        mock_cls.return_value = mock_storage
        mock_gi.return_value.verify_payment.return_value = self._doc()

        resp = client.post(
            "/dashboard/subscription/webhook",
            json={"id": "doc_1", "tokenId": "tok_abc123"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "paid"

        call_args = mock_storage.update_user_profile.call_args[0]
        assert call_args[0] == "test@example.com"  # email from the GI document
        data = call_args[1]
        assert data["subscription_status"] == "paid"
        assert data["subscription_token_id"] == "tok_abc123"
        assert data["subscription_gi_document_id"] == "doc_1"
        assert data["subscription_price_paid"] == 100  # 1 shekel -> 100 agorot
        assert data["subscription_started_at"] is not None
        assert data["subscription_expires_at"] is not None
        # Raw call is always logged for diagnosis.
        mock_storage.log_webhook.assert_called_once()

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_unverifiable_ipn_does_not_activate(self, mock_cls, mock_gi, client):
        # No document id / verify returns None -> no flip, but logged + 200.
        mock_gi.return_value.verify_payment.return_value = None
        mock_storage = MagicMock()
        mock_cls.return_value = mock_storage

        resp = client.post(
            "/dashboard/subscription/webhook",
            json={"custom": "test@example.com", "tokenId": "tok_abc"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ignored"
        mock_storage.update_user_profile.assert_not_called()
        mock_storage.log_webhook.assert_called_once()

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_amount_mismatch_does_not_activate(self, mock_cls, mock_gi, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = _make_user("trial_ended")
        mock_cls.return_value = mock_storage
        # Verified doc but amount (99) != plan price (1) -> rejected.
        mock_gi.return_value.verify_payment.return_value = self._doc(amount=99)

        resp = client.post(
            "/dashboard/subscription/webhook",
            json={"id": "doc_1", "tokenId": "tok_abc"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "amount_mismatch"
        mock_storage.update_user_profile.assert_not_called()

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_unknown_user_does_not_activate(self, mock_cls, mock_gi, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_cls.return_value = mock_storage
        mock_gi.return_value.verify_payment.return_value = self._doc(email="ghost@example.com")

        resp = client.post(
            "/dashboard/subscription/webhook",
            json={"id": "doc_1", "tokenId": "tok_abc"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "user_not_found"
        mock_storage.update_user_profile.assert_not_called()


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
