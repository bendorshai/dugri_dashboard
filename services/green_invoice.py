"""Green Invoice (Morning) API client for subscription billing.

Handles authentication, payment form URL generation, and token-based
recurring charges. Works with both sandbox and production environments.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

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
            # Request that the card be saved as a reusable token for the monthly
            # renewal charge. NOTE (2026-07): Green Invoice silently ignores
            # unknown fields (so this is harmless), and the exact field + how the
            # saved token is returned to us is UNCONFIRMED - the terminal has
            # tokens:true, but the token is not in the receipt document and the
            # IPN (which would carry it) is not reliably delivered. Renewals are
            # gated OFF until token capture is confirmed with Morning support.
            "addToken": True,
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

    def get_document(self, document_id: str) -> dict:
        """Fetch a document from GI's authenticated API. Raises on failure."""
        resp = requests.get(
            f"{self._base_url}/api/v1/documents/{document_id}",
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            raise GreenInvoiceError(
                f"Get document failed: {resp.status_code} {resp.text}")
        return resp.json()

    def get_document_url(self, document_id: str) -> str | None:
        """Return the hosted PDF link for a GI document (the emailed receipt), or
        None if unavailable. GI documents carry a `url` object with `origin`/`he`
        PDF links - we reuse those rather than generating a PDF ourselves. Never
        raises: any error (missing doc, network, missing url) degrades to None so
        the caller can 404 gracefully."""
        try:
            data = self.get_document(document_id)
        except (GreenInvoiceError, requests.RequestException):
            logger.warning("get_document_url: fetch failed for %s", document_id,
                           exc_info=True)
            return None
        url = data.get("url") or {}
        if isinstance(url, dict):
            return url.get("origin") or url.get("he") or url.get("en")
        # Some responses expose a bare string url.
        return url if isinstance(url, str) and url else None

    def verify_payment(self, document_id: str) -> dict | None:
        """Confirm an IPN refers to a real, settled payment via the authenticated API.

        Re-fetches the document GI says was created and checks it is a genuine,
        positive-amount payment. Returns the document dict when verified, else
        None. NEVER raises - a verification failure must leave the webhook a
        no-op, not 500 the caller. This closes the spoofing hole where an
        unauthenticated IPN POST could flip any email to paid: without a real
        settled document behind it, nothing happens.
        """
        if not document_id:
            return None
        try:
            doc = self.get_document(document_id)
        except (GreenInvoiceError, requests.RequestException):
            logger.warning("GI verify: could not fetch document %s", document_id)
            return None
        amount = doc.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            logger.warning(
                "GI verify: document %s has non-positive/absent amount %r",
                document_id, amount,
            )
            return None
        return doc

    def find_recent_receipt(
        self, email: str, amount_ils: int, within_days: int = 3, limit: int = 50
    ) -> dict | None:
        """Find the most recent settled receipt (type 400) for this client email
        and exact amount, created within the last `within_days`.

        Used to reconcile a paid subscription WITHOUT relying on GI's IPN push
        (which is not reliably delivered): after a real card payment GI issues
        the receipt, so we can confirm the payment authoritatively by looking it
        up. Returns the matching search item (has `id`, `amount`, `client`,
        `documentDate`, `number`) or None. NEVER raises.
        """
        if not email:
            return None
        try:
            resp = requests.post(
                f"{self._base_url}/api/v1/documents/search",
                json={"pageSize": limit, "page": 1, "sort": "creationDate"},
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("GI search failed: %s %s", resp.status_code, resp.text)
                return None
            items = resp.json().get("items", []) or []
        except (GreenInvoiceError, requests.RequestException):
            logger.warning("GI search: request error", exc_info=True)
            return None

        cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).date()
        email_l = email.lower()
        matches = []
        for it in items:
            if it.get("type") != DOC_TYPE_RECEIPT:
                continue
            amt = it.get("amount")
            if not isinstance(amt, (int, float)) or int(amt) != int(amount_ils):
                continue
            emails = [e.lower() for e in (it.get("client", {}).get("emails") or [])]
            if email_l not in emails:
                continue
            try:
                doc_date = datetime.fromisoformat(str(it.get("documentDate"))).date()
            except (ValueError, TypeError):
                doc_date = None
            if doc_date is not None and doc_date < cutoff:
                continue
            matches.append(it)
        # Newest first by document number (sequential; higher = newer).
        matches.sort(key=lambda d: d.get("number", 0), reverse=True)
        return matches[0] if matches else None

    def charge_token(self, token_id: str, amount_ils: int,
                     idempotency_key: str | None = None) -> dict:
        """Charge a stored card token for recurring billing.

        A type-400 receipt is issued for the charge (client email comes from the
        stored token's client), so the renewal receipt is emailed like the first
        payment. When ``idempotency_key`` is supplied it is sent to Green Invoice
        (and mirrored as the charge ``remarks``/external ref) so a retried charge
        after a crash is deduped provider-side - the true defense against a
        charge-succeeds-then-DB-write-fails double-charge.

        Returns ``{success, data?, document_id?, transaction_id?, error?, status?}``.

        NOTE (2026-07): the exact provider idempotency-field name is unconfirmed
        against Green Invoice docs; the caller ALSO guards with an atomic Mongo
        per-period claim, so a wrong field degrades safety only to the Mongo
        guarantee, never below it. Confirm the field on a real charged token.
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
        if idempotency_key:
            payload["externalId"] = idempotency_key
            payload["remarks"] = idempotency_key

        try:
            resp = requests.post(
                f"{self._base_url}/api/v1/payments/token/{token_id}/charge",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json() if resp.text else {}
                return {
                    "success": True,
                    "data": data,
                    "document_id": data.get("id") or data.get("documentId"),
                    "transaction_id": data.get("transactionId") or data.get("paymentId"),
                }
            logger.error("Token charge failed: %s %s", resp.status_code, resp.text)
            return {"success": False, "error": resp.text, "status": resp.status_code}
        except requests.RequestException as e:
            logger.exception("Token charge request error")
            return {"success": False, "error": str(e)}
