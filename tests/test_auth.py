from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock


class TestLogin:
    def test_login_redirects(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 302

    def test_logout_clears_session_and_redirects(self, client):
        with client.session_transaction() as sess:
            sess["user_email"] = "test@example.com"
        resp = client.get("/auth/logout")
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert "user_email" not in sess


class TestCallback:
    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_callback_creates_user_and_sets_session(self, mock_requests, mock_storage_cls, client, app):
        # Mock the Google token exchange
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test-token",
            "id_token": "test-id-token",
        }

        # Mock the userinfo response
        userinfo_response = MagicMock()
        userinfo_response.status_code = 200
        userinfo_response.json.return_value = {
            "email": "user@example.com",
            "name": "Test User",
        }

        mock_requests.post.return_value = token_response
        mock_requests.get.return_value = userinfo_response

        # Mock storage
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"

        with patch.object(app, 'config', {**app.config, 'APP_CONFIG': app.config['APP_CONFIG']}):
            resp = client.get("/auth/callback?code=test-code&state=test-state")

        assert resp.status_code == 302
