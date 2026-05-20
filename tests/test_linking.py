"""
test_linking — TDD tests for LinkingService and StartHandler.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from models.profile import UserProfile
from services.linking_service import LinkingService
from repositories.user_repository import UserRepository


def _make_user_repo():
    repo = MagicMock(spec=UserRepository)
    repo.get.return_value = None
    return repo


def _make_dashboard_col():
    return MagicMock()


class TestLinkingService:
    def test_valid_token_links_successfully(self):
        user_repo = _make_user_repo()
        dashboard = _make_dashboard_col()
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        dashboard.find_one.return_value = {
            "_id": "user@test.com",
            "name": "Test User",
            "telegram_user_id": None,
            "signup_session_token": "valid_token",
            "signup_session_token_expires_at": expires,
        }

        svc = LinkingService(user_repo, dashboard)
        result = svc.link(12345, "valid_token")

        assert result.status == "linked"
        assert result.profile is not None
        assert result.name == "Test User"
        user_repo.save.assert_called_once()
        dashboard.update_one.assert_called_once()
        update_set = dashboard.update_one.call_args[0][1]["$set"]
        assert update_set["telegram_user_id"] == 12345
        assert update_set["signup_session_token"] is None
        assert update_set["subscription_status"] == "trial_active"

    def test_expired_token_returns_invalid(self):
        user_repo = _make_user_repo()
        dashboard = _make_dashboard_col()
        dashboard.find_one.return_value = None

        svc = LinkingService(user_repo, dashboard)
        result = svc.link(12345, "expired_token")

        assert result.status == "invalid"
        assert result.profile is None
        user_repo.save.assert_not_called()

    def test_already_linked_returns_already_linked(self):
        user_repo = _make_user_repo()
        existing_profile = UserProfile(telegram_user_id=12345)
        user_repo.get.return_value = existing_profile

        dashboard = _make_dashboard_col()
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        dashboard.find_one.return_value = {
            "_id": "user@test.com",
            "telegram_user_id": 12345,  # Already linked
            "signup_session_token": "token",
            "signup_session_token_expires_at": expires,
        }

        svc = LinkingService(user_repo, dashboard)
        result = svc.link(12345, "token")

        assert result.status == "already_linked"
        assert result.profile is existing_profile
        dashboard.update_one.assert_not_called()

    def test_no_profile_returns_none(self):
        user_repo = _make_user_repo()
        dashboard = _make_dashboard_col()

        svc = LinkingService(user_repo, dashboard)
        result = svc.get_profile_without_token(99999)

        assert result is None
        user_repo.get.assert_called_once_with(99999)
