"""
test_hook_scheduler - TDD tests for the hook scheduling system.

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


class TestInlineHookWindowGuard:
    """Inline hooks must respect time windows.

    Bug: inline path in _check_inline_hooks had no window guard, so logging
    food at 00:30 on Sunday triggered a weekly summary offer. The poller's
    randomized timing never got a chance because inline 'stole' the slot.
    """

    def test_weekly_summary_blocked_outside_window(self):
        """Weekly summary should NOT fire at 00:30 on Sunday."""
        # 00:30 Israel Sunday = 21:30 UTC Saturday
        clock = _clock(datetime(2026, 6, 6, 21, 30))
        assert clock.weekday() == 6  # Sunday in Israel
        start, end = WEEKLY_SUMMARY_HOOK_WINDOW
        assert not (start <= clock.now().hour < end)

    def test_weekly_summary_allowed_inside_window(self):
        """Weekly summary should fire at 09:30 on Sunday."""
        # 09:30 Israel Sunday = 06:30 UTC Sunday
        clock = _clock(datetime(2026, 6, 7, 6, 30))
        assert clock.weekday() == 6  # Sunday in Israel
        start, end = WEEKLY_SUMMARY_HOOK_WINDOW
        assert start <= clock.now().hour < end

    def test_sleep_blocked_outside_window(self):
        """Sleep hook should NOT fire at 23:00."""
        # 23:00 Israel = 20:00 UTC
        clock = _clock(datetime(2026, 6, 7, 20, 0))
        start, end = SLEEP_HOOK_WINDOW
        assert not (start <= clock.now().hour < end)

    def test_sleep_allowed_inside_window(self):
        """Sleep hook should fire at 09:00."""
        # 09:00 Israel = 06:00 UTC
        clock = _clock(datetime(2026, 6, 7, 6, 0))
        start, end = SLEEP_HOOK_WINDOW
        assert start <= clock.now().hour < end

    def test_workouts_blocked_outside_window(self):
        """Workouts hook should NOT fire at 08:00."""
        # 08:00 Israel = 05:00 UTC
        clock = _clock(datetime(2026, 6, 4, 5, 0))  # Thursday
        assert clock.weekday() == WORKOUTS_ANCHOR_DAY
        start, end = WORKOUTS_HOOK_WINDOW
        assert not (start <= clock.now().hour < end)

    def test_workouts_allowed_inside_window(self):
        """Workouts hook should fire at 17:00 on Thursday."""
        # 17:00 Israel Thursday = 14:00 UTC
        clock = _clock(datetime(2026, 6, 4, 14, 0))
        assert clock.weekday() == WORKOUTS_ANCHOR_DAY
        start, end = WORKOUTS_HOOK_WINDOW
        assert start <= clock.now().hour < end

    def test_self_care_blocked_outside_window(self):
        """Self-care hook should NOT fire at 08:00."""
        # 08:00 Israel Friday = 05:00 UTC
        clock = _clock(datetime(2026, 6, 5, 5, 0))  # Friday
        assert clock.weekday() == SELF_CARE_ANCHOR_DAY
        start, end = SELF_CARE_HOOK_WINDOW
        assert not (start <= clock.now().hour < end)

    def test_self_care_allowed_inside_window(self):
        """Self-care hook should fire at 11:00 on Friday."""
        # 11:00 Israel Friday = 08:00 UTC
        clock = _clock(datetime(2026, 6, 5, 8, 0))
        assert clock.weekday() == SELF_CARE_ANCHOR_DAY
        start, end = SELF_CARE_HOOK_WINDOW
        assert start <= clock.now().hour < end


class TestProactiveReveals:
    """Proactive reveals via the 28-min poller.

    The poller is a fallback for users who haven't logged food. But:
    - Nutrition is STRICTLY inline-only (after first food entry). The poller
      must never reveal nutrition.
    - Eating window requires at least 1 food entry in history, even via poller.
    """

    @pytest.fixture
    def context(self):
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()
        return ctx

    @pytest.fixture
    def toggle_service(self):
        svc = MagicMock()
        svc.reveal_toggle = MagicMock()
        return svc

    @pytest.fixture
    def user_repo(self):
        return MagicMock()

    @pytest.fixture
    def food_repo(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_poller_does_not_reveal_nutrition(
        self, context, toggle_service, user_repo, food_repo,
    ):
        """Nutrition reveal is strictly inline. Poller must never offer it."""
        from scheduler import _check_proactive_reveals

        user = _make_user(
            toggles=Toggles(nutrition=ToggleState(status="dormant")),
        )
        user.onboarding = MagicMock(name_collected=True)

        toggle_service.should_reveal_nutrition.return_value = True
        toggle_service.should_reveal_sleep.return_value = False
        toggle_service.should_reveal_eating_window.return_value = False
        toggle_service.should_reveal_workouts.return_value = False
        toggle_service.should_reveal_self_care.return_value = False

        now = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
        await _check_proactive_reveals(
            context, user, user_repo, toggle_service, now, 4,
            food_repo=food_repo,
        )

        toggle_service.reveal_toggle.assert_not_called()
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_poller_does_not_reveal_eating_window_without_food(
        self, context, toggle_service, user_repo, food_repo,
    ):
        """Eating window should not be offered if user has zero food entries."""
        from scheduler import _check_proactive_reveals

        user = _make_user(
            toggles=Toggles(eating_window=ToggleState(status="dormant")),
        )

        toggle_service.should_reveal_sleep.return_value = False
        toggle_service.should_reveal_eating_window.return_value = True
        toggle_service.should_reveal_workouts.return_value = False
        toggle_service.should_reveal_self_care.return_value = False

        food_repo.get_all_for_user.return_value = []

        now = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
        await _check_proactive_reveals(
            context, user, user_repo, toggle_service, now, 4,
            food_repo=food_repo,
        )

        toggle_service.reveal_toggle.assert_not_called()

    @pytest.mark.asyncio
    async def test_poller_reveals_eating_window_with_food(
        self, context, toggle_service, user_repo, food_repo,
    ):
        """Eating window should be offered when user has food history."""
        from scheduler import _check_proactive_reveals

        user = _make_user(
            toggles=Toggles(eating_window=ToggleState(status="dormant")),
        )

        toggle_service.should_reveal_sleep.return_value = False
        toggle_service.should_reveal_eating_window.return_value = True
        toggle_service.should_reveal_workouts.return_value = False
        toggle_service.should_reveal_self_care.return_value = False

        food_repo.get_all_for_user.return_value = [{"entry": "fake"}]

        now = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
        await _check_proactive_reveals(
            context, user, user_repo, toggle_service, now, 4,
            food_repo=food_repo,
        )

        toggle_service.reveal_toggle.assert_called_once_with(user.telegram_user_id, "eating_window")
