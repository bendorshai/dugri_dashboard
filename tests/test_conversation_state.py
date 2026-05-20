"""
test_conversation_state — TDD tests for ConversationStateService.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from models.profile import UserProfile, PendingState
from services.conversation_state_service import ConversationStateService, PENDING_TTL_SECONDS
from repositories.user_repository import UserRepository


def _make_service():
    repo = MagicMock(spec=UserRepository)
    return ConversationStateService(repo), repo


class TestConversationStateService:
    def test_get_pending_returns_none_when_no_state(self):
        svc, _ = _make_service()
        profile = UserProfile(telegram_user_id=123, pending_state=None)
        assert svc.get_pending(profile) is None

    def test_get_pending_returns_state_when_fresh(self):
        svc, _ = _make_service()
        state = PendingState(kind="awaiting_name", created_at=datetime.now(timezone.utc))
        profile = UserProfile(telegram_user_id=123, pending_state=state)
        result = svc.get_pending(profile)
        assert result is not None
        assert result.kind == "awaiting_name"

    def test_get_pending_clears_expired_state(self):
        svc, repo = _make_service()
        old_time = datetime.now(timezone.utc) - timedelta(seconds=PENDING_TTL_SECONDS + 10)
        state = PendingState(kind="awaiting_name", created_at=old_time)
        profile = UserProfile(telegram_user_id=123, pending_state=state)
        result = svc.get_pending(profile)
        assert result is None
        repo.update_fields.assert_called_once()

    def test_set_pending_updates_profile(self):
        svc, repo = _make_service()
        svc.set_pending(123, "awaiting_name", {"extra": "data"})
        repo.update_fields.assert_called_once()
        call_args = repo.update_fields.call_args[0]
        assert call_args[0] == 123
        pending = call_args[1]["pending_state"]
        assert pending["kind"] == "awaiting_name"
        assert pending["data"] == {"extra": "data"}

    def test_clear_pending_sets_none(self):
        svc, repo = _make_service()
        svc.clear_pending(123)
        repo.update_fields.assert_called_once()
        call_args = repo.update_fields.call_args[0]
        assert call_args[1]["pending_state"] is None

    def test_dispatch_returns_result_when_pending(self):
        svc, _ = _make_service()
        state = PendingState(kind="awaiting_name", data={"x": 1})
        profile = UserProfile(telegram_user_id=123, pending_state=state)
        result = svc.dispatch(profile, "hello")
        assert result is not None
        assert result.kind == "awaiting_name"
        assert result.data == {"x": 1}

    def test_dispatch_returns_none_when_no_pending(self):
        svc, _ = _make_service()
        profile = UserProfile(telegram_user_id=123, pending_state=None)
        result = svc.dispatch(profile, "hello")
        assert result is None
