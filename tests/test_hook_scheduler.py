"""
test_hook_scheduler — TDD tests for the hook scheduling system.

Tests the hook scheduling, random time generation, inline hook detection,
and hook callback behavior.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from models.profile import User, ToggleState, Toggles
from constants import (
    SLEEP_HOOK_WINDOW,
    WORKOUTS_HOOK_WINDOW,
    SELF_CARE_HOOK_WINDOW,
    WEEKLY_SUMMARY_HOOK_WINDOW,
    WORKOUTS_ANCHOR_DAY,
    SELF_CARE_ANCHOR_DAY,
    WEEKLY_SUMMARY_ANCHOR_DAY,
)
from scheduler import (
    should_fire_inline,
    get_hooks_to_schedule,
)
from user_clock import UserClock


def _make_user(**kwargs):
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "trial_started_at": datetime.now(timezone.utc) - timedelta(days=10),
    }
    defaults.update(kwargs)
    return User(**defaults)


def _clock(utc_time=None):
    """Create a UserClock for Israel timezone, optionally pinned to a UTC time."""
    if utc_time and utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=timezone.utc)
    return UserClock("Asia/Jerusalem", _now_override=utc_time)


class TestShouldPiggyback:
    def test_true_when_hook_not_fired_today(self):
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=None),
        ))
        assert should_fire_inline(user, "sleep", _clock(datetime(2026, 5, 22, 9, 0))) is True

    def test_false_when_hook_already_fired_today(self):
        today_morning = datetime(2026, 5, 22, 8, 30, tzinfo=timezone.utc)
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=today_morning),
        ))
        clock = _clock(datetime(2026, 5, 22, 12, 0))
        assert should_fire_inline(user, "sleep", clock) is False

    def test_true_when_last_asked_was_yesterday(self):
        yesterday = datetime(2026, 5, 21, 9, 0, tzinfo=timezone.utc)
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=yesterday),
        ))
        clock = _clock(datetime(2026, 5, 22, 12, 0))
        assert should_fire_inline(user, "sleep", clock) is True

    def test_false_when_toggle_dormant(self):
        user = _make_user()
        assert should_fire_inline(user, "sleep", _clock(datetime(2026, 5, 22, 9, 0))) is False

    def test_false_when_toggle_cancelled(self):
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="cancelled"),
        ))
        assert should_fire_inline(user, "sleep", _clock(datetime(2026, 5, 22, 9, 0))) is False

    def test_no_double_fire_across_midnight_utc(self):
        """Critical bug fix: hook at 01:00 Israel (22:00 UTC prev day)
        should not fire again at 02:00 Israel (23:00 UTC prev day)."""
        # Hook fired at 01:00 Israel June 5 = 22:00 UTC June 4
        last_asked = datetime(2026, 6, 4, 22, 0, tzinfo=timezone.utc)
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=last_asked),
        ))
        # Poller at 02:00 Israel June 5 = 23:00 UTC June 4
        clock = _clock(datetime(2026, 6, 4, 23, 0))
        assert should_fire_inline(user, "sleep", clock) is False

    def test_fires_on_new_local_day_after_midnight(self):
        """Hook fired yesterday at 23:00 Israel, should fire today."""
        # Hook fired at 23:00 Israel June 4 = 20:00 UTC June 4
        last_asked = datetime(2026, 6, 4, 20, 0, tzinfo=timezone.utc)
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=last_asked),
        ))
        # Now: 09:00 Israel June 5 = 06:00 UTC June 5
        clock = _clock(datetime(2026, 6, 5, 6, 0))
        assert should_fire_inline(user, "sleep", clock) is True


class TestGetHooksToSchedule:
    def test_active_sleep_gets_daily_hook(self):
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active"),
        ))
        hooks = get_hooks_to_schedule(user)
        sleep_hooks = [h for h in hooks if h["toggle_name"] == "sleep"]
        assert len(sleep_hooks) == 1
        assert sleep_hooks[0]["schedule_type"] == "daily"
        assert sleep_hooks[0]["window"] == SLEEP_HOOK_WINDOW

    def test_active_workouts_gets_weekly_hook(self):
        user = _make_user(toggles=Toggles(
            workouts=ToggleState(status="active"),
        ))
        hooks = get_hooks_to_schedule(user)
        workout_hooks = [h for h in hooks if h["toggle_name"] == "workouts"]
        assert len(workout_hooks) == 1
        assert workout_hooks[0]["schedule_type"] == "weekly"
        assert workout_hooks[0]["anchor_day"] == WORKOUTS_ANCHOR_DAY

    def test_active_self_care_gets_weekly_hook(self):
        user = _make_user(toggles=Toggles(
            self_care=ToggleState(status="active"),
        ))
        hooks = get_hooks_to_schedule(user)
        sc_hooks = [h for h in hooks if h["toggle_name"] == "self_care"]
        assert len(sc_hooks) == 1
        assert sc_hooks[0]["anchor_day"] == SELF_CARE_ANCHOR_DAY

    def test_active_eating_window_not_scheduled_as_hook(self):
        """Eating window is auto-computed, not a proactive hook."""
        user = _make_user(toggles=Toggles(
            eating_window=ToggleState(status="active"),
        ))
        hooks = get_hooks_to_schedule(user)
        ew_hooks = [h for h in hooks if h["toggle_name"] == "eating_window"]
        assert len(ew_hooks) == 0

    def test_active_weekly_summary_gets_weekly_hook(self):
        user = _make_user(toggles=Toggles())  # weekly_summary is active by default
        hooks = get_hooks_to_schedule(user)
        ws_hooks = [h for h in hooks if h["toggle_name"] == "weekly_summary"]
        assert len(ws_hooks) == 1
        assert ws_hooks[0]["anchor_day"] == WEEKLY_SUMMARY_ANCHOR_DAY

    def test_dormant_toggle_not_scheduled(self):
        user = _make_user()  # all opt-in toggles dormant
        hooks = get_hooks_to_schedule(user)
        toggle_names = {h["toggle_name"] for h in hooks}
        assert "sleep" not in toggle_names
        assert "workouts" not in toggle_names
        assert "self_care" not in toggle_names
        assert "eating_window" not in toggle_names

    def test_cancelled_toggle_not_scheduled(self):
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="cancelled"),
        ))
        hooks = get_hooks_to_schedule(user)
        sleep_hooks = [h for h in hooks if h["toggle_name"] == "sleep"]
        assert len(sleep_hooks) == 0

    def test_multiple_active_toggles(self):
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active"),
            workouts=ToggleState(status="active"),
            self_care=ToggleState(status="active"),
            eating_window=ToggleState(status="active"),
        ))
        hooks = get_hooks_to_schedule(user)
        # sleep + workouts + self_care + weekly_summary (default active)
        # eating_window is auto-computed, not a proactive hook
        assert len(hooks) == 4
