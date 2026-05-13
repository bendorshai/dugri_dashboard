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
    "goals": {
        "calories": {"enabled": True, "target": 2000},
        "protein": {"enabled": True, "target": 150},
    },
    "onboarding_complete": True,
}


class TestDashboardGoals:
    @patch("dashboard_views.DashboardStorage")
    def test_goals_page_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = MOCK_USER
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/dashboard/goals")
        assert resp.status_code == 200
        assert "הגדרת יעדים".encode() in resp.data

    @patch("dashboard_views.DashboardStorage")
    def test_goals_post_updates(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/dashboard/goals", data={
            "calories_enabled": "1", "calories_target": "1800",
        })
        assert resp.status_code == 302
        goals = mock_storage.update_user_goals.call_args[0][1]
        assert goals["calories"]["target"] == 1800

    @patch("dashboard_views.DashboardStorage")
    def test_index_redirects_to_goals(self, mock_storage_cls, client):
        _login(client)
        resp = client.get("/dashboard/")
        assert resp.status_code == 302


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
        resp = client.get("/dashboard/goals")
        assert resp.status_code == 302
