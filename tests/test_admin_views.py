from __future__ import annotations

from unittest.mock import patch, MagicMock


class TestAdminAuth:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/admin/")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_non_admin_gets_403(self, client):
        with client.session_transaction() as sess:
            sess["user_email"] = "regular@example.com"
        resp = client.get("/admin/")
        assert resp.status_code == 403

    @patch("admin_views.AdminStorage")
    def test_admin_can_access(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_total_users.return_value = 5
        mock_storage.get_total_signups.return_value = 10
        mock_storage.get_active_this_week.return_value = 3
        mock_storage.get_signup_funnel.return_value = {
            "total_signups": 10,
            "linked_to_bot": 5,
            "activated_24h_from_signup": 3,
            "activated_24h_from_link": 4,
        }
        mock_storage.get_dau_30_days.return_value = []
        mock_storage.get_habit_adoption.return_value = {}
        mock_storage.get_activity_hours.return_value = [0] * 24
        mock_storage.get_churn_curve.return_value = []
        mock_storage.get_super_active_users.return_value = []
        mock_storage.get_churning_users.return_value = []
        mock_storage.get_stuck_at_gate_users.return_value = []
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["user_email"] = "admin@test.com"

        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"Dugri Admin" in resp.data

    @patch("admin_views.AdminStorage")
    def test_kpi_values_rendered(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_total_users.return_value = 42
        mock_storage.get_total_signups.return_value = 100
        mock_storage.get_active_this_week.return_value = 15
        mock_storage.get_signup_funnel.return_value = {
            "total_signups": 100,
            "linked_to_bot": 42,
            "activated_24h_from_signup": 30,
            "activated_24h_from_link": 35,
        }
        mock_storage.get_dau_30_days.return_value = []
        mock_storage.get_habit_adoption.return_value = {}
        mock_storage.get_activity_hours.return_value = [0] * 24
        mock_storage.get_churn_curve.return_value = []
        mock_storage.get_super_active_users.return_value = []
        mock_storage.get_churning_users.return_value = []
        mock_storage.get_stuck_at_gate_users.return_value = []
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["user_email"] = "admin@test.com"

        resp = client.get("/admin/")
        html = resp.data.decode()
        assert "42" in html
        assert "15" in html

    @patch("admin_views.AdminStorage")
    def test_leads_rendered(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_total_users.return_value = 1
        mock_storage.get_total_signups.return_value = 2
        mock_storage.get_active_this_week.return_value = 1
        mock_storage.get_signup_funnel.return_value = {
            "total_signups": 2,
            "linked_to_bot": 1,
            "activated_24h_from_signup": 1,
            "activated_24h_from_link": 1,
        }
        mock_storage.get_dau_30_days.return_value = []
        mock_storage.get_habit_adoption.return_value = {}
        mock_storage.get_activity_hours.return_value = [0] * 24
        mock_storage.get_churn_curve.return_value = []
        mock_storage.get_super_active_users.return_value = [
            {
                "email": "active@test.com",
                "name": "Active User",
                "telegram_user_id": 99999,
                "category": "super_active",
                "signup_date": "2026-05-20T10:00:00",
                "last_active": "2026-05-22T12:00:00",
            }
        ]
        mock_storage.get_churning_users.return_value = []
        mock_storage.get_stuck_at_gate_users.return_value = []
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["user_email"] = "admin@test.com"

        resp = client.get("/admin/")
        html = resp.data.decode()
        assert "Active User" in html
        assert "active@test.com" in html
        assert "tg://user?id=99999" in html
