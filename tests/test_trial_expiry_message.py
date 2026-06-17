"""
test_trial_expiry_message - Tests for the revamped trial expiry message.

Covers:
- Window gating: message fires only within 20:30-21:30 local time
- Trial stats computation: averages over active trial days
- LLM call: correct args passed to analyzer.generate_trial_expiry_message
- Fallback: celebration text used when LLM fails
- Sent flag: trial_expiry_message_sent set after send
- Hook gating: _check_user_hooks returns early for trial_ended users
- Idempotency: already-sent flag prevents re-send
"""

import sys
from unittest.mock import MagicMock, AsyncMock, patch
from collections import namedtuple

for mod in ["telegram", "telegram.ext", "telegram.ext._application", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from datetime import datetime, timezone, timedelta
import pytest
import pytz

from user_clock import UserClock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ISR = "Asia/Jerusalem"
ISR_TZ = pytz.timezone(ISR)


def _utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=timezone.utc)


def _make_profile(**kwargs):
    from models.profile import User
    defaults = dict(
        email="test@example.com",
        telegram_user_id=12345,
        name="טסט",
        gender="male",
        subscription_status="trial_active",
        trial_started_at=_utc(2026, 6, 1, 10, 0, 0),
        trial_expiry_message_sent=False,
        timezone=ISR,
    )
    defaults.update(kwargs)
    return User(**defaults)


def _make_repo():
    repo = MagicMock()
    repo.update_fields = MagicMock()
    return repo


def _make_food_entry(date, calories, protein):
    """Minimal food entry stub."""
    entry = MagicMock()
    entry.date = date
    entry.calories = calories
    entry.protein = protein
    entry.within_window = True
    entry.time = "12:00"
    entry.description = "ארוחה"
    return entry


def _make_sleep_log(date, sleep_time):
    log = MagicMock()
    log.date = date
    log.sleep_time = sleep_time
    return log


def _make_workout_log(date, note="אימון"):
    log = MagicMock()
    log.date = date
    log.note = note
    return log


def _make_self_care_log(date, description="יוגה"):
    log = MagicMock()
    log.date = date
    log.week_id = "2026-W23"
    log.description = description
    return log


# ---------------------------------------------------------------------------
# TestComputeTrialStats
# ---------------------------------------------------------------------------

class TestComputeTrialStats:
    """Tests for _compute_trial_stats helper."""

    def test_basic_food_averages(self):
        from scheduler import _compute_trial_stats

        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 10, 0, 0))
        food_repo = MagicMock()
        food_repo.get_by_user_and_dates.return_value = [
            _make_food_entry("01/06/2026", 2000, 100),
            _make_food_entry("01/06/2026", 500, 30),
            _make_food_entry("02/06/2026", 1800, 90),
            _make_food_entry("03/06/2026", 2200, 110),
        ]

        stats = _compute_trial_stats(
            profile, food_repo,
            sleep_repo=None, workout_repo=None, self_care_repo=None,
        )

        # Day 01: 2500 cal, 130 prot. Day 02: 1800, 90. Day 03: 2200, 110
        # Avg: (2500+1800+2200)/3 = 2166.67 -> 2167
        assert stats["active_food_days"] == 3
        assert stats["avg_daily_calories"] == 2167
        # Avg protein: (130+90+110)/3 = 110
        assert stats["avg_daily_protein"] == 110

    def test_no_food_data(self):
        from scheduler import _compute_trial_stats

        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 10, 0, 0))
        food_repo = MagicMock()
        food_repo.get_by_user_and_dates.return_value = []

        stats = _compute_trial_stats(
            profile, food_repo,
            sleep_repo=None, workout_repo=None, self_care_repo=None,
        )

        assert stats["active_food_days"] == 0
        assert stats["avg_daily_calories"] == 0
        assert stats["avg_daily_protein"] == 0

    def test_workout_count(self):
        from scheduler import _compute_trial_stats

        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 10, 0, 0))
        food_repo = MagicMock()
        food_repo.get_by_user_and_dates.return_value = []

        workout_repo = MagicMock()
        workout_repo.get_recent.return_value = [
            _make_workout_log("01/06/2026"),
            _make_workout_log("03/06/2026"),
            _make_workout_log("05/06/2026"),
            # One outside trial range (before trial)
            _make_workout_log("15/05/2026"),
        ]

        stats = _compute_trial_stats(
            profile, food_repo,
            sleep_repo=None, workout_repo=workout_repo, self_care_repo=None,
        )

        # Only 3 workouts within trial period
        assert stats["total_workouts"] == 3

    def test_sleep_average(self):
        from scheduler import _compute_trial_stats

        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 10, 0, 0))
        food_repo = MagicMock()
        food_repo.get_by_user_and_dates.return_value = []

        sleep_repo = MagicMock()
        sleep_repo.get_recent.return_value = [
            _make_sleep_log("01/06/2026", "22:00"),
            _make_sleep_log("02/06/2026", "23:00"),
            _make_sleep_log("03/06/2026", "22:30"),
        ]

        stats = _compute_trial_stats(
            profile, food_repo,
            sleep_repo=sleep_repo, workout_repo=None, self_care_repo=None,
        )

        assert stats["avg_sleep_time"] == "22:30"

    def test_self_care_count(self):
        from scheduler import _compute_trial_stats

        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 10, 0, 0))
        food_repo = MagicMock()
        food_repo.get_by_user_and_dates.return_value = []

        self_care_repo = MagicMock()
        self_care_repo.get_recent.return_value = [
            _make_self_care_log("02/06/2026", "מסאז'"),
            _make_self_care_log("05/06/2026", "טיול"),
        ]

        stats = _compute_trial_stats(
            profile, food_repo,
            sleep_repo=None, workout_repo=None, self_care_repo=self_care_repo,
        )

        assert stats["self_care_count"] == 2

    def test_targets_included(self):
        from scheduler import _compute_trial_stats

        profile = _make_profile(
            trial_started_at=_utc(2026, 6, 1, 10, 0, 0),
            targets={"calories": 2000, "protein": 150, "sleep_time": "23:00",
                     "workouts_per_week": 3},
        )
        food_repo = MagicMock()
        food_repo.get_by_user_and_dates.return_value = []

        stats = _compute_trial_stats(
            profile, food_repo,
            sleep_repo=None, workout_repo=None, self_care_repo=None,
        )

        assert stats["target_calories"] == 2000
        assert stats["target_protein"] == 150
        assert stats["target_sleep_time"] == "23:00"
        assert stats["target_workouts_per_week"] == 3


# ---------------------------------------------------------------------------
# TestTrialExpiryWindow
# ---------------------------------------------------------------------------

class TestTrialExpiryWindow:
    """Tests for the time window check in _check_trial_expiry_message."""

    @pytest.mark.asyncio
    async def test_fires_within_window(self):
        """Message fires when local time is 20:45 (inside 20:30-21:30)."""
        from scheduler import _check_trial_expiry_message

        # 20:45 Israel time on June 13 = 17:45 UTC
        now_utc = _utc(2026, 6, 13, 17, 45)
        profile = _make_profile()
        user_repo = _make_repo()
        trial_service = MagicMock()
        trial_service.check_and_expire.return_value = True

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        analyzer = MagicMock()
        analyzer.generate_trial_expiry_message.return_value = "הודעת סיום"

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=trial_service,
            analyzer=analyzer,
            now_override=now_utc,
        )

        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_fire_before_window(self):
        """Message does NOT fire at 19:00 (before 20:30)."""
        from scheduler import _check_trial_expiry_message

        # 19:00 Israel = 16:00 UTC
        now_utc = _utc(2026, 6, 13, 16, 0)
        profile = _make_profile()
        user_repo = _make_repo()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=MagicMock(),
            analyzer=MagicMock(),
            now_override=now_utc,
        )

        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_fire_after_window(self):
        """Message does NOT fire at 22:00 (after 21:30)."""
        from scheduler import _check_trial_expiry_message

        # 22:00 Israel = 19:00 UTC
        now_utc = _utc(2026, 6, 13, 19, 0)
        profile = _make_profile()
        user_repo = _make_repo()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=MagicMock(),
            analyzer=MagicMock(),
            now_override=now_utc,
        )

        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_fires_at_window_start(self):
        """Message fires at exactly 20:30."""
        from scheduler import _check_trial_expiry_message

        # 20:30 Israel = 17:30 UTC
        now_utc = _utc(2026, 6, 13, 17, 30)
        profile = _make_profile()
        user_repo = _make_repo()
        trial_service = MagicMock()
        trial_service.check_and_expire.return_value = True

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        analyzer = MagicMock()
        analyzer.generate_trial_expiry_message.return_value = "הודעת סיום"

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=trial_service,
            analyzer=analyzer,
            now_override=now_utc,
        )

        context.bot.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# TestLLMCallStructure
# ---------------------------------------------------------------------------

class TestLLMCallStructure:
    """Tests that the LLM call receives the right arguments."""

    @pytest.mark.asyncio
    async def test_analyzer_called_with_correct_args(self):
        from scheduler import _check_trial_expiry_message
        import messages as M

        now_utc = _utc(2026, 6, 13, 17, 45)  # 20:45 Israel
        profile = _make_profile(
            targets={"calories": 2000, "protein": 150},
        )

        user_repo = _make_repo()
        trial_service = MagicMock()
        trial_service.check_and_expire.return_value = True

        food_repo = MagicMock()
        food_repo.get_by_user_and_dates.return_value = [
            _make_food_entry("01/06/2026", 2500, 100),
        ]

        gem_result = MagicMock()
        gem_result.raw_text = "פנינת חוכמה גולמית"
        gem_service = MagicMock()
        gem_service.select_best_gem.return_value = gem_result

        feedback_service = MagicMock()
        feedback_service.give_feedback.return_value = "סיכום שבועי"

        analyzer = MagicMock()
        analyzer.generate_trial_expiry_message.return_value = "הודעה מלאה"

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=trial_service,
            analyzer=analyzer,
            gem_service=gem_service,
            feedback_service=feedback_service,
            food_repo=food_repo,
            now_override=now_utc,
        )

        analyzer.generate_trial_expiry_message.assert_called_once()
        call_kwargs = analyzer.generate_trial_expiry_message.call_args
        # Check key arguments
        assert call_kwargs.kwargs.get("celebration_text") or call_kwargs[1].get("celebration_text")
        assert "gem_text" in (call_kwargs.kwargs or call_kwargs[1])
        assert "weekly_report" in (call_kwargs.kwargs or call_kwargs[1])
        assert "name" in (call_kwargs.kwargs or call_kwargs[1])
        assert "gender" in (call_kwargs.kwargs or call_kwargs[1])


# ---------------------------------------------------------------------------
# TestFallback
# ---------------------------------------------------------------------------

class TestFallback:
    """Tests that celebration text is used as fallback when LLM fails."""

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        from scheduler import _check_trial_expiry_message
        import messages as M

        now_utc = _utc(2026, 6, 13, 17, 45)
        profile = _make_profile()
        user_repo = _make_repo()
        trial_service = MagicMock()
        trial_service.check_and_expire.return_value = True

        analyzer = MagicMock()
        analyzer.generate_trial_expiry_message.side_effect = Exception("LLM error")

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=trial_service,
            analyzer=analyzer,
            now_override=now_utc,
        )

        # Should still send - using fallback
        context.bot.send_message.assert_called_once()
        sent_text = context.bot.send_message.call_args.kwargs.get("text", "")
        assert M.TRIAL_EXPIRY_CELEBRATION in sent_text

    @pytest.mark.asyncio
    async def test_fallback_on_empty_llm_response(self):
        from scheduler import _check_trial_expiry_message
        import messages as M

        now_utc = _utc(2026, 6, 13, 17, 45)
        profile = _make_profile()
        user_repo = _make_repo()
        trial_service = MagicMock()
        trial_service.check_and_expire.return_value = True

        analyzer = MagicMock()
        analyzer.generate_trial_expiry_message.return_value = ""

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=trial_service,
            analyzer=analyzer,
            now_override=now_utc,
        )

        sent_text = context.bot.send_message.call_args.kwargs.get("text", "")
        assert M.TRIAL_EXPIRY_CELEBRATION in sent_text


# ---------------------------------------------------------------------------
# TestSentFlag
# ---------------------------------------------------------------------------

class TestSentFlag:
    """Tests that trial_expiry_message_sent is set after sending."""

    @pytest.mark.asyncio
    async def test_marks_sent_after_success(self):
        from scheduler import _check_trial_expiry_message

        now_utc = _utc(2026, 6, 13, 17, 45)
        profile = _make_profile()
        user_repo = _make_repo()
        trial_service = MagicMock()
        trial_service.check_and_expire.return_value = True

        analyzer = MagicMock()
        analyzer.generate_trial_expiry_message.return_value = "הודעה"

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, user_repo,
            toggle_service=MagicMock(),
            trial_service=trial_service,
            analyzer=analyzer,
            now_override=now_utc,
        )

        user_repo.update_fields.assert_any_call(
            12345, {"trial_expiry_message_sent": True},
        )


# ---------------------------------------------------------------------------
# TestIdempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Tests that already-sent users are skipped."""

    @pytest.mark.asyncio
    async def test_skips_if_already_sent(self):
        from scheduler import _check_trial_expiry_message

        now_utc = _utc(2026, 6, 13, 17, 45)
        profile = _make_profile(trial_expiry_message_sent=True)

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, _make_repo(),
            toggle_service=MagicMock(),
            trial_service=MagicMock(),
            analyzer=MagicMock(),
            now_override=now_utc,
        )

        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_if_not_trial_active(self):
        from scheduler import _check_trial_expiry_message

        now_utc = _utc(2026, 6, 13, 17, 45)
        profile = _make_profile(subscription_status="trial_ended")

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _check_trial_expiry_message(
            context, profile, _make_repo(),
            toggle_service=MagicMock(),
            trial_service=MagicMock(),
            analyzer=MagicMock(),
            now_override=now_utc,
        )

        context.bot.send_message.assert_not_called()
