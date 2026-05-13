from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def _login(client):
    with client.session_transaction() as sess:
        sess["user_email"] = "test@example.com"
        sess["user_name"] = "Test"


class TestOnboardingSteps:
    @patch("onboarding.DashboardStorage")
    def test_step1_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": "test@example.com", "goals": {},
            "birth_year": None, "weight_kg": None, "height_cm": None,
        }
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/onboarding/step/1")
        assert resp.status_code == 200
        assert "שנת לידה".encode() in resp.data

    @patch("onboarding.DashboardStorage")
    def test_step1_post_saves_profile(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/onboarding/step/1", data={
            "birth_year": "1990", "weight_kg": "80", "height_cm": "175",
        })
        assert resp.status_code == 302
        mock_storage.update_user_profile.assert_called_once()
        profile = mock_storage.update_user_profile.call_args[0][1]
        assert profile["birth_year"] == 1990

    @patch("onboarding.DashboardStorage")
    def test_step2_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": "test@example.com", "goals": {},
            "birth_year": 1990, "weight_kg": 80, "height_cm": 175,
        }
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/onboarding/step/2")
        assert resp.status_code == 200
        assert "קלוריות".encode() in resp.data

    @patch("onboarding.DashboardStorage")
    def test_step2_post_saves_goals(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/onboarding/step/2", data={
            "calories_enabled": "1", "calories_target": "2200",
            "protein_enabled": "1", "protein_target": "160",
        })
        assert resp.status_code == 302
        goals = mock_storage.update_user_goals.call_args[0][1]
        assert goals["calories"]["target"] == 2200
        assert goals["protein"]["target"] == 160

    @patch("onboarding.DashboardStorage")
    def test_step3_renders(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {"_id": "test@example.com", "goals": {}}
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/onboarding/step/3")
        assert resp.status_code == 200
        assert "תנאים ופרטיות".encode() in resp.data

    @patch("onboarding.DashboardStorage")
    def test_step4_shows_bot_key(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": "test@example.com", "goals": {},
            "bot_key": "abc123def456",
        }
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/onboarding/step/4")
        assert resp.status_code == 200
        assert b"abc123def456" in resp.data

    @patch("onboarding.DashboardStorage")
    def test_step4_post_completes_onboarding(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.post("/onboarding/step/4")
        assert resp.status_code == 302
        mock_storage.complete_onboarding.assert_called_once_with("test@example.com")

    def test_redirects_when_not_logged_in(self, client):
        resp = client.get("/onboarding/step/1")
        assert resp.status_code == 302

    @patch("onboarding.DashboardStorage")
    def test_invalid_step_redirects(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        _login(client)
        resp = client.get("/onboarding/step/99")
        assert resp.status_code == 302
