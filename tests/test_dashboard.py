from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def _login(client):
    with client.session_transaction() as sess:
        sess["user_email"] = "test@example.com"
        sess["user_name"] = "Test"


MOCK_USER = {
    "_id": "test@example.com",
    "name": "Test",
    "targets": {"calories": 2000, "protein": 150},
    "toggles": {
        "sleep": {"status": "active"},
        "eating_window": {"status": "dormant"},
        "workouts": {"status": "dormant"},
        "self_care": {"status": "dormant"},
        "nutrition": {"status": "dormant"},
        "weekly_summary": {"status": "active"},
    },
    "onboarding_complete": True,
}


class TestDashboardPreferences:
    @patch("dashboard_views.DashboardStorage")
    def test_preferences_page_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/preferences")
        assert resp.status_code == 200
        assert "העדפות אישיות".encode("utf-8") in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_preferences_post_updates_toggles_and_targets(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage.update_user_targets.return_value = {"calories": 2000, "protein": 150}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/dashboard/preferences", data={
            "sleep_enabled": "1",
            "weekly_summary_enabled": "1",
            "calories": "1800",
            "protein": "130",
        })
        assert resp.status_code == 302
        toggles = mock_storage.update_user_toggles.call_args[0][1]
        assert toggles["sleep"]["status"] == "active"
        assert toggles["weekly_summary"]["status"] == "active"
        mock_storage.update_user_targets.assert_called_once()


    @patch("dashboard_views.DashboardStorage")
    def test_activating_toggle_sets_timestamps(self, mock_storage_cls, client):
        """Dashboard must set activated_at/revealed_at when activating a toggle.

        Without these, the bot sees an impossible state (active but no activation
        timestamp) and tries to run goal flows that were never started.
        """
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage.update_user_targets.return_value = {"calories": 2000, "protein": 150}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/dashboard/preferences", data={
            "nutrition_status": "active",
            "calories": "2000",
            "protein": "150",
        })
        assert resp.status_code == 302
        toggles = mock_storage.update_user_toggles.call_args[0][1]
        nutrition = toggles["nutrition"]
        assert nutrition["status"] == "active"
        assert nutrition["activated_at"] is not None
        assert nutrition["revealed_at"] is not None
        assert nutrition["edu_intro_shown"] is True

    @patch("dashboard_views.DashboardStorage")
    def test_dormant_toggle_clears_timestamps(self, mock_storage_cls, client):
        """Setting a toggle to dormant should clear activation timestamps."""
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage.update_user_targets.return_value = {"calories": 2000, "protein": 150}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/dashboard/preferences", data={
            "sleep_status": "dormant",
            "calories": "2000",
            "protein": "150",
        })
        assert resp.status_code == 302
        toggles = mock_storage.update_user_toggles.call_args[0][1]
        sleep = toggles["sleep"]
        assert sleep["status"] == "dormant"
        assert sleep["revealed_at"] is None
        assert sleep["activated_at"] is None
        assert sleep["edu_intro_shown"] is False


    @patch("dashboard_views.DashboardStorage")
    def test_reactivating_already_active_keeps_existing_timestamps(self, mock_storage_cls, client):
        """Re-saving an already-active toggle should not overwrite timestamps."""
        user_with_active = {**MOCK_USER, "toggles": {
            **MOCK_USER["toggles"],
            "sleep": {"status": "active", "activated_at": "2026-06-01T00:00:00", "revealed_at": "2026-05-31T00:00:00"},
        }}
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = user_with_active
        mock_storage.update_user_targets.return_value = {"calories": 2000, "protein": 150}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/dashboard/preferences", data={
            "sleep_status": "active",
            "calories": "2000",
            "protein": "150",
        })
        assert resp.status_code == 302
        toggles = mock_storage.update_user_toggles.call_args[0][1]
        sleep = toggles["sleep"]
        assert sleep["activated_at"] == "2026-06-01T00:00:00"
        assert sleep["revealed_at"] == "2026-05-31T00:00:00"


class TestDashboardLegacyRedirects:
    def test_toggles_redirects_to_preferences(self, client):
        _login(client)
        resp = client.get("/dashboard/toggles")
        assert resp.status_code == 302
        assert "preferences" in resp.location

    def test_targets_redirects_to_preferences(self, client):
        _login(client)
        resp = client.get("/dashboard/targets")
        assert resp.status_code == 302
        assert "preferences" in resp.location


class TestDashboardSubscription:
    @patch("dashboard_views.DashboardStorage")
    def test_subscription_page_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/subscription")
        assert resp.status_code == 200
        assert "מנוי".encode() in resp.data


class TestDashboardAuth:
    def test_redirects_when_not_logged_in(self, client):
        resp = client.get("/dashboard/toggles")
        assert resp.status_code == 302

    def test_index_redirects_to_home(self, client):
        _login(client)
        resp = client.get("/dashboard/")
        assert resp.status_code == 302


class TestTrendAPI:
    MOCK_TREND = {
        "days": [
            {"date": "01/06/2026", "calories": 1800, "protein": 120, "workouts": 0},
            {"date": "02/06/2026", "calories": 2100, "protein": 140, "workouts": 1},
        ],
        "targets": {"calories": 2000, "protein": 150, "workouts_per_week": 3},
    }

    @patch("dashboard_views.DashboardStorage")
    def test_returns_json_with_days_and_targets(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_trend_data.return_value = self.MOCK_TREND
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/api/trend?days=7")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "days" in data
        assert "targets" in data
        assert len(data["days"]) == 2

    @patch("dashboard_views.DashboardStorage")
    def test_defaults_to_30_days(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_trend_data.return_value = {"days": [], "targets": {}}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/api/trend")
        assert resp.status_code == 200
        mock_storage.get_trend_data.assert_called_once_with(
            "test@example.com", days=30,
        )

    @patch("dashboard_views.DashboardStorage")
    def test_days_zero_for_all_history(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_trend_data.return_value = {"days": [], "targets": {}}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/api/trend?days=0")
        assert resp.status_code == 200
        mock_storage.get_trend_data.assert_called_once_with(
            "test@example.com", days=0,
        )

    def test_requires_login(self, client):
        resp = client.get("/dashboard/api/trend")
        assert resp.status_code == 302
