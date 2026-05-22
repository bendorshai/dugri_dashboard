"""
test_hook_scheduler — TDD tests for the hook scheduling system.

Tests the hook scheduling, random time generation, piggyback detection,
and hook callback behavior.
"""

import random
from datetime import datetime, time, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from models.profile import User, ToggleState, Toggles
from constants import (
    SLEEP_HOOK_WINDOW,
    EATING_WINDOW_HOOK_WINDOW,
    WORKOUTS_HOOK_WINDOW,
    SELF_CARE_HOOK_WINDOW,
    WEEKLY_SUMMARY_HOOK_WINDOW,
    WORKOUTS_ANCHOR_DAY,
    SELF_CARE_ANCHOR_DAY,
    WEEKLY_SUMMARY_ANCHOR_DAY,
)
from scheduler import (
    random_time_in_window,
    should_piggyback,
    get_hooks_to_schedule,
)


def _make_user(**kwargs):
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "trial_started_at": datetime.now(timezone.utc) - timedelta(days=10),
    }
    defaults.update(kwargs)
    return User(**defaults)


class TestRandomTimeInWindow:
    def test_returns_time_within_window(self):
        random.seed(42)
        start, end = SLEEP_HOOK_WINDOW  # 8-10
        t = random_time_in_window(start, end)
        assert isinstance(t, time)
        assert start <= t.hour < end

    def test_returns_different_times(self):
        """Multiple calls should produce variety (not always the same)."""
        times = set()
        for seed in range(20):
            random.seed(seed)
            t = random_time_in_window(8, 10)
            times.add((t.hour, t.minute))
        assert len(times) > 1

    def test_all_windows_produce_valid_times(self):
        random.seed(0)
        for window in [
            SLEEP_HOOK_WINDOW,
            EATING_WINDOW_HOOK_WINDOW,
            WORKOUTS_HOOK_WINDOW,
            SELF_CARE_HOOK_WINDOW,
            WEEKLY_SUMMARY_HOOK_WINDOW,
        ]:
            t = random_time_in_window(*window)
            assert window[0] <= t.hour < window[1]


class TestShouldPiggyback:
    def test_true_when_hook_not_fired_today(self):
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=None),
        ))
        assert should_piggyback(user, "sleep", datetime(2026, 5, 22, 9, 0)) is True

    def test_false_when_hook_already_fired_today(self):
        today_morning = datetime(2026, 5, 22, 8, 30, tzinfo=timezone.utc)
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=today_morning),
        ))
        now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
        assert should_piggyback(user, "sleep", now) is False

    def test_true_when_last_asked_was_yesterday(self):
        yesterday = datetime(2026, 5, 21, 9, 0, tzinfo=timezone.utc)
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="active", last_asked_at=yesterday),
        ))
        now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
        assert should_piggyback(user, "sleep", now) is True

    def test_false_when_toggle_dormant(self):
        user = _make_user()
        assert should_piggyback(user, "sleep", datetime(2026, 5, 22, 9, 0)) is False

    def test_false_when_toggle_cancelled(self):
        user = _make_user(toggles=Toggles(
            sleep=ToggleState(status="cancelled"),
        ))
        assert should_piggyback(user, "sleep", datetime(2026, 5, 22, 9, 0)) is False


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

    def test_active_eating_window_gets_daily_hook(self):
        user = _make_user(toggles=Toggles(
            eating_window=ToggleState(status="active"),
        ))
        hooks = get_hooks_to_schedule(user)
        ew_hooks = [h for h in hooks if h["toggle_name"] == "eating_window"]
        assert len(ew_hooks) == 1
        assert ew_hooks[0]["schedule_type"] == "daily"
        assert ew_hooks[0]["window"] == EATING_WINDOW_HOOK_WINDOW

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
        # sleep + eating_window + workouts + self_care + weekly_summary (default active)
        assert len(hooks) == 5
