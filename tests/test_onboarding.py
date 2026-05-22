"""
test_onboarding — TDD tests for OnboardingService.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models.profile import UserProfile, Onboarding, OnboardingHabits, HabitState
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


class TestHabitOffers:
    def test_does_not_offer_nutrition_if_already_active(self):
        svc, _, _ = _make_service()
        profile = _make_profile(
            onboarding=Onboarding(
                habits=OnboardingHabits(
                    nutrition=HabitState(state="active"),
                ),
            ),
        )
        assert svc.should_offer_calorie_target(profile, 1) is False

    def test_does_not_offer_nutrition_if_declined(self):
        svc, _, _ = _make_service()
        profile = _make_profile(
            onboarding=Onboarding(
                habits=OnboardingHabits(
                    nutrition=HabitState(state="declined"),
                ),
            ),
        )
        assert svc.should_offer_calorie_target(profile, 1) is False

    def test_offers_nutrition_on_first_meal(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_calorie_target(profile, 1) is True

    def test_does_not_offer_nutrition_on_second_meal(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_calorie_target(profile, 2) is False

    def test_offers_eating_window_on_first_meal(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_eating_window(profile, 1) is True

    def test_offers_sleep_late_at_night(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_sleep(profile, 23) is True

    def test_does_not_offer_sleep_during_day(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_sleep(profile, 14) is False

    def test_offers_workouts_after_7_days(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_workouts(profile, 7) is True

    def test_does_not_offer_workouts_before_7_days(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_workouts(profile, 3) is False

    def test_offers_self_care_after_10_days(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.should_offer_self_care(profile, 10) is True


class TestConsentHandling:
    def test_accepted_nutrition_sets_active_and_asks_body_stats(self):
        svc, user_repo, state_svc = _make_service()
        response = svc.handle_consent_response(123, "awaiting_calorie_target_consent", True)
        assert "גובה" in response
        state_svc.clear_pending.assert_called_once()
        state_svc.set_pending.assert_called_with(123, "awaiting_body_stats")

    def test_declined_nutrition_sets_declined(self):
        svc, user_repo, state_svc = _make_service()
        response = svc.handle_consent_response(123, "awaiting_calorie_target_consent", False)
        assert "בסדר" in response
        update_fields = user_repo.update_fields.call_args[0][1]
        assert update_fields["onboarding.habits.nutrition.state"] == "declined"
        state_svc.clear_pending.assert_called_once()

    def test_accepted_eating_window_asks_for_window(self):
        svc, _, state_svc = _make_service()
        response = svc.handle_consent_response(123, "awaiting_eating_window_consent", True)
        assert "HH:MM" in response
        state_svc.set_pending.assert_called_with(123, "awaiting_eating_window")
