from __future__ import annotations

from unittest.mock import patch, MagicMock

from hebrew_strings import ERROR_MISSING_CONSENT


class TestLogin:
    def test_login_without_consents_redirects_with_error(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 302
        assert "/" in resp.headers["Location"]

    def test_login_without_medical_consent_redirects_with_error(self, client):
        resp = client.get("/auth/login?terms=1")
        assert resp.status_code == 302

    def test_login_with_consents_redirects_to_google(self, client):
        resp = client.get("/auth/login?terms=1&medical=1")
        assert resp.status_code == 302
        assert "accounts.google.com" in resp.headers["Location"]

    def test_login_stores_consents_in_session(self, client):
        client.get("/auth/login?terms=1&medical=1&marketing=1")
        with client.session_transaction() as sess:
            assert sess["pending_consents"]["terms"] is True
            assert sess["pending_consents"]["medical"] is True
            assert sess["pending_consents"]["marketing"] is True

    def test_login_marketing_defaults_to_false(self, client):
        client.get("/auth/login?terms=1&medical=1")
        with client.session_transaction() as sess:
            assert sess["pending_consents"]["marketing"] is False

    def test_returning_user_skips_consent_check(self, client):
        with client.session_transaction() as sess:
            sess["user_email"] = "test@example.com"
        resp = client.get("/auth/login")
        assert resp.status_code == 302
        assert "accounts.google.com" in resp.headers["Location"]


class TestLogout:
    def test_logout_clears_session_and_redirects(self, client):
        with client.session_transaction() as sess:
            sess["user_email"] = "test@example.com"
        resp = client.get("/auth/logout")
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert "user_email" not in sess


def _setup_oauth_mocks(mock_requests, email="user@example.com", name="Test User", picture=None):
    """Helper to mock Google OAuth token + userinfo responses."""
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


class TestCallbackNewUser:
    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_creates_user_with_consents(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_storage.create_user.return_value = {"telegram_user_id": None}
        mock_storage.regenerate_signup_session_token.return_value = "new-token"
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"
            sess["pending_consents"] = {"terms": True, "medical": True, "marketing": False}

        resp = client.get("/auth/callback?code=test-code&state=test-state")
        assert resp.status_code == 302
        assert "post_signup=1" in resp.headers["Location"]

        mock_storage.create_user.assert_called_once()
        call_kwargs = mock_storage.create_user.call_args
        assert call_kwargs[1]["consents"]["terms_accepted_at"] is not None
        assert call_kwargs[1]["consents"]["marketing_opt_in"] is False

    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_captures_photo_url(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests, picture="https://photo.url/pic.jpg")
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_storage.create_user.return_value = {"telegram_user_id": None}
        mock_storage.regenerate_signup_session_token.return_value = "tok"
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"
            sess["pending_consents"] = {"terms": True, "medical": True, "marketing": False}

        client.get("/auth/callback?code=test-code&state=test-state")
        call_kwargs = mock_storage.create_user.call_args
        assert call_kwargs[1]["photo_url"] == "https://photo.url/pic.jpg"

    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_generates_signup_session_token(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_storage.create_user.return_value = {"telegram_user_id": None}
        mock_storage.regenerate_signup_session_token.return_value = "abc123"
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"
            sess["pending_consents"] = {"terms": True, "medical": True, "marketing": False}

        client.get("/auth/callback?code=test-code&state=test-state")
        mock_storage.regenerate_signup_session_token.assert_called_once_with("user@example.com")

        with client.session_transaction() as sess:
            assert sess["signup_session_token"] == "abc123"

    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_rejects_new_user_without_consents(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = None
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"
            # No pending_consents in session

        resp = client.get("/auth/callback?code=test-code&state=test-state")
        assert resp.status_code == 302
        mock_storage.create_user.assert_not_called()


class TestCallbackReturningUser:
    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_returning_user_with_telegram_goes_to_dashboard(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": "user@example.com",
            "telegram_user_id": 12345,
            "photo_url": None,
        }
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"

        resp = client.get("/auth/callback?code=test-code&state=test-state")
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]

    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_returning_user_without_telegram_gets_new_token(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": "user@example.com",
            "telegram_user_id": None,
            "photo_url": None,
        }
        mock_storage.regenerate_signup_session_token.return_value = "fresh-token"
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"

        resp = client.get("/auth/callback?code=test-code&state=test-state")
        assert resp.status_code == 302
        assert "post_signup=1" in resp.headers["Location"]
        mock_storage.regenerate_signup_session_token.assert_called_once()

    @patch("auth.DashboardStorage")
    @patch("auth.requests")
    def test_returning_user_skips_consent_validation(self, mock_requests, mock_storage_cls, client):
        _setup_oauth_mocks(mock_requests)
        mock_storage = MagicMock()
        mock_storage.get_user.return_value = {
            "_id": "user@example.com",
            "telegram_user_id": None,
            "photo_url": None,
        }
        mock_storage.regenerate_signup_session_token.return_value = "tok"
        mock_storage_cls.return_value = mock_storage

        with client.session_transaction() as sess:
            sess["oauth_state"] = "test-state"
            # No pending_consents — should still work for returning user

        resp = client.get("/auth/callback?code=test-code&state=test-state")
        assert resp.status_code == 302
        mock_storage.create_user.assert_not_called()
