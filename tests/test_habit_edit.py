"""
test_habit_edit — TDD tests for edit/delete flow on sleep, workout, self_care.

Expected behavior:
- New keyboard builders create edit + delete buttons for each habit
- Edit callback sets pending_X_correction state in chat_data
- Delete callback deletes via repo
- Pending correction handler extracts correction via LoggerService
- Date change triggers repo.move(), note change triggers update_by_id()
- RouteResult includes entry_id for keyboard attachment
"""

import sys
import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from keyboards import (
    CB_SLEEP_EDIT, CB_SLEEP_DELETE,
    CB_WORKOUT_EDIT, CB_WORKOUT_DELETE,
    CB_SELFCARE_EDIT, CB_SELFCARE_DELETE,
    make_sleep_entry_keyboard, make_workout_entry_keyboard, make_self_care_entry_keyboard,
)
from models.analyzer_models import HabitCorrectionResult
from services.message_router_service import RouteResult


class TestHabitKeyboards:
    def test_sleep_keyboard_has_edit_and_delete(self):
        kb = make_sleep_entry_keyboard("abc123")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        data = [b.callback_data for b in buttons]
        assert f"{CB_SLEEP_EDIT}abc123" in data
        assert f"{CB_SLEEP_DELETE}abc123" in data

    def test_workout_keyboard_has_edit_and_delete(self):
        kb = make_workout_entry_keyboard("abc123")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        data = [b.callback_data for b in buttons]
        assert f"{CB_WORKOUT_EDIT}abc123" in data
        assert f"{CB_WORKOUT_DELETE}abc123" in data

    def test_self_care_keyboard_has_edit_and_delete(self):
        kb = make_self_care_entry_keyboard("abc123")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        data = [b.callback_data for b in buttons]
        assert f"{CB_SELFCARE_EDIT}abc123" in data
        assert f"{CB_SELFCARE_DELETE}abc123" in data


class TestHabitCorrectionResultModel:
    def test_defaults_all_none(self):
        result = HabitCorrectionResult()
        assert result.corrected_date is None
        assert result.corrected_time is None
        assert result.corrected_note is None
        assert result.delete is False

    def test_with_date_and_note(self):
        result = HabitCorrectionResult(
            corrected_date="15/06/2026",
            corrected_note="אימון ריצה",
        )
        assert result.corrected_date == "15/06/2026"
        assert result.corrected_note == "אימון ריצה"


class TestRouteResultEntryId:
    def test_route_result_has_entry_id(self):
        result = RouteResult(response_text="test", entry_id="abc123")
        assert result.entry_id == "abc123"

    def test_route_result_entry_id_default_none(self):
        result = RouteResult(response_text="test")
        assert result.entry_id is None


class TestRouteMethodsReturnEntryId:
    def test_route_sleep_returns_entry_id(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        saved_log = MagicMock()
        saved_log.id = "aabbccddee112233aabbccdd"
        habit.log_sleep.return_value = saved_log
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_sleep(123, "23:00", "16/06/2026")
        assert result.entry_id == "aabbccddee112233aabbccdd"

    def test_route_workout_returns_entry_id(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        saved_log = MagicMock()
        saved_log.id = "bbccddee11223344bbccddee"
        habit.log_workout.return_value = saved_log
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_workout(123, "16/06/2026", "אימון ריצה")
        assert result.entry_id == "bbccddee11223344bbccddee"

    def test_route_self_care_returns_entry_id(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        saved_log = MagicMock()
        saved_log.id = "ccddee112233aabbccddee11"
        habit.log_self_care.return_value = saved_log
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_self_care(123, "הלכתי לים", "16/06/2026")
        assert result.entry_id == "ccddee112233aabbccddee11"


class TestHabitEditCallbacks:
    @pytest.mark.asyncio
    async def test_sleep_edit_sets_pending(self):
        from handlers.callback_handler import CallbackHandler

        ctx = MagicMock()
        sleep_log = MagicMock()
        sleep_log.date = "16/06/2026"
        sleep_log.sleep_time = "23:00"
        sleep_log.id = "aabbccddee112233aabbccdd"
        ctx.sleep_repo.get_by_id.return_value = sleep_log

        handler = CallbackHandler(ctx)
        update = MagicMock()
        query = MagicMock()
        query.data = f"{CB_SLEEP_EDIT}aabbccddee112233aabbccdd"
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()
        update.callback_query = query
        context = MagicMock()
        context.chat_data = {}

        await handler.handle_sleep_edit_callback(update, context)

        assert "pending_habit_correction" in context.chat_data
        pending = context.chat_data["pending_habit_correction"]
        assert pending["habit_type"] == "sleep"
        assert pending["entry"]["date"] == "16/06/2026"

    @pytest.mark.asyncio
    async def test_sleep_delete_calls_repo(self):
        from handlers.callback_handler import CallbackHandler

        ctx = MagicMock()
        ctx.landing_page_url = "https://example.com"
        handler = CallbackHandler(ctx)
        update = MagicMock()
        query = MagicMock()
        query.data = f"{CB_SLEEP_DELETE}aabbccddee112233aabbccdd"
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()
        update.callback_query = query
        context = MagicMock()

        await handler.handle_sleep_delete_callback(update, context)
        ctx.sleep_repo.delete_by_id.assert_called_once()


class TestLoggerServiceHabitCorrection:
    def test_extract_habit_correction_returns_model(self):
        from services.logger_service import LoggerService

        analyzer = MagicMock()
        analyzer._parse.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(
                parsed=HabitCorrectionResult(corrected_date="15/06/2026")
            ))]
        )
        svc = LoggerService(analyzer)
        result = svc.extract_habit_correction(
            "זה היה אתמול",
            habit_type="sleep",
            original_date="16/06/2026",
            original_value="23:00",
            today_str="16/06/2026",
        )
        assert result.corrected_date == "15/06/2026"
