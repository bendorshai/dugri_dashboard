"""Tests for the Meta (Facebook) conversion-tracking feature (dashboard side).

Covers:
- OAuth callback captures _fbp/_fbc cookies + IP/UA into the user doc's meta.* sub-doc.
- POST /api/meta-identifiers requires login (401 without session).
- POST /api/meta-identifiers persists fbp/fbc/fbclid and synthesizes fbc from fbclid.
- The Meta pixel renders ONLY when meta.enabled is true AND pixel_id is set.
- The webhook fires a server-side Purchase CAPI event (deduped by token id).
- services.meta_capi.send_event payload shape + disabled/no-op behavior.

Uses the shared test Mongo (db "test_health_tracker") for the integration tests
that need to read the persisted doc back; cleans up any user docs it inserts.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from storage import DashboardStorage
from tests.conftest import SAMPLE_CONFIG, _TEST_MONGO_URI

TEST_EMAIL = "meta_capture_test@example.com"


# -- Shared helpers ----------------------------------------------------------

def _real_storage() -> DashboardStorage:
    return DashboardStorage(uri=_TEST_MONGO_URI, db_name="test_health_tracker")


@pytest.fixture()
def real_storage():
    storage = _real_storage()
    storage._users.delete_one({"_id": TEST_EMAIL})
    yield storage
    storage._users.delete_one({"_id": TEST_EMAIL})


def _meta_enabled_config() -> dict:
    cfg = json.loads(json.dumps(SAMPLE_CONFIG))
    cfg["meta"] = {
        "pixel_id": "123",
        "capi_access_token": "tok-abc",
        "api_version": "v20.0",
        "enabled": True,
        "test_event_code": "",
    }
    return cfg


@pytest.fixture()
def meta_app(tmp_path, monkeypatch):
    """App wired with meta.enabled=true + pixel_id='123'."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(_meta_enabled_config()), encoding="utf-8")
    monkeypatch.setattr("app.CONFIG_PATH", config_file)
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def meta_client(meta_app):
    return meta_app.test_client()


def _setup_oauth_mocks(mock_requests, email=TEST_EMAIL, name="Meta Test", picture=None):
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": "test-token"}

    userinfo = {"email": email, "name": name}
    if picture:
        userinfo["picture"] = picture
    userinfo_response = MagicMock()
    userinfo_response.status_code = 200
    userinfo_response.json.return_value = userinfo

    mock_requests.post.return_value = token_response
    mock_requests.get.return_value = userinfo_response


# -- 1. OAuth callback persists _fbp/_fbc from cookies -----------------------

class TestCallbackMetaCapture:
    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_callback_persists_fbp_fbc_from_cookies(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_storage.create_user.return_value = {"telegram_user_id": None}
        mock_storage.regenerate_signup_session_token.return_value = "tok"
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"
            sess["pending_consents"] = {"terms": True, "medical": True, "marketing": False}

        client.set_cookie("_fbp", "fb.1.111.222", domain="localhost")
        client.set_cookie("_fbc", "fb.1.333.clickid", domain="localhost")

        resp = client.get(
            "/auth/callback?code=test-code&state=test-state",
            headers={"User-Agent": "pytest-agent", "X-Forwarded-For": "9.9.9.9, 10.0.0.1"},
        )
        assert resp.status_code == 302

        mock_storage.set_meta_identifiers.assert_called_once()
        kwargs = mock_storage.set_meta_identifiers.call_args.kwargs
        assert kwargs["fbp"] == "fb.1.111.222"
        assert kwargs["fbc"] == "fb.1.333.clickid"
        assert kwargs["client_ip"] == "9.9.9.9"  # first hop of XFF
        assert kwargs["client_user_agent"] == "pytest-agent"

    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_callback_capture_failure_is_non_fatal(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_storage.create_user.return_value = {"telegram_user_id": None}
        mock_storage.regenerate_signup_session_token.return_value = "tok"
        mock_storage.set_meta_identifiers.side_effect = RuntimeError("boom")
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"
            sess["pending_consents"] = {"terms": True, "medical": True, "marketing": False}

        resp = client.get("/auth/callback?code=test-code&state=test-state")
        # Even though capture raised, the flow completes to /welcome.
        assert resp.status_code == 302
        assert "/welcome" in resp.headers["Location"]


# -- 2 & 3. /api/meta-identifiers endpoint -----------------------------------

class TestMetaIdentifiersEndpoint:
    def test_meta_identifiers_endpoint_requires_login(self, client):
        resp = client.post("/api/meta-identifiers", json={"fbp": "x"})
        assert resp.status_code == 401

    def test_meta_identifiers_endpoint_persists_and_synthesizes_fbc(self, client, real_storage):
        real_storage.create_user(TEST_EMAIL, "Meta Test")

        with client.session_transaction() as sess:
            sess["user_email"] = TEST_EMAIL

        resp = client.post("/api/meta-identifiers", json={"fbclid": "abc"})
        assert resp.status_code == 200

        doc = real_storage.get_user(TEST_EMAIL)
        meta = doc["meta"]
        assert meta["fbclid"] == "abc"
        assert meta["fbc"].startswith("fb.1.")
        assert meta["fbc"].endswith(".abc")


# -- 4 & 5. Pixel render gating ----------------------------------------------

class TestPixelGating:
    def test_pixel_absent_when_disabled(self, client):
        resp = client.get("/signup")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "fbq(" not in body
        assert "connect.facebook.net" not in body

    def test_pixel_present_when_enabled(self, meta_client):
        resp = meta_client.get("/signup")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "fbq('init', '123')" in body
        assert "connect.facebook.net" in body


# -- 6. Purchase event on webhook --------------------------------------------

class TestPurchaseWebhook:
    @patch("services.meta_capi.requests.post")
    @patch("dashboard_views.DashboardStorage")
    def test_purchase_event_fired_on_webhook(self, mock_storage_cls, mock_post, meta_client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": TEST_EMAIL,
            "subscription_status": "trial_ended",
            "meta": {"fbp": "fb.1.p", "client_ip": "9.9.9.9", "client_user_agent": "UA"},
        }
        mock_storage_cls.return_value = mock_storage

        post_resp = MagicMock()
        post_resp.status_code = 200
        mock_post.return_value = post_resp

        resp = meta_client.post(
            "/dashboard/subscription/webhook?gi-type=ipn",
            json={"custom": TEST_EMAIL, "tokenId": "tok1"},
        )
        assert resp.status_code == 200

        assert mock_post.call_count == 1
        payload = mock_post.call_args.kwargs["json"]
        event = payload["data"][0]
        assert event["event_name"] == "Purchase"
        assert event["custom_data"] == {"value": 1, "currency": "ILS"}  # SAMPLE_CONFIG price
        # em must be present and hashed (64 hex chars), never the raw email.
        em = event["user_data"]["em"]
        assert len(em) == 64
        assert TEST_EMAIL not in em

    @patch("services.meta_capi.requests.post")
    @patch("dashboard_views.DashboardStorage")
    def test_purchase_not_fired_when_meta_disabled(self, mock_storage_cls, mock_post, client):
        # Default `client` fixture uses SAMPLE_CONFIG which has no meta block.
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": TEST_EMAIL, "subscription_status": "trial_ended", "meta": {},
        }
        mock_storage_cls.return_value = mock_storage

        resp = client.post(
            "/dashboard/subscription/webhook?gi-type=ipn",
            json={"custom": TEST_EMAIL, "tokenId": "tok1"},
        )
        assert resp.status_code == 200
        mock_post.assert_not_called()

    @patch("services.meta_capi.requests.post")
    @patch("dashboard_views.DashboardStorage")
    def test_purchase_logged_to_meta_events_log(self, mock_storage_cls, mock_post, meta_client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": TEST_EMAIL, "subscription_status": "trial_ended",
            "telegram_user_id": 42, "meta": {},
        }
        mock_storage_cls.return_value = mock_storage

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.ok = True
        post_resp.json.return_value = {"events_received": 1, "fbtrace_id": "tb"}
        mock_post.return_value = post_resp

        resp = meta_client.post(
            "/dashboard/subscription/webhook?gi-type=ipn",
            json={"custom": TEST_EMAIL, "tokenId": "tok1"},
        )
        assert resp.status_code == 200

        # The webhook records the Purchase in our own audit log with the send outcome.
        mock_storage.log_meta_event.assert_called_once()
        kw = mock_storage.log_meta_event.call_args.kwargs
        assert kw["event_name"] == "Purchase"
        assert kw["event_key"] == "paid"
        assert kw["sent_ok"] is True
        assert kw["fbtrace_id"] == "tb"
        assert kw["events_received"] == 1
        assert kw["telegram_user_id"] == 42


class TestLogMetaEvent:
    def test_log_meta_event_inserts_row(self, real_storage):
        marker = "log-meta-event-test-trace"
        coll = real_storage._db["meta_events_log"]
        coll.delete_many({"fbtrace_id": marker})
        real_storage.log_meta_event(
            telegram_user_id=7, user_email=TEST_EMAIL, event_key="paid",
            event_name="Purchase", action_source="website", sent_ok=True,
            http_status=200, events_received=1, fbtrace_id=marker,
            custom_data={"value": 47, "currency": "ILS"},
        )
        try:
            row = coll.find_one({"fbtrace_id": marker})
            assert row is not None
            assert row["event_name"] == "Purchase"
            assert row["source"] == "dashboard"
            assert row["sent_ok"] is True
            assert row["telegram_user_id"] == 7
            assert "timestamp" in row
        finally:
            coll.delete_many({"fbtrace_id": marker})


# -- Unit tests for services.meta_capi.send_event ----------------------------

class TestMetaCapiSendEvent:
    def _cfg(self, **overrides):
        cfg = {
            "pixel_id": "PIX",
            "capi_access_token": "TOK",
            "api_version": "v20.0",
            "enabled": True,
            "test_event_code": "",
        }
        cfg.update(overrides)
        return cfg

    @patch("services.meta_capi.requests.post")
    def test_disabled_config_is_noop(self, mock_post):
        import services.meta_capi as meta_capi
        meta_capi.send_event(
            self._cfg(enabled=False), email="a@b.com",
            event_name="Purchase", event_id="e1",
        )
        mock_post.assert_not_called()

    @patch("services.meta_capi.requests.post")
    def test_missing_pixel_or_token_is_noop(self, mock_post):
        import services.meta_capi as meta_capi
        meta_capi.send_event(
            self._cfg(pixel_id=""), email="a@b.com",
            event_name="Purchase", event_id="e1",
        )
        meta_capi.send_event(
            self._cfg(capi_access_token=""), email="a@b.com",
            event_name="Purchase", event_id="e1",
        )
        mock_post.assert_not_called()

    @patch("services.meta_capi.requests.post")
    def test_payload_shape_and_hashing(self, mock_post):
        import services.meta_capi as meta_capi
        meta_capi.send_event(
            self._cfg(test_event_code="TEST42"),
            email="Person@Example.COM",
            event_name="Purchase",
            event_id="evt-1",
            user_meta={"fbp": "fbp1", "fbc": "fbc1", "client_ip": "1.2.3.4",
                       "client_user_agent": "UA"},
            custom_data={"value": 47, "currency": "ILS"},
            event_source_url="https://dugri.life/welcome",
        )
        assert mock_post.call_count == 1
        url = mock_post.call_args.args[0]
        assert "graph.facebook.com/v20.0/PIX/events" in url
        assert "access_token=TOK" in url

        payload = mock_post.call_args.kwargs["json"]
        assert payload["test_event_code"] == "TEST42"
        event = payload["data"][0]
        assert event["event_name"] == "Purchase"
        assert event["event_id"] == "evt-1"
        assert event["action_source"] == "website"
        assert event["event_source_url"] == "https://dugri.life/welcome"
        assert event["custom_data"] == {"value": 47, "currency": "ILS"}

        ud = event["user_data"]
        # email hashed lower/trimmed -> em == external_id == sha256("person@example.com")
        assert ud["em"] == meta_capi._sha256("person@example.com")
        assert ud["external_id"] == meta_capi._sha256("person@example.com")
        assert ud["fbp"] == "fbp1"
        assert ud["fbc"] == "fbc1"
        assert ud["client_ip_address"] == "1.2.3.4"
        assert ud["client_user_agent"] == "UA"

    @patch("services.meta_capi.requests.post", side_effect=RuntimeError("network"))
    def test_send_failure_is_swallowed(self, mock_post):
        import services.meta_capi as meta_capi
        # Must not raise.
        meta_capi.send_event(
            self._cfg(), email="a@b.com", event_name="Purchase", event_id="e1",
        )


# -- Storage unit tests ------------------------------------------------------

class TestStorageMetaMethods:
    def test_create_user_mints_signup_event_id(self, real_storage):
        doc = real_storage.create_user(TEST_EMAIL, "Meta Test")
        assert doc["meta"]["signup_event_id"]

    def test_get_or_create_signup_event_id_is_stable(self, real_storage):
        real_storage.create_user(TEST_EMAIL, "Meta Test")
        first = real_storage.get_or_create_signup_event_id(TEST_EMAIL)
        second = real_storage.get_or_create_signup_event_id(TEST_EMAIL)
        assert first and first == second

    def test_set_meta_identifiers_skips_empty(self, real_storage):
        real_storage.create_user(TEST_EMAIL, "Meta Test")
        real_storage.set_meta_identifiers(TEST_EMAIL, fbp="fb.1.p", fbc=None)
        meta = real_storage.get_user(TEST_EMAIL)["meta"]
        assert meta["fbp"] == "fb.1.p"
        assert "fbc" not in meta  # None never written
