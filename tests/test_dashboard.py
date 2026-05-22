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
        "target_data": {"status": "dormant"},
        "weekly_summary": {"status": "active"},
    },
    "onboarding_complete": True,
}


class TestDashboardToggles:
    @patch("dashboard_views.DashboardStorage")
    def test_toggles_page_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/toggles")
        assert resp.status_code == 200
        assert "מתגים".encode() in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_toggles_post_updates(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/dashboard/toggles", data={
            "sleep_enabled": "1",
            "weekly_summary_enabled": "1",
        })
        assert resp.status_code == 302
        toggles = mock_storage.update_user_toggles.call_args[0][1]
        assert toggles["sleep"]["status"] == "active"
        assert toggles["weekly_summary"]["status"] == "active"


class TestDashboardTargets:
    @patch("dashboard_views.DashboardStorage")
    def test_targets_page_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/targets")
        assert resp.status_code == 200
        assert "יעדים".encode() in resp.data


class TestDashboardGoalsRedirect:
    @patch("dashboard_views.DashboardStorage")
    def test_goals_redirects_to_toggles(self, mock_storage_cls, client):
        _login(client)
        resp = client.get("/dashboard/goals")
        assert resp.status_code == 302
        assert "toggles" in resp.location


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
