"""Tests for the admin-only Meta Events monitor page (/admin/meta-events).

Covers:
- Auth gating: no session -> redirect to login; non-admin -> 403.
- Admin can access; empty collection renders a "No events yet" message.
- A seeded meta_events_log row renders the event name + its tooltip description.

The row-render test uses the shared test Mongo (db "test_health_tracker");
it cleans up any row it seeds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from admin_storage import AdminStorage
from tests.conftest import _TEST_MONGO_URI

MARKER_FBTRACE = "admin-meta-events-test-trace"


def _admin_storage() -> AdminStorage:
    return AdminStorage(uri=_TEST_MONGO_URI, db_name="test_health_tracker")


@pytest.fixture()
def seeded_meta_event():
    storage = _admin_storage()
    coll = storage._db["meta_events_log"]
    coll.delete_many({"fbtrace_id": MARKER_FBTRACE})
    doc = {
        "telegram_user_id": None,
        "user_email": "meta_events_admin_test@example.com",
        "event_key": "paid",
        "event_name": "Purchase",
        "action_source": "website",
        "source": "dashboard",
        "event_time": None,
        "custom_data": {"value": 47, "currency": "ILS"},
        "sent_ok": True,
        "http_status": 200,
        "events_received": 1,
        "fbtrace_id": MARKER_FBTRACE,
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    coll.insert_one(doc)
    yield doc
    coll.delete_many({"fbtrace_id": MARKER_FBTRACE})


class TestMetaEventsAuth:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/admin/meta-events")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_non_admin_gets_403(self, client):
        with client.session_transaction() as sess:
            sess["user_email"] = "regular@example.com"
        resp = client.get("/admin/meta-events")
        assert resp.status_code == 403


class TestMetaEventsPage:
    @patch("admin_views.AdminStorage")
    def test_admin_can_access_empty(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_meta_events.return_value = []
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["user_email"] = "admin@test.com"

        resp = client.get("/admin/meta-events")
        assert resp.status_code == 200
        assert b"No Meta events recorded yet" in resp.data

    def test_seeded_row_and_tooltip_rendered(self, client, seeded_meta_event):
        with client.session_transaction() as sess:
            sess["user_email"] = "admin@test.com"

        resp = client.get("/admin/meta-events")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Event name rendered.
        assert "Purchase" in html
        # Tooltip description text rendered (substring of EVENT_DESCRIPTIONS).
        assert "User paid for a subscription" in html
