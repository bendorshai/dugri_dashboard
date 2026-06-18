"""Tests for the Green Invoice service wrapper.

Covers:
- Authentication and token caching
- Payment form URL generation
- Token charging (success and failure)
- Sandbox vs production URL selection
"""

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from services.green_invoice import (
    GreenInvoiceService,
    GreenInvoiceError,
    SANDBOX_BASE,
    PRODUCTION_BASE,
)


@pytest.fixture
def gi_sandbox():
    return GreenInvoiceService("test_id", "test_secret", sandbox=True)


@pytest.fixture
def gi_production():
    return GreenInvoiceService("test_id", "test_secret", sandbox=False)


class TestAuthentication:
    @patch("services.green_invoice.requests.post")
    def test_authenticates_and_caches_token(self, mock_post, gi_sandbox):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"token": "jwt_123", "expires_in": 1800},
        )

        token1 = gi_sandbox._authenticate()
        token2 = gi_sandbox._authenticate()

        assert token1 == "jwt_123"
        assert token2 == "jwt_123"
        # Should only call API once due to caching
        assert mock_post.call_count == 1

    @patch("services.green_invoice.requests.post")
    def test_auth_failure_raises(self, mock_post, gi_sandbox):
        mock_post.return_value = MagicMock(
            status_code=401,
            text="Unauthorized",
        )

        with pytest.raises(GreenInvoiceError, match="Auth failed"):
            gi_sandbox._authenticate()


class TestBaseUrl:
    def test_sandbox_url(self, gi_sandbox):
        assert gi_sandbox._base_url == SANDBOX_BASE

    def test_production_url(self, gi_production):
        assert gi_production._base_url == PRODUCTION_BASE


class TestPaymentFormUrl:
    @patch("services.green_invoice.requests.post")
    def test_returns_form_url(self, mock_post, gi_sandbox):
        responses = [
            MagicMock(status_code=200, json=lambda: {"token": "jwt_123", "expires_in": 1800}),
            MagicMock(status_code=200, json=lambda: {"url": "https://sandbox.d.greeninvoice.co.il/form/abc"}),
        ]
        mock_post.side_effect = responses

        url = gi_sandbox.get_payment_form_url(
            user_email="user@test.com",
            user_name="Test User",
            amount_ils=1,
            success_url="https://app.com/success",
            failure_url="https://app.com/failure",
            notify_url="https://app.com/webhook",
        )

        assert url == "https://sandbox.d.greeninvoice.co.il/form/abc"
        # Second call should be the form creation
        form_call = mock_post.call_args_list[1]
        payload = form_call.kwargs.get("json") or form_call[1].get("json")
        assert payload["amount"] == 1
        assert payload["currency"] == "ILS"
        assert payload["custom"] == "user@test.com"

    @patch("services.green_invoice.requests.post")
    def test_form_failure_raises(self, mock_post, gi_sandbox):
        responses = [
            MagicMock(status_code=200, json=lambda: {"token": "jwt_123", "expires_in": 1800}),
            MagicMock(status_code=400, text="Bad request"),
        ]
        mock_post.side_effect = responses

        with pytest.raises(GreenInvoiceError, match="Payment form failed"):
            gi_sandbox.get_payment_form_url(
                user_email="user@test.com",
                user_name="Test",
                amount_ils=1,
                success_url="https://app.com/s",
                failure_url="https://app.com/f",
                notify_url="https://app.com/w",
            )


class TestChargeToken:
    @patch("services.green_invoice.requests.post")
    def test_successful_charge(self, mock_post, gi_sandbox):
        responses = [
            MagicMock(status_code=200, json=lambda: {"token": "jwt_123", "expires_in": 1800}),
            MagicMock(status_code=200, json=lambda: {"transactionId": "txn_456"}),
        ]
        mock_post.side_effect = responses

        result = gi_sandbox.charge_token("tok_abc", 47)

        assert result["success"] is True
        assert "data" in result

    @patch("services.green_invoice.requests.post")
    def test_failed_charge(self, mock_post, gi_sandbox):
        responses = [
            MagicMock(status_code=200, json=lambda: {"token": "jwt_123", "expires_in": 1800}),
            MagicMock(status_code=402, text="Card declined"),
        ]
        mock_post.side_effect = responses

        result = gi_sandbox.charge_token("tok_abc", 47)

        assert result["success"] is False
        assert "error" in result
