"""Green Invoice (Morning) API client for subscription billing.

Handles authentication, payment form URL generation, and token-based
recurring charges. Works with both sandbox and production environments.
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

SANDBOX_BASE = "https://sandbox.d.greeninvoice.co.il"
PRODUCTION_BASE = "https://api.greeninvoice.co.il"

# Document type for receipt (קבלה)
DOC_TYPE_RECEIPT = 400


class GreenInvoiceError(Exception):
    """Raised when a Green Invoice API call fails."""


class GreenInvoiceService:
    def __init__(self, api_id: str, api_secret: str, sandbox: bool = True):
        self._base_url = SANDBOX_BASE if sandbox else PRODUCTION_BASE
        self._api_id = api_id
        self._api_secret = api_secret
        self._token: str | None = None
        self._token_expires_at: float = 0
        self._plugin_id: str | None = None

    def _authenticate(self) -> str:
        """Get a JWT token, using cached value if still valid."""
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        resp = requests.post(
            f"{self._base_url}/api/v1/account/token",
            json={"id": self._api_id, "secret": self._api_secret},
            timeout=15,
        )
        if resp.status_code != 200:
            raise GreenInvoiceError(f"Auth failed: {resp.status_code} {resp.text}")

        data = resp.json()
        self._token = data["token"]
        # Tokens typically last 30 minutes
        self._token_expires_at = now + data.get("expires_in", 1800)
        return self._token

    def _headers(self) -> dict:
        token = self._authenticate()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _get_payment_plugin_id(self) -> str:
        """Resolve the account's credit-card clearing terminal plugin id.

        The /payments/form endpoint must be told which clearing terminal to
        use via `pluginId`; without it Green Invoice returns a misleading
        errorCode 2403 ("document type not supported for this business type").
        We resolve it dynamically (the plugin flagged `payments: true`) so the
        same code works against the sandbox and production terminals, which
        have different ids. Cached for the lifetime of the instance.
        """
        if self._plugin_id:
            return self._plugin_id

        resp = requests.get(
            f"{self._base_url}/api/v1/plugins",
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            raise GreenInvoiceError(f"Plugins fetch failed: {resp.status_code} {resp.text}")

        plugins = resp.json() or []
        terminal = next(
            (p for p in plugins if p.get("payments") and p.get("id")), None
        )
        if terminal is None:
            raise GreenInvoiceError(
                "No payment clearing terminal configured on this Green Invoice account"
            )
        self._plugin_id = terminal["id"]
        return self._plugin_id

    def get_payment_form_url(
        self,
        user_email: str,
        user_name: str,
        amount_ils: int,
        success_url: str,
        failure_url: str,
        notify_url: str,
    ) -> str:
        """Create a payment form for card tokenization + first charge.

        Returns the hosted form URL to redirect the user to.
        """
        payload = {
            "type": DOC_TYPE_RECEIPT,
            "pluginId": self._get_payment_plugin_id(),
            "lang": "he",
            "currency": "ILS",
            "amount": amount_ils,
            "maxPayments": 1,
            "description": "דוגרי - מנוי חודשי",
            "client": {
                "name": user_name or user_email,
                "emails": [user_email],
            },
            "income": [
                {
                    "description": "מנוי חודשי לדוגרי",
                    "quantity": 1,
                    "price": amount_ils,
                    "currency": "ILS",
                }
            ],
            "successUrl": success_url,
            "failureUrl": failure_url,
            "notifyUrl": notify_url,
            "custom": user_email,
        }

        resp = requests.post(
            f"{self._base_url}/api/v1/payments/form",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        # GI returns 201 Created on success for the payment form.
        if resp.status_code not in (200, 201):
            raise GreenInvoiceError(f"Payment form failed: {resp.status_code} {resp.text}")

        data = resp.json()
        return data["url"]

    def charge_token(self, token_id: str, amount_ils: int) -> dict:
        """Charge a stored card token for recurring billing.

        Returns dict with 'success' bool and response data.
        """
        payload = {
            "amount": amount_ils,
            "currency": "ILS",
            "description": "דוגרי - חידוש מנוי חודשי",
            "type": DOC_TYPE_RECEIPT,
            "income": [
                {
                    "description": "מנוי חודשי לדוגרי",
                    "quantity": 1,
                    "price": amount_ils,
                    "currency": "ILS",
                }
            ],
        }

        try:
            resp = requests.post(
                f"{self._base_url}/api/v1/payments/token/{token_id}/charge",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code in (200, 201):
                return {"success": True, "data": resp.json()}
            else:
                logger.error("Token charge failed: %s %s", resp.status_code, resp.text)
                return {"success": False, "error": resp.text, "status": resp.status_code}
        except requests.RequestException as e:
            logger.exception("Token charge request error")
            return {"success": False, "error": str(e)}
