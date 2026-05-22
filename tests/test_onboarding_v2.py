"""
test_onboarding_v2 — TDD tests for the rewritten OnboardingService.

The new onboarding is minimal: name collection + post-meal target offer.
Habit reveals (sleep, workouts, self-care, eating window) are handled by
the hook system, not onboarding.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models.profile import User, Toggles, ToggleState
from services.onboarding_service import OnboardingService
from services.conversation_state_service import ConversationStateService
from services.toggle_service import ToggleService
from repositories.user_repository import UserRepository
import messages as M


def _make_service():
    user_repo = MagicMock(spec=UserRepository)
    state_svc = MagicMock(spec=ConversationStateService)
    toggle_svc = MagicMock(spec=ToggleService)
    return OnboardingService(user_repo, state_svc, toggle_svc), user_repo, state_svc, toggle_svc


def _make_user(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123}
    defaults.update(kwargs)
    return User(**defaults)


class TestStartOnboarding:
    def test_returns_greeting(self):
        svc, _, state_svc, _ = _make_service()
        greeting = svc.start_onboarding(123)
        assert "דוגרי" in greeting
        state_svc.set_pending.assert_called_once_with(123, "awaiting_name")

    def test_greeting_asks_for_name(self):
        svc, _, _, _ = _make_service()
        greeting = svc.start_onboarding(123)
        assert "אקרא" in greeting or "שם" in greeting


class TestHandleNameResponse:
    def test_saves_name(self):
        svc, user_repo, state_svc, _ = _make_service()
        response = svc.handle_name_response(123, "שי")
        assert "שי" in response
        user_repo.update_fields.assert_called_once()
        fields = user_repo.update_fields.call_args[0][1]
        assert fields["name"] == "שי"
        assert fields["onboarding.name_collected"] is True

    def test_clears_pending(self):
        svc, _, state_svc, _ = _make_service()
        svc.handle_name_response(123, "שי")
        state_svc.clear_pending.assert_called_once_with(123)

    def test_invites_first_meal(self):
        svc, _, _, _ = _make_service()
        response = svc.handle_name_response(123, "דנה")
        assert "אכלת" in response or "אוכל" in response


class TestShouldOfferTarget:
    def test_true_on_first_meal_when_dormant(self):
        svc, _, _, _ = _make_service()
        user = _make_user()
        assert svc.should_offer_target(user, meal_count=1) is True

    def test_false_on_second_meal(self):
        svc, _, _, _ = _make_service()
        user = _make_user()
        assert svc.should_offer_target(user, meal_count=2) is False

    def test_false_when_target_already_active(self):
        svc, _, _, _ = _make_service()
        user = _make_user(toggles=Toggles(
            target_data=ToggleState(status="active"),
        ))
        assert svc.should_offer_target(user, meal_count=1) is False

    def test_false_when_target_cancelled(self):
        svc, _, _, _ = _make_service()
        user = _make_user(toggles=Toggles(
            target_data=ToggleState(status="cancelled"),
        ))
        assert svc.should_offer_target(user, meal_count=1) is False


class TestOfferTarget:
    def test_returns_offer_text(self):
        svc, _, state_svc, toggle_svc = _make_service()
        text = svc.offer_target(123)
        assert "גובה" in text or "משקל" in text or "יעד" in text
        state_svc.set_pending.assert_called_once_with(123, "awaiting_target_consent")

    def test_reveals_target_toggle(self):
        svc, _, _, toggle_svc = _make_service()
        svc.offer_target(123)
        toggle_svc.reveal_toggle.assert_called_once_with(123, "target_data")


class TestHandleTargetConsent:
    def test_accepted_asks_body_stats(self):
        svc, _, state_svc, _ = _make_service()
        response = svc.handle_target_consent(123, accepted=True)
        assert "גובה" in response
        state_svc.set_pending.assert_called_with(123, "awaiting_body_stats")

    def test_declined_keeps_dormant(self):
        svc, _, state_svc, _ = _make_service()
        response = svc.handle_target_consent(123, accepted=False)
        state_svc.clear_pending.assert_called_once_with(123)
        # Should NOT activate or cancel — stays dormant for day 9 retry
        assert "בסדר" in response or "נמשיך" in response or "בעיה" in response


class TestNoLongerOffersHabits:
    """Verify that old habit offer methods no longer exist."""

    def test_no_should_offer_eating_window(self):
        svc, _, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_eating_window")

    def test_no_should_offer_sleep(self):
        svc, _, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_sleep")

    def test_no_should_offer_workouts(self):
        svc, _, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_workouts")

    def test_no_should_offer_self_care(self):
        svc, _, _, _ = _make_service()
        assert not hasattr(svc, "should_offer_self_care")
