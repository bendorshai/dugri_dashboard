"""
test_onboarding - Legacy test file, replaced by test_onboarding_v2.py.

Kept for backward compatibility verification of the constructor signature.
Full onboarding tests are in test_onboarding_v2.py.
"""

from unittest.mock import MagicMock

import pytest

from models.profile import UserProfile
from services.onboarding_service import OnboardingService
from repositories.user_repository import UserRepository


def _make_service():
    user_repo = MagicMock(spec=UserRepository)
    return OnboardingService(user_repo), user_repo


def _make_profile(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123}
    defaults.update(kwargs)
    return UserProfile(**defaults)


class TestStartOnboarding:
    def test_returns_greeting_with_name_question(self):
        svc, _ = _make_service()
        greeting = svc.start_onboarding(123)
        assert "דוגרי" in greeting
        assert "איך" in greeting or "שם" in greeting or "אקרא" in greeting


class TestHandleNameResponse:
    def test_saves_name_and_clears_pending(self):
        svc, user_repo = _make_service()
        response = svc.handle_name_response(123, "שי")
        assert "שי" in response
        user_repo.update_fields.assert_called_once()
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["name"] == "שי"
        assert call_fields["onboarding.name_collected"] is True

    def test_direct_response_asks_gender(self):
        """Direct name response (after greeting) asks בן או בת."""
        svc, _ = _make_service()
        response = svc.handle_name_response(123, "שי", late=False)
        assert "שי" in response
        assert "בן או בת" in response

    def test_late_declaration_short_ack(self):
        """Late name declaration gets a short acknowledgment, no 'מה אכלת?'."""
        svc, _ = _make_service()
        response = svc.handle_name_response(123, "דני", late=True)
        assert "דני" in response
        assert "ארוחה" not in response
        assert "נתחיל" not in response


class TestHandleGenderResponse:
    def test_saves_gender_male(self):
        svc, user_repo = _make_service()
        response = svc.handle_gender_response(123, "male")
        user_repo.update_fields.assert_called_once_with(123, {"gender": "male"})
        assert len(response) > 0

    def test_saves_gender_female(self):
        svc, user_repo = _make_service()
        response = svc.handle_gender_response(123, "female")
        user_repo.update_fields.assert_called_once_with(123, {"gender": "female"})
        assert len(response) > 0

    def test_response_includes_meal_invite(self):
        """After gender is collected, the intro continues with meal invite."""
        svc, _ = _make_service()
        response = svc.handle_gender_response(123, "male")
        assert "ארוחה" in response


class TestBackwardCompatConstructor:
    """OnboardingService can be constructed with just user_repo."""

    def test_constructor_minimal(self):
        user_repo = MagicMock(spec=UserRepository)
        svc = OnboardingService(user_repo)
        greeting = svc.start_onboarding(123)
        assert len(greeting) > 0
