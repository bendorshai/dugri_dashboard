"""
test_onboarding_v2 - TDD tests for the rewritten OnboardingService.

The new onboarding is minimal: name collection + post-meal target offer.
Habit reveals (sleep, workouts, self-care, eating window) are handled by
the hook system, not onboarding.
"""

from unittest.mock import MagicMock

from models.profile import User
from services.onboarding_service import OnboardingService
from services.toggle_service import ToggleService
from repositories.user_repository import UserRepository


def _make_service():
    user_repo = MagicMock(spec=UserRepository)
    toggle_svc = MagicMock(spec=ToggleService)
    return OnboardingService(user_repo), user_repo, toggle_svc


def _make_user(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123}
    defaults.update(kwargs)
    return User(**defaults)


class TestStartOnboarding:
    def test_returns_greeting(self):
        svc, _, _ = _make_service()
        greeting = svc.start_onboarding(123)
        assert "דוגרי" in greeting

    def test_greeting_asks_for_name(self):
        svc, _, _ = _make_service()
        greeting = svc.start_onboarding(123)
        assert "אקרא" in greeting or "שם" in greeting


class TestHandleNameResponse:
    def test_saves_name(self):
        svc, user_repo, _ = _make_service()
        response = svc.handle_name_response(123, "שי")
        assert "שי" in response
        user_repo.update_fields.assert_called_once()
        fields = user_repo.update_fields.call_args[0][1]
        assert fields["name"] == "שי"
        assert fields["onboarding.name_collected"] is True

    def test_asks_gender_after_name(self):
        svc, _, _ = _make_service()
        response = svc.handle_name_response(123, "דנה")
        assert "בן או בת" in response


class TestNoLongerOffersHabits:
    """Verify that old habit offer methods no longer exist."""

    def test_no_should_offer_eating_window(self):
        svc, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_eating_window")

    def test_no_should_offer_sleep(self):
        svc, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_sleep")

    def test_no_should_offer_workouts(self):
        svc, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_workouts")

    def test_no_should_offer_self_care(self):
        svc, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_self_care")
