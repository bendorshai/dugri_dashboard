"""Tests for the monthly renewal charge loop (/internal/run-due-charges).

Money-safety spec:
- The endpoint is secret-protected and GATED by config renewals_enabled (off by
  default) - inert until explicitly enabled.
- A due user is charged at most once per billing period via an atomic claim.
- Success advances next_bill_at (anchor-based) and writes a success ledger row.
- Failure writes a failed ledger row, increments retry, and after MAX_CHARGE_RETRIES
  ends the subscription; a charge-failed message is sent to the bot.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def _due_user(**overrides):
    u = {
        "_id": "test@example.com",
        "telegram_user_id": 42,
        "subscription_status": "paid",
        "subscription_token_id": "tok_live",
        "subscription_anchor_day": 15,
        "next_bill_at": "2026-08-15T00:00:00+00:00",
        "charge_retry_count": 0,
        "subscription_charge_failed_message_sent": False,
    }
    u.update(overrides)
    return u


class TestRunDueChargesGate:
    @patch("dashboard_views.DashboardStorage")
    def test_unauthorized_without_secret(self, mock_cls, client, app):
        app.config["APP_CONFIG"]["internal_secret"] = "s3cr3t"
        resp = client.post("/dashboard/internal/run-due-charges")  # no X-Internal-Secret header
        assert resp.status_code == 401

    @patch("dashboard_views.DashboardStorage")
    def test_disabled_by_default(self, mock_cls, client, app):
        app.config["APP_CONFIG"]["internal_secret"] = "s3cr3t"
        app.config["APP_CONFIG"]["renewals_enabled"] = False
        resp = client.post("/dashboard/internal/run-due-charges",
                           headers={"X-Internal-Secret": "s3cr3t"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "disabled"
        mock_cls.return_value.find_due_for_charge.assert_not_called()


class TestRunDueCharges:
    def _enable(self, app):
        app.config["APP_CONFIG"]["internal_secret"] = "s3cr3t"
        app.config["APP_CONFIG"]["renewals_enabled"] = True

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_successful_charge_advances_date_and_ledgers(self, mock_cls, mock_gi, client, app):
        self._enable(app)
        storage = MagicMock()
        storage.find_due_for_charge.return_value = [_due_user()]
        storage.claim_charge_period.return_value = True
        storage.get_user.return_value = _due_user()
        mock_cls.return_value = storage
        mock_gi.return_value.charge_token.return_value = {
            "success": True, "data": {}, "document_id": "doc_r", "transaction_id": "txn_r",
        }

        resp = client.post("/dashboard/internal/run-due-charges",
                           headers={"X-Internal-Secret": "s3cr3t"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["charged"] == 1 and body["failed"] == 0

        # Charged with an idempotency key = email:period.
        _, kwargs = mock_gi.return_value.charge_token.call_args
        assert kwargs["idempotency_key"] == "test@example.com:2026-08"
        # Advanced next_bill_at to the next anchor (Sep 15) + success ledger row.
        upd = storage.update_user_profile.call_args[0][1]
        assert upd["subscription_charge_state"] == "done"
        assert upd["next_bill_at"].startswith("2026-09-15")
        assert storage.record_charge_attempt.call_args.kwargs["status"] == "success"

    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_claim_lost_is_skipped(self, mock_cls, mock_gi, client, app):
        self._enable(app)
        storage = MagicMock()
        storage.find_due_for_charge.return_value = [_due_user()]
        storage.claim_charge_period.return_value = False  # another tick owns it
        mock_cls.return_value = storage

        resp = client.post("/dashboard/internal/run-due-charges",
                           headers={"X-Internal-Secret": "s3cr3t"})
        assert resp.get_json()["skipped"] == 1
        mock_gi.return_value.charge_token.assert_not_called()

    @patch("dashboard_views.requests.post")
    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_failed_charge_ledgers_and_retries(self, mock_cls, mock_gi, mock_notify, client, app):
        self._enable(app)
        app.config["APP_CONFIG"]["bot_internal_url"] = "http://bot.local"
        storage = MagicMock()
        storage.find_due_for_charge.return_value = [_due_user()]
        storage.claim_charge_period.return_value = True
        storage.get_user.return_value = _due_user()
        mock_cls.return_value = storage
        mock_gi.return_value.charge_token.return_value = {"success": False, "error": "declined"}

        resp = client.post("/dashboard/internal/run-due-charges",
                           headers={"X-Internal-Secret": "s3cr3t"})
        assert resp.get_json()["failed"] == 1
        assert storage.record_charge_attempt.call_args.kwargs["status"] == "failed"
        # First failure of the period -> charge-failed message pinged to the bot.
        called = [c for c in mock_notify.call_args_list
                  if "notify-subscription-event" in c.args[0]]
        assert called and called[0].kwargs["json"]["event"] == "charge_failed"

    @patch("dashboard_views.requests.post")
    @patch("dashboard_views.GreenInvoiceService")
    @patch("dashboard_views.DashboardStorage")
    def test_final_failure_ends_subscription(self, mock_cls, mock_gi, mock_notify, client, app):
        self._enable(app)
        app.config["APP_CONFIG"]["bot_internal_url"] = "http://bot.local"
        storage = MagicMock()
        # Already failed 3 times; this is attempt 4 = MAX -> end.
        u = _due_user(charge_retry_count=3, subscription_charge_failed_message_sent=True)
        storage.find_due_for_charge.return_value = [u]
        storage.claim_charge_period.return_value = True
        storage.get_user.return_value = u
        mock_cls.return_value = storage
        mock_gi.return_value.charge_token.return_value = {"success": False, "error": "declined"}

        client.post("/dashboard/internal/run-due-charges", headers={"X-Internal-Secret": "s3cr3t"})
        upd = storage.update_user_profile.call_args[0][1]
        assert upd["subscription_status"] == "subscription_ended"
        called = [c for c in mock_notify.call_args_list
                  if "notify-subscription-event" in c.args[0]]
        assert called and called[0].kwargs["json"]["event"] == "charge_failed_ended"


class TestBillingHistoryCsv:
    @patch("dashboard_views.DashboardStorage")
    def test_csv_download(self, mock_cls, client):
        mock_cls.return_value.get_charge_history.return_value = [
            {"created_at": "2026-07-22T00:00:00+00:00", "amount_agorot": 4700,
             "status": "success", "billing_period": "2026-07",
             "gi_document_id": "doc_1", "provider_txn_id": "txn_1"},
        ]
        with client.session_transaction() as sess:
            sess["user_email"] = "test@example.com"
        resp = client.get("/dashboard/subscription/history.csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["Content-Type"]
        assert b"amount_ils" in resp.data
        assert b"47.0" in resp.data
