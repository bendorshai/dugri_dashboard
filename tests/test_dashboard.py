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


class TestDashboardLegacyRedirects:
    def test_goals_redirects_to_preferences(self, client):
        _login(client)
        resp = client.get("/dashboard/goals")
        assert resp.status_code == 302
        assert "preferences" in resp.location

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


class TestCalorieTrendAPI:
    @patch("dashboard_views.DashboardStorage")
    def test_returns_json_with_days_and_target(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_daily_calorie_totals.return_value = {
            "days": [
                {"date": "01/06/2026", "calories": 1800},
                {"date": "02/06/2026", "calories": 2100},
            ],
            "target": 2000,
        }
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/api/calorie-trend?days=7")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "days" in data
        assert "target" in data
        assert len(data["days"]) == 2

    @patch("dashboard_views.DashboardStorage")
    def test_defaults_to_30_days(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_daily_calorie_totals.return_value = {"days": [], "target": None}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/api/calorie-trend")
        assert resp.status_code == 200
        mock_storage.get_daily_calorie_totals.assert_called_once_with(
            "test@example.com", days=30,
        )

    @patch("dashboard_views.DashboardStorage")
    def test_caps_days_at_90(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_daily_calorie_totals.return_value = {"days": [], "target": None}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/api/calorie-trend?days=999")
        assert resp.status_code == 200
        mock_storage.get_daily_calorie_totals.assert_called_once_with(
            "test@example.com", days=90,
        )

    def test_requires_login(self, client):
        resp = client.get("/dashboard/api/calorie-trend")
        assert resp.status_code == 302
