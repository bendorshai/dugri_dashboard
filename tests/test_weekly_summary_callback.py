"""
test_weekly_summary_callback - TDD tests for the enhanced weekly summary callback.

# ============================================================================
# WEEKLY SUMMARY CALLBACK SPECIFICATION (Single Source of Truth)
#
# The weekly summary shows per-day data for the last 7 days:
#
# PER-DAY SECTIONS:
# - Calories vs target with percentage (existing)
# - Protein vs target with percentage (existing)
# - Eating window compliance - ONLY when eating_window toggle is active
# - Workout indicator - shown when workout logged for that day
#   Include workout note if available
# - Sleep time - shown when sleep logged for that day
#   If sleep goal exists: emoji reflects compliance
#     Within 30 min of target: checkmark
#     Outside 30 min: warning
#   If no sleep goal: show time without emoji
#
# GRACEFUL DEGRADATION:
# - If sleep_repo is None, skip sleep data entirely
# - If workout_repo is None, skip workout data entirely
# - Days with no data show "אין נתונים" (unchanged)
#
# ============================================================================
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Stub heavy imports
for mod in [
    "telegram", "telegram.ext", "telegram.ext._application",
    "pymongo", "openai",
]:
    sys.modules.setdefault(mod, MagicMock())

mock_telegram = sys.modules["telegram"]
if isinstance(mock_telegram, MagicMock):
    mock_telegram.Update = MagicMock
    mock_telegram.InlineKeyboardButton = MagicMock
    mock_telegram.InlineKeyboardMarkup = MagicMock

mock_ext = sys.modules["telegram.ext"]
if isinstance(mock_ext, MagicMock):
    mock_ext.ContextTypes = MagicMock()
    mock_ext.ContextTypes.DEFAULT_TYPE = MagicMock

from models.profile import UserProfile, EatingWindow, Targets, ToggleState, Toggles
from models.food import FoodEntry
from models.sleep import SleepLog
from models.workout import WorkoutLog


def _make_profile(**kwargs):
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "eating_window": EatingWindow(start="08:00", end="20:00"),
        "targets": Targets(calories=2000, protein=150),
        "timezone": "Asia/Jerusalem",
    }
    defaults.update(kwargs)
    return UserProfile(**defaults)


def _make_handler():
    from handlers.base import HealthHandlers
    h = HealthHandlers.__new__(HealthHandlers)
    h._debug_mode = False
    h.user_repo = MagicMock()
    h.food_repo = MagicMock()
    h.feedback_repo = MagicMock()
    h.eating_day_svc = MagicMock()
    h.analyzer = MagicMock()
    h.sleep_repo = None
    h.workout_repo = None
    h.landing_page_url = ""
    return h


def _make_update_context():
    query = AsyncMock()
    query.data = "weekly_summary"
    update = MagicMock()
    update.callback_query = query
    update.effective_user.id = 123
    context = MagicMock()
    return update, context, query


class TestWeeklyCallbackWithWorkouts:
    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_shows_workout_for_day(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        workout_repo = MagicMock()
        workout_repo.get_recent.return_value = [
            WorkoutLog(telegram_user_id=123, date="15/06/2026", note="ריצה"),
        ]
        h.workout_repo = workout_repo

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        assert "אימון" in call_text
        assert "ריצה" in call_text

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_workout_without_note(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        workout_repo = MagicMock()
        workout_repo.get_recent.return_value = [
            WorkoutLog(telegram_user_id=123, date="15/06/2026"),
        ]
        h.workout_repo = workout_repo

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        assert "אימון" in call_text


class TestWeeklyCallbackWithSleep:
    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_shows_sleep_time(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        sleep_repo = MagicMock()
        sleep_repo.get_recent.return_value = [
            SleepLog(telegram_user_id=123, date="15/06/2026", sleep_time="23:00"),
        ]
        h.sleep_repo = sleep_repo

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        assert "שינה" in call_text
        assert "23:00" in call_text

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_sleep_within_goal_shows_checkmark(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        profile = _make_profile(targets=Targets(calories=2000, protein=150, sleep_time="23:00"))
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        sleep_repo = MagicMock()
        sleep_repo.get_recent.return_value = [
            SleepLog(telegram_user_id=123, date="15/06/2026", sleep_time="23:15"),
        ]
        h.sleep_repo = sleep_repo

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        # Within 30 min of target -> checkmark
        sleep_line = [l for l in call_text.split("\n") if "שינה" in l][0]
        assert "✅" in sleep_line

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_sleep_outside_goal_shows_warning(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        profile = _make_profile(targets=Targets(calories=2000, protein=150, sleep_time="23:00"))
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        sleep_repo = MagicMock()
        sleep_repo.get_recent.return_value = [
            SleepLog(telegram_user_id=123, date="15/06/2026", sleep_time="01:30"),
        ]
        h.sleep_repo = sleep_repo

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        sleep_line = [l for l in call_text.split("\n") if "שינה" in l][0]
        assert "⚠️" in sleep_line

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_sleep_no_goal_no_emoji(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        profile = _make_profile(targets=Targets(calories=2000, protein=150))
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        sleep_repo = MagicMock()
        sleep_repo.get_recent.return_value = [
            SleepLog(telegram_user_id=123, date="15/06/2026", sleep_time="23:00"),
        ]
        h.sleep_repo = sleep_repo

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        sleep_line = [l for l in call_text.split("\n") if "שינה" in l][0]
        # No goal -> just show time, no compliance emoji on the sleep line
        assert "23:00" in sleep_line
        assert "✅" not in sleep_line
        assert "⚠️" not in sleep_line


class TestWeeklyCallbackEatingWindow:
    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_eating_window_shown_when_toggle_active(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        toggles = Toggles(eating_window=ToggleState(status="active"))
        profile = _make_profile(toggles=toggles)
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        assert "חלון אכילה" in call_text

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_eating_window_hidden_when_toggle_not_active(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        # Default toggles - eating_window is dormant
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        assert "חלון אכילה" not in call_text


class TestWeeklyCallbackGracefulDegradation:
    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_no_sleep_repo_skips_sleep(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        h.sleep_repo = None
        h.workout_repo = MagicMock()
        h.workout_repo.get_recent.return_value = []
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        assert "שינה" not in call_text

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_no_workout_repo_skips_workouts(self, mock_answer, mock_now):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 14, 0, tzinfo=tz)

        h = _make_handler()
        h.workout_repo = None
        h.sleep_repo = MagicMock()
        h.sleep_repo.get_recent.return_value = []
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="15/06/2026", time="12:00",
                      description="ארוחה", calories=500, protein=30, within_window=True),
        ]

        update, context, query = _make_update_context()
        await h.handle_weekly_callback(update, context)

        call_text = query.edit_message_text.call_args[0][0]
        assert "אימון" not in call_text
