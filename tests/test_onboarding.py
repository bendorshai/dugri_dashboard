"""
test_onboarding — Legacy test file, replaced by test_onboarding_v2.py.

Kept for backward compatibility verification of the constructor signature.
Full onboarding tests are in test_onboarding_v2.py.
"""

from unittest.mock import MagicMock

import pytest

from models.profile import UserProfile
from services.onboarding_service import OnboardingService
from services.conversation_state_service import ConversationStateService
from repositories.user_repository import UserRepository


def _make_service():
    user_repo = MagicMock(spec=UserRepository)
    state_svc = MagicMock(spec=ConversationStateService)
    return OnboardingService(user_repo, state_svc), user_repo, state_svc


def _make_profile(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123}
    defaults.update(kwargs)
    return UserProfile(**defaults)


class TestStartOnboarding:
    def test_returns_greeting_with_name_question(self):
        svc, _, state_svc = _make_service()
        greeting = svc.start_onboarding(123)
        assert "דוגרי" in greeting
        assert "איך" in greeting or "שם" in greeting or "אקרא" in greeting
        state_svc.set_pending.assert_called_once_with(123, "awaiting_name")


class TestHandleNameResponse:
    def test_saves_name_and_clears_pending(self):
        svc, user_repo, state_svc = _make_service()
        response = svc.handle_name_response(123, "שי")
        assert "שי" in response
        user_repo.update_fields.assert_called_once()
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["name"] == "שי"
        assert call_fields["onboarding.name_collected"] is True
        state_svc.clear_pending.assert_called_once_with(123)


class TestBackwardCompatConstructor:
    """OnboardingService can be constructed without toggle_service (backward compat)."""

    def test_constructor_without_toggle_service(self):
        user_repo = MagicMock(spec=UserRepository)
        state_svc = MagicMock(spec=ConversationStateService)
        svc = OnboardingService(user_repo, state_svc)
        # Should work without toggle_service
        greeting = svc.start_onboarding(123)
        assert len(greeting) > 0
