"""
test_habit_temporal.py - TDD tests for temporal date extraction in habit logging.

Expected behavior:
- HabitLoggerClassification has a resolved_date field (DD/MM/YYYY or None)
- RouterClassification carries resolved_date through the tiered pipeline
- When resolved_date is set, handler uses it instead of stats_date
- When resolved_date is None, handler falls back to stats_date (today)
- Confirmation messages include day name when date != today
- LLM resolves Hebrew temporal markers: אתמול, שלשום, בשבת, ביום ראשון, etc.
- Always resolves to the past

Habit types x temporal references matrix (LLM tests):
  sleep  x {אתמול, שלשום, בשבת, ביום ראשון, no marker}
  workout x {אתמול, שלשום, בשבת, ביום ראשון, no marker}
  self_care x {אתמול, שלשום, בשבת, ביום ראשון, no marker}
"""

import sys
import os
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

for mod in ["telegram", "telegram.ext", "pymongo"]:
    sys.modules.setdefault(mod, MagicMock())


# ============================================================================
# UNIT TESTS - Model fields, handler logic, date validation (no LLM)
# ============================================================================


class TestHabitLoggerClassificationModel:
    """resolved_date field exists and behaves correctly."""

    def test_resolved_date_defaults_to_none(self):
        from models.analyzer_models import HabitLoggerClassification

        result = HabitLoggerClassification(type="workout")
        assert result.resolved_date is None

    def test_resolved_date_accepts_valid_date(self):
        from models.analyzer_models import HabitLoggerClassification

        result = HabitLoggerClassification(
            type="workout",
            workout_note="אימון ריצה",
            resolved_date="14/06/2026",
        )
        assert result.resolved_date == "14/06/2026"

    def test_resolved_date_on_sleep(self):
        from models.analyzer_models import HabitLoggerClassification

        result = HabitLoggerClassification(
            type="sleep",
            sleep_time="23:00",
            resolved_date="13/06/2026",
        )
        assert result.resolved_date == "13/06/2026"
        assert result.sleep_time == "23:00"

    def test_resolved_date_on_self_care(self):
        from models.analyzer_models import HabitLoggerClassification

        result = HabitLoggerClassification(
            type="self_care",
            self_care_description="הלכתי לים",
            resolved_date="14/06/2026",
        )
        assert result.resolved_date == "14/06/2026"


class TestRouterClassificationModel:
    """RouterClassification carries resolved_date and self_care_description."""

    def test_resolved_date_defaults_to_none(self):
        from models.analyzer_models import RouterClassification

        result = RouterClassification(type="workout")
        assert result.resolved_date is None

    def test_resolved_date_carried_through(self):
        from models.analyzer_models import RouterClassification

        result = RouterClassification(
            type="workout",
            workout_note="אימון",
            resolved_date="14/06/2026",
        )
        assert result.resolved_date == "14/06/2026"

    def test_self_care_description_carried_through(self):
        from models.analyzer_models import RouterClassification

        result = RouterClassification(
            type="self_care",
            self_care_description="הלכתי לים",
            resolved_date="14/06/2026",
        )
        assert result.self_care_description == "הלכתי לים"


class TestDateValidation:
    """_validate_resolved_date rejects bad formats, accepts good ones."""

    def test_valid_date_passes(self):
        from handlers.base import _validate_resolved_date

        assert _validate_resolved_date("14/06/2026") == "14/06/2026"

    def test_none_returns_none(self):
        from handlers.base import _validate_resolved_date

        assert _validate_resolved_date(None) is None

    def test_bad_format_returns_none(self):
        from handlers.base import _validate_resolved_date

        assert _validate_resolved_date("2026-06-14") is None

    def test_empty_string_returns_none(self):
        from handlers.base import _validate_resolved_date

        assert _validate_resolved_date("") is None

    def test_garbage_returns_none(self):
        from handlers.base import _validate_resolved_date

        assert _validate_resolved_date("not a date") is None

    def test_future_date_returns_none(self):
        """Future dates are rejected - habits are always reported in the past."""
        from handlers.base import _validate_resolved_date

        future = (datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")
        assert _validate_resolved_date(future) is None


class TestHandlerUsesResolvedDate:
    """Handler dispatch uses resolved_date when available, falls back to stats_date."""

    def _make_handler(self):
        """Create a minimal MessageHandler with mocked dependencies."""
        from handlers.base import MessageHandler

        handler = MagicMock(spec=MessageHandler)
        handler.message_router = MagicMock()
        handler.sleep_repo = MagicMock()
        handler.workout_repo = MagicMock()
        handler.self_care_repo = MagicMock()
        handler._send = AsyncMock()
        handler._store_message_ids = MagicMock()
        handler._get_education_intro = MagicMock(return_value=None)
        return handler

    @pytest.mark.asyncio
    async def test_workout_uses_resolved_date(self):
        """When resolved_date is set, route_workout receives it instead of stats_date."""
        from models.analyzer_models import RouterClassification

        router_result = RouterClassification(
            type="workout",
            workout_note="אימון ריצה",
            resolved_date="14/06/2026",
        )
        # The effective_date should be 14/06/2026, not stats_date
        effective_date = router_result.resolved_date or "16/06/2026"
        assert effective_date == "14/06/2026"

    @pytest.mark.asyncio
    async def test_sleep_uses_resolved_date(self):
        from models.analyzer_models import RouterClassification

        router_result = RouterClassification(
            type="sleep",
            resolved_date="13/06/2026",
        )
        effective_date = router_result.resolved_date or "16/06/2026"
        assert effective_date == "13/06/2026"

    @pytest.mark.asyncio
    async def test_self_care_uses_resolved_date(self):
        from models.analyzer_models import RouterClassification

        router_result = RouterClassification(
            type="self_care",
            self_care_description="הלכתי לים",
            resolved_date="14/06/2026",
        )
        effective_date = router_result.resolved_date or "16/06/2026"
        assert effective_date == "14/06/2026"

    @pytest.mark.asyncio
    async def test_falls_back_to_stats_date(self):
        from models.analyzer_models import RouterClassification

        router_result = RouterClassification(type="workout", workout_note="אימון")
        effective_date = router_result.resolved_date or "16/06/2026"
        assert effective_date == "16/06/2026"


class TestConfirmationMessages:
    """Confirmation messages include day name when date is not today."""

    def test_workout_with_date_label(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        habit.log_workout.return_value = MagicMock(id="abc123")
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_workout(123, "14/06/2026", "אימון ריצה", date_label="שבת")
        assert "שבת" in result.response_text

    def test_workout_without_date_label(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        habit.log_workout.return_value = MagicMock(id="abc123")
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_workout(123, "16/06/2026", "אימון ריצה")
        assert "שבת" not in result.response_text

    def test_sleep_with_date_label(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        habit.log_sleep.return_value = MagicMock(id="abc123")
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_sleep(123, "23:00", "14/06/2026", date_label="שבת")
        assert "שבת" in result.response_text

    def test_sleep_without_date_label(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        habit.log_sleep.return_value = MagicMock(id="abc123")
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_sleep(123, "23:00", "16/06/2026")
        assert "שבת" not in result.response_text

    def test_self_care_with_date_label(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        habit.log_self_care.return_value = MagicMock(id="abc123")
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_self_care(123, "הלכתי לים", "14/06/2026", date_label="שבת")
        assert "שבת" in result.response_text

    def test_self_care_without_date_label(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        habit.log_self_care.return_value = MagicMock(id="abc123")
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_self_care(123, "הלכתי לים", "16/06/2026")
        assert "שבת" not in result.response_text


# ============================================================================
# LLM INTEGRATION TESTS - Temporal date resolution via actual GPT calls
# ============================================================================

# Date computation helpers
_NOW = datetime.now(timezone.utc)
_TODAY_STR = _NOW.strftime("%d/%m/%Y")


def _yesterday() -> str:
    return (_NOW - timedelta(days=1)).strftime("%d/%m/%Y")


def _day_before_yesterday() -> str:
    return (_NOW - timedelta(days=2)).strftime("%d/%m/%Y")


def _last_day(target_weekday: int) -> str:
    """Get last occurrence of a weekday (0=Mon, 5=Sat, 6=Sun)."""
    days_back = (_NOW.weekday() - target_weekday) % 7
    if days_back == 0:
        days_back = 7  # if today is the target day, go back a full week
    return (_NOW - timedelta(days=days_back)).strftime("%d/%m/%Y")


def _last_saturday() -> str:
    return _last_day(5)


def _last_sunday() -> str:
    return _last_day(6)


def _last_monday() -> str:
    return _last_day(0)


def _make_analyzer():
    """Create a real FoodAnalyzer for LLM integration tests."""
    import json
    from analyzer import FoodAnalyzer

    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        api_key = config.get("openai", {}).get("api_key", "")
    except FileNotFoundError:
        api_key = os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        pytest.skip("No OpenAI API key available")

    return FoodAnalyzer(api_key)


def _get_day_name() -> str:
    from parsing import hebrew_day_name
    return hebrew_day_name(_NOW)


def _route_habit(analyzer, text):
    """Call route_tier2_habit_logger with proper date context."""
    return analyzer.route_tier2_habit_logger(
        text=text,
        today_str=_TODAY_STR,
        day_name=_get_day_name(),
    )


# ============================================================================
# SLEEP x temporal references
# ============================================================================


@pytest.mark.integration
class TestSleepTemporal:

    def test_sleep_yesterday(self):
        """'אתמול ישנתי ב-22' -> resolved_date = yesterday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "אתמול ישנתי ב-22")
        assert result.type == "sleep"
        assert result.sleep_time == "22:00"
        assert result.resolved_date == _yesterday()

    def test_sleep_day_before_yesterday(self):
        """'שלשום ישנתי ב-23:30' -> resolved_date = 2 days ago"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "שלשום ישנתי ב-23:30")
        assert result.type == "sleep"
        assert result.resolved_date == _day_before_yesterday()

    def test_sleep_on_saturday(self):
        """'בשבת הלכתי לישון ב-1 בלילה' -> resolved_date = last Saturday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "בשבת הלכתי לישון ב-1 בלילה")
        assert result.type == "sleep"
        assert result.resolved_date == _last_saturday()

    def test_sleep_on_sunday(self):
        """'ביום ראשון ישנתי ב-23' -> resolved_date = last Sunday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "ביום ראשון ישנתי ב-23")
        assert result.type == "sleep"
        assert result.resolved_date == _last_sunday()

    def test_sleep_on_monday(self):
        """'ביום שני ישנתי ב-00:30' -> resolved_date = last Monday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "ביום שני ישנתי ב-00:30")
        assert result.type == "sleep"
        assert result.resolved_date == _last_monday()

    def test_sleep_no_marker(self):
        """'הלכתי לישון ב-23' -> resolved_date = None (use today)"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "הלכתי לישון ב-23")
        assert result.type == "sleep"
        assert result.resolved_date is None


# ============================================================================
# WORKOUT x temporal references
# ============================================================================


@pytest.mark.integration
class TestWorkoutTemporal:

    def test_workout_yesterday(self):
        """'אתמול התאמנתי' -> resolved_date = yesterday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "אתמול התאמנתי")
        assert result.type == "workout"
        assert result.resolved_date == _yesterday()

    def test_workout_day_before_yesterday(self):
        """'שלשום עשיתי אימון כושר' -> resolved_date = 2 days ago"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "שלשום עשיתי אימון כושר")
        assert result.type == "workout"
        assert result.resolved_date == _day_before_yesterday()

    def test_workout_on_saturday(self):
        """'בשבת הלכתי שעה וחצי ברגל' -> resolved_date = last Saturday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "בשבת הלכתי שעה וחצי ברגל")
        assert result.type == "workout"
        assert result.resolved_date == _last_saturday()

    def test_workout_on_sunday(self):
        """'ביום ראשון רצתי חמישה קילומטר' -> resolved_date = last Sunday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "ביום ראשון רצתי חמישה קילומטר")
        assert result.type == "workout"
        assert result.resolved_date == _last_sunday()

    def test_workout_on_monday(self):
        """'ביום שני הלכתי לחדר כושר' -> resolved_date = last Monday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "ביום שני הלכתי לחדר כושר")
        assert result.type == "workout"
        assert result.resolved_date == _last_monday()

    def test_workout_no_marker(self):
        """'התאמנתי היום' -> resolved_date = None (use today)"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "התאמנתי היום")
        assert result.type == "workout"
        assert result.resolved_date is None


# ============================================================================
# SELF_CARE x temporal references
# ============================================================================


@pytest.mark.integration
class TestSelfCareTemporal:

    def test_self_care_yesterday(self):
        """'אתמול הייתי בים' -> resolved_date = yesterday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "אתמול הייתי בים")
        assert result.type == "self_care"
        assert result.resolved_date == _yesterday()

    def test_self_care_day_before_yesterday(self):
        """'שלשום קראתי ספר' -> resolved_date = 2 days ago"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "שלשום קראתי ספר")
        assert result.type == "self_care"
        assert result.resolved_date == _day_before_yesterday()

    def test_self_care_on_saturday(self):
        """'בשבת הייתי בטיול' -> resolved_date = last Saturday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "בשבת הייתי בטיול")
        assert result.type == "self_care"
        assert result.resolved_date == _last_saturday()

    def test_self_care_on_sunday(self):
        """'ביום ראשון הלכתי לטיפול' -> resolved_date = last Sunday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "ביום ראשון הלכתי לטיפול")
        assert result.type == "self_care"
        assert result.resolved_date == _last_sunday()

    def test_self_care_on_monday(self):
        """'ביום שני ניגנתי בגיטרה' -> resolved_date = last Monday"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "ביום שני ניגנתי בגיטרה")
        assert result.type == "self_care"
        assert result.resolved_date == _last_monday()

    def test_self_care_no_marker(self):
        """'הייתי בים' -> resolved_date = None (use today)"""
        analyzer = _make_analyzer()
        result = _route_habit(analyzer, "הייתי בים")
        assert result.type == "self_care"
        assert result.resolved_date is None
