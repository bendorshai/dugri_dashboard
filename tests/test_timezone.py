"""Tests for the user-timezone feature (dashboard side).

Covers:
- supported_timezones.is_valid_timezone accepts real IANA zones, rejects junk.
- create_user seeds timezone_source='default' + timezone_updated_at=None.
- GET /dashboard/profile renders the timezone <select> with the stored zone.
- POST /dashboard/profile persists timezone + source + updated_at; ignores junk.
- POST /api/timezone-detect requires login, persists a valid zone (browser_detected),
  and silently ignores an invalid one.

Uses mocked storage (no Mongo) so the whole file runs offline.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from supported_timezones import SUPPORTED_TIMEZONES, is_valid_timezone


def _login(client):
    with client.session_transaction() as sess:
        sess["user_email"] = "test@example.com"
        sess["user_name"] = "Test"


MOCK_USER = {
    "_id": "test@example.com",
    "name": "Test",
    "timezone": "America/New_York",
    "timezone_source": "user_manual",
}


# -- is_valid_timezone -------------------------------------------------------

class TestIsValidTimezone:
    def test_all_supported_zones_are_valid(self):
        for tz in SUPPORTED_TIMEZONES:
            assert is_valid_timezone(tz), tz

    def test_common_non_listed_zone_is_valid(self):
        # Browser auto-detect may return a real zone we don't list in the dropdown.
        assert is_valid_timezone("Europe/Berlin")

    @pytest.mark.parametrize("bad", ["", "  ", "garbage", "Mars/Olympus", "UTC+3", None, 123])
    def test_junk_is_invalid(self, bad):
        assert is_valid_timezone(bad) is False


# -- create_user seeds the metadata -----------------------------------------

class TestCreateUserTimezoneDefaults:
    def test_create_user_sets_default_source(self):
        from storage import DashboardStorage
        storage = DashboardStorage(uri="mongodb://localhost:27017", db_name="unused")
        storage._users = MagicMock()  # no real DB round-trip

        doc = storage.create_user("new@example.com", "New")
        assert doc["timezone"] == "Asia/Jerusalem"
        assert doc["timezone_source"] == "default"
        assert doc["timezone_updated_at"] is None


# -- profile page ------------------------------------------------------------

class TestProfileTimezone:
    @patch("dashboard_views.DashboardStorage")
    def test_profile_renders_timezone_select(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.get("/dashboard/profile")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert 'name="timezone"' in body
        assert "America/New_York" in body      # stored zone appears as an option
        assert "Asia/Jerusalem" in body        # curated list present
        assert 'name="timezone_source"' in body

    @patch("dashboard_views.DashboardStorage")
    def test_profile_post_persists_timezone(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/dashboard/profile", data={
            "name": "Test",
            "timezone": "Asia/Tokyo",
            "timezone_source": "user_manual",
        })
        assert resp.status_code == 302
        data = mock_storage.update_user_profile.call_args[0][1]
        assert data["timezone"] == "Asia/Tokyo"
        assert data["timezone_source"] == "user_manual"
        assert data["timezone_updated_at"]  # a timestamp was stamped

    @patch("dashboard_views.DashboardStorage")
    def test_profile_post_banner_confirm_source(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)

        client.post("/dashboard/profile", data={
            "timezone": "Europe/Paris",
            "timezone_source": "user_confirmed",
        })
        data = mock_storage.update_user_profile.call_args[0][1]
        assert data["timezone"] == "Europe/Paris"
        assert data["timezone_source"] == "user_confirmed"

    @patch("dashboard_views.DashboardStorage")
    def test_profile_post_invalid_timezone_ignored(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/dashboard/profile", data={
            "name": "Test",
            "timezone": "garbage/zone",
            "timezone_source": "user_manual",
        })
        assert resp.status_code == 302
        data = mock_storage.update_user_profile.call_args[0][1]
        # Invalid tz must not be written (stored zone left unchanged).
        assert "timezone" not in data

    @patch("dashboard_views.DashboardStorage")
    def test_profile_post_unknown_source_treated_as_manual(self, mock_storage_cls, client):
        """A real zone CHANGE with a spoofed/unknown source is persisted as
        user_manual - the change itself is trusted (diff vs stored), the source
        string only refines manual vs the banner's confirmed."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER  # stored zone = America/New_York
        mock_storage_cls.return_value = mock_storage
        _login(client)

        client.post("/dashboard/profile", data={
            "timezone": "Asia/Tokyo",       # differs from stored
            "timezone_source": "spoofed",
        })
        data = mock_storage.update_user_profile.call_args[0][1]
        assert data["timezone"] == "Asia/Tokyo"
        assert data["timezone_source"] == "user_manual"

    @patch("dashboard_views.DashboardStorage")
    def test_profile_post_manual_change_without_js_source(self, mock_storage_cls, client):
        """JS-independent fallback: if the dropdown changed but client JS failed to
        set timezone_source (empty), the change is still persisted (diff vs stored)
        as user_manual - the save is not silently dropped."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER  # stored zone = America/New_York
        mock_storage_cls.return_value = mock_storage
        _login(client)

        client.post("/dashboard/profile", data={
            "timezone": "Asia/Tokyo",       # differs from stored
            "timezone_source": "",          # JS didn't populate it
        })
        data = mock_storage.update_user_profile.call_args[0][1]
        assert data["timezone"] == "Asia/Tokyo"
        assert data["timezone_source"] == "user_manual"

    @patch("dashboard_views.DashboardStorage")
    def test_profile_post_untouched_timezone_preserves_source(self, mock_storage_cls, client):
        """Saving the profile without changing the timezone (submitted zone equals
        the stored zone) must NOT rewrite the timezone fields - otherwise an
        unrelated 'save name' would clobber a browser_detected provenance and bump
        timezone_updated_at.
        """
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER  # stored zone = America/New_York
        mock_storage_cls.return_value = mock_storage
        _login(client)

        client.post("/dashboard/profile", data={
            "name": "Test",
            "timezone": "America/New_York",   # equals stored -> no change
            "timezone_source": "",
        })
        data = mock_storage.update_user_profile.call_args[0][1]
        assert "timezone" not in data
        assert "timezone_source" not in data
        assert "timezone_updated_at" not in data

    @patch("dashboard_views.DashboardStorage")
    def test_profile_post_legacy_user_default_not_fabricated(self, mock_storage_cls, client):
        """A legacy user with NO stored timezone key renders the default in the
        dropdown; saving an unrelated field submits that default. It must NOT be
        misread as a deliberate change (which would fabricate user_manual and block
        the auto-detect banner forever)."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {"_id": "test@example.com", "name": "Test"}  # no timezone
        mock_storage_cls.return_value = mock_storage
        _login(client)

        client.post("/dashboard/profile", data={
            "name": "Test",
            "timezone": "Asia/Jerusalem",   # the rendered default for a keyless user
            "timezone_source": "",
        })
        data = mock_storage.update_user_profile.call_args[0][1]
        assert "timezone" not in data
        assert "timezone_source" not in data


# -- /api/timezone-detect ----------------------------------------------------

class TestTimezoneDetectEndpoint:
    def test_requires_login(self, client):
        resp = client.post("/api/timezone-detect", json={"timezone": "Asia/Tokyo"})
        assert resp.status_code == 401

    @patch("api.DashboardStorage")
    def test_persists_valid_zone_as_browser_detected(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {}  # no prior explicit choice
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/api/timezone-detect",
                           json={"timezone": "Europe/Paris", "source": "browser_detected"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
        mock_storage.set_timezone.assert_called_once_with(
            "test@example.com", "Europe/Paris", "browser_detected")

    @patch("api.DashboardStorage")
    def test_invalid_zone_silently_ignored(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/api/timezone-detect", json={"timezone": "garbage"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ignored"
        mock_storage.set_timezone.assert_not_called()

    @patch("api.DashboardStorage")
    def test_unknown_source_defaults_to_browser_detected(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {}
        mock_storage_cls.return_value = mock_storage
        _login(client)

        client.post("/api/timezone-detect",
                   json={"timezone": "Asia/Tokyo", "source": "spoofed"})
        mock_storage.set_timezone.assert_called_once_with(
            "test@example.com", "Asia/Tokyo", "browser_detected")

    @patch("api.DashboardStorage")
    def test_browser_detected_writes_from_default(self, mock_storage_cls, client):
        """The one-shot initial capture: browser_detected DOES set the zone when
        the stored provenance is still 'default'."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {"timezone_source": "default"}
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/api/timezone-detect",
                           json={"timezone": "Europe/Paris", "source": "browser_detected"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
        mock_storage.set_timezone.assert_called_once_with(
            "test@example.com", "Europe/Paris", "browser_detected")

    @patch("api.DashboardStorage")
    def test_browser_detected_does_not_override_explicit_choice(self, mock_storage_cls, client):
        """The passive welcome-page browser_detected signal must NOT clobber a
        deliberate user_manual/user_confirmed zone (a returning traveler's choice)."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {"timezone_source": "user_manual"}
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/api/timezone-detect",
                           json={"timezone": "Asia/Tokyo", "source": "browser_detected"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "kept"
        mock_storage.set_timezone.assert_not_called()

    @patch("api.DashboardStorage")
    def test_browser_detected_does_not_override_prior_detection(self, mock_storage_cls, client):
        """browser_detected is a one-shot: a later welcome visit (from a transient
        OS/VPN zone) must NOT overwrite an already-detected zone."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {"timezone_source": "browser_detected"}
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/api/timezone-detect",
                           json={"timezone": "Asia/Tokyo", "source": "browser_detected"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "kept"
        mock_storage.set_timezone.assert_not_called()

    @patch("api.DashboardStorage")
    def test_user_confirmed_overrides_explicit_choice(self, mock_storage_cls, client):
        """An explicit user_confirmed tap (relocation banner) DOES override a prior
        explicit choice - it's a deliberate action, not a passive detection."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {"timezone_source": "user_manual"}
        mock_storage_cls.return_value = mock_storage
        _login(client)

        resp = client.post("/api/timezone-detect",
                           json={"timezone": "Asia/Tokyo", "source": "user_confirmed"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
        mock_storage.set_timezone.assert_called_once_with(
            "test@example.com", "Asia/Tokyo", "user_confirmed")
