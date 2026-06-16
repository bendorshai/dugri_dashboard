"""
test_toggle_service - TDD tests for ToggleService.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from models.profile import User, ToggleState, Toggles
from services.toggle_service import ToggleService
from repositories.user_repository import UserRepository


def _make_service():
    user_repo = MagicMock(spec=UserRepository)
    return ToggleService(user_repo), user_repo


def _make_user(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123}
    defaults.update(kwargs)
    return User(**defaults)


class TestGetToggle:
    def test_returns_toggle_by_name(self):
        svc, _ = _make_service()
        user = _make_user(toggles=Toggles(sleep=ToggleState(status="active")))
        assert svc.get_toggle(user, "sleep").status == "active"

    def test_returns_dormant_for_default_toggle(self):
        svc, _ = _make_service()
        user = _make_user()
        assert svc.get_toggle(user, "workouts").status == "dormant"

    def test_raises_for_invalid_toggle_name(self):
        svc, _ = _make_service()
        user = _make_user()
        with pytest.raises(ValueError):
            svc.get_toggle(user, "coffee")


class TestRevealToggle:
    def test_sets_revealed_at(self):
        svc, user_repo = _make_service()
        svc.reveal_toggle(123, "sleep")
        user_repo.update_fields.assert_called_once()
        call_fields = user_repo.update_fields.call_args[0][1]
        assert "toggles.sleep.revealed_at" in call_fields

    def test_does_not_change_status(self):
        """Reveal marks the moment of first offer, but status stays dormant."""
        svc, user_repo = _make_service()
        svc.reveal_toggle(123, "sleep")
        call_fields = user_repo.update_fields.call_args[0][1]
        assert "toggles.sleep.status" not in call_fields


class TestActivateToggle:
    def test_sets_active_and_activated_at(self):
        svc, user_repo = _make_service()
        svc.activate_toggle(123, "workouts")
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["toggles.workouts.status"] == "active"
        assert "toggles.workouts.activated_at" in call_fields

    def test_resets_unanswered_counter(self):
        svc, user_repo = _make_service()
        svc.activate_toggle(123, "workouts")
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["toggles.workouts.consecutive_unanswered"] == 0


class TestCancelToggle:
    def test_sets_cancelled(self):
        svc, user_repo = _make_service()
        svc.cancel_toggle(123, "sleep")
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["toggles.sleep.status"] == "cancelled"


class TestRecordAsked:
    def test_updates_last_asked_at(self):
        svc, user_repo = _make_service()
        svc.record_asked(123, "sleep")
        call_fields = user_repo.update_fields.call_args[0][1]
        assert "toggles.sleep.last_asked_at" in call_fields


class TestRecordAnswered:
    def test_resets_consecutive_unanswered(self):
        svc, user_repo = _make_service()
        svc.record_answered(123, "sleep")
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["toggles.sleep.consecutive_unanswered"] == 0


class TestIncrementUnanswered:
    def test_increments_and_returns_new_count(self):
        svc, user_repo = _make_service()
        user = _make_user(toggles=Toggles(sleep=ToggleState(consecutive_unanswered=1)))
        result = svc.increment_unanswered(123, user, "sleep")
        assert result == 2
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["toggles.sleep.consecutive_unanswered"] == 2


class TestShouldShowExitDoor:
    def test_true_at_threshold(self):
        svc, _ = _make_service()
        user = _make_user(toggles=Toggles(sleep=ToggleState(
            status="active", consecutive_unanswered=2,
        )))
        assert svc.should_show_exit_door(user, "sleep") is True

    def test_false_below_threshold(self):
        svc, _ = _make_service()
        user = _make_user(toggles=Toggles(sleep=ToggleState(
            status="active", consecutive_unanswered=1,
        )))
        assert svc.should_show_exit_door(user, "sleep") is False

    def test_false_for_dormant_toggle(self):
        svc, _ = _make_service()
        user = _make_user(toggles=Toggles(sleep=ToggleState(
            status="dormant", consecutive_unanswered=5,
        )))
        assert svc.should_show_exit_door(user, "sleep") is False


class TestIsPastGate:
    def test_true_after_gate_days(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert svc.is_past_gate(user) is True

    def test_false_before_gate_days(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        assert svc.is_past_gate(user) is False

    def test_false_if_no_trial_started(self):
        svc, _ = _make_service()
        user = _make_user(trial_started_at=None)
        assert svc.is_past_gate(user) is False


class TestShouldRevealSleep:
    def test_true_when_dormant_and_never_revealed(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert svc.should_reveal_sleep(user) is True

    def test_false_when_already_revealed(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=1),
            toggles=Toggles(sleep=ToggleState(
                revealed_at=datetime.now(timezone.utc),
            )),
        )
        assert svc.should_reveal_sleep(user) is False

    def test_false_when_active(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=1),
            toggles=Toggles(sleep=ToggleState(status="active")),
        )
        assert svc.should_reveal_sleep(user) is False

    def test_false_on_same_day_as_trial_start(self):
        """Sleep is gated to 24h - must not reveal on day 0."""
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(hours=6),
        )
        assert svc.should_reveal_sleep(user) is False

    def test_false_when_no_trial_started(self):
        svc, _ = _make_service()
        user = _make_user(trial_started_at=None)
        assert svc.should_reveal_sleep(user) is False


class TestShouldRevealWorkouts:
    def test_true_on_thursday_after_gate(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert svc.should_reveal_workouts(user, weekday=3) is True  # Thursday

    def test_false_on_non_thursday(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert svc.should_reveal_workouts(user, weekday=2) is False  # Wednesday

    def test_false_before_gate(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        assert svc.should_reveal_workouts(user, weekday=3) is False

    def test_false_when_already_active(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
            toggles=Toggles(workouts=ToggleState(status="active")),
        )
        assert svc.should_reveal_workouts(user, weekday=3) is False


class TestShouldRevealSelfCare:
    def test_true_on_friday_after_gate(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert svc.should_reveal_self_care(user, weekday=4) is True  # Friday

    def test_false_on_non_friday(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert svc.should_reveal_self_care(user, weekday=3) is False


class TestShouldRevealEatingWindow:
    def test_true_after_gate(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert svc.should_reveal_eating_window(user) is True

    def test_false_before_gate(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        assert svc.should_reveal_eating_window(user) is False

    def test_false_when_already_revealed(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
            toggles=Toggles(eating_window=ToggleState(
                revealed_at=datetime.now(timezone.utc),
            )),
        )
        assert svc.should_reveal_eating_window(user) is False


class TestShouldShowDashboardIntro:
    def test_true_on_day_16(self):
        svc, _ = _make_service()
        user = _make_user()
        assert svc.should_show_dashboard_intro(user, day_number=16) is True

    def test_false_if_already_shown(self):
        svc, _ = _make_service()
        user = _make_user(dashboard_intro_shown=True)
        assert svc.should_show_dashboard_intro(user, day_number=16) is False

    def test_false_before_day_16(self):
        svc, _ = _make_service()
        user = _make_user()
        assert svc.should_show_dashboard_intro(user, day_number=10) is False


class TestGetDayNumber:
    def test_returns_correct_day(self):
        svc, _ = _make_service()
        user = _make_user(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert svc.get_day_number(user) == 5

    def test_returns_0_if_no_trial(self):
        svc, _ = _make_service()
        user = _make_user(trial_started_at=None)
        assert svc.get_day_number(user) == 0
