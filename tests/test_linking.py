"""
test_linking — TDD tests for LinkingService and StartHandler.

After the merge, LinkingService operates on a single 'users' collection
via UserRepository. No separate dashboard_users_collection.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from models.profile import User
from services.linking_service import LinkingService
from repositories.user_repository import UserRepository


def _make_user_repo():
    repo = MagicMock(spec=UserRepository)
    repo.get.return_value = None
    repo.get_by_signup_token.return_value = None
    return repo


class TestLinkingService:
    def test_valid_token_links_successfully(self):
        user_repo = _make_user_repo()
        dashboard_user = User(
            email="user@test.com",
            name="Test User",
            telegram_user_id=None,
            subscription_status="trial_pending",
        )
        user_repo.get_by_signup_token.return_value = dashboard_user
        # After update, get() returns the updated user
        linked_user = User(
            email="user@test.com",
            name="Test User",
            telegram_user_id=12345,
            subscription_status="trial_active",
        )
        user_repo.get.return_value = linked_user

        svc = LinkingService(user_repo)
        result = svc.link(12345, "valid_token")

        assert result.status == "linked"
        assert result.profile is not None
        assert result.profile.telegram_user_id == 12345
        assert result.name == "Test User"
        user_repo.update_fields_by_email.assert_called_once()
        update_fields = user_repo.update_fields_by_email.call_args[0][1]
        assert update_fields["telegram_user_id"] == 12345
        assert update_fields["signup_session_token"] is None
        assert update_fields["subscription_status"] == "trial_active"
        # trial_started_at is NOT set at linking - it starts on first real message
        assert "trial_started_at" not in update_fields

    def test_expired_token_returns_invalid(self):
        user_repo = _make_user_repo()
        user_repo.get_by_signup_token.return_value = None

        svc = LinkingService(user_repo)
        result = svc.link(12345, "expired_token")

        assert result.status == "invalid"
        assert result.profile is None
        user_repo.update_fields_by_email.assert_not_called()

    def test_already_linked_returns_already_linked(self):
        user_repo = _make_user_repo()
        existing_user = User(
            email="user@test.com",
            telegram_user_id=12345,
            subscription_status="trial_active",
        )
        user_repo.get_by_signup_token.return_value = existing_user

        svc = LinkingService(user_repo)
        result = svc.link(12345, "token")

        assert result.status == "already_linked"
        assert result.profile is existing_user
        user_repo.update_fields_by_email.assert_not_called()

    def test_no_profile_returns_none(self):
        user_repo = _make_user_repo()

        svc = LinkingService(user_repo)
        result = svc.get_profile_without_token(99999)

        assert result is None
        user_repo.get.assert_called_once_with(99999)
