"""
test_correction_date - TDD tests for date/time correction in food entries.

Expected behavior:
- CorrectionResult can include corrected_date and corrected_time (optional)
- When correction has date change, handle_correction calls food_repo.move()
- When correction has no date change, date/time are untouched
- within_window is recalculated when date changes:
  - different date from today -> within_window = True
  - same date as today -> use eating window check
- pending_correction entry dict includes date and time
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from models.analyzer_models import CorrectionResult, CorrectionFoodItem


class TestCorrectionResultDateFields:
    def test_no_date_fields_by_default(self):
        result = CorrectionResult(
            items=[],
            corrected_description="test",
            corrected_calories=100,
            corrected_protein=10,
        )
        assert result.corrected_date is None
        assert result.corrected_time is None

    def test_with_date_and_time(self):
        result = CorrectionResult(
            items=[],
            corrected_description="test",
            corrected_calories=100,
            corrected_protein=10,
            corrected_date="15/06/2026",
            corrected_time="20:00",
        )
        assert result.corrected_date == "15/06/2026"
        assert result.corrected_time == "20:00"

    def test_with_date_only(self):
        result = CorrectionResult(
            items=[],
            corrected_description="test",
            corrected_calories=100,
            corrected_protein=10,
            corrected_date="15/06/2026",
        )
        assert result.corrected_date == "15/06/2026"
        assert result.corrected_time is None


class TestHandleCorrectionWithDate:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.food_repo = MagicMock()
        ctx.eating_day_svc.get_stats_date.return_value = "16/06/2026"
        ctx.eating_day_svc.get_eating_day_totals.return_value = (500, 30)
        ctx._target_cal.return_value = 2000
        ctx._target_prot.return_value = 120
        ctx._send = AsyncMock()
        return ctx

    def _make_correction(self, date=None, time=None):
        return CorrectionResult(
            items=[CorrectionFoodItem(
                description="test", estimated_grams=100,
                calories=200, protein=20, change_type="modified",
            )],
            corrected_description="test corrected",
            corrected_calories=200,
            corrected_protein=20,
            corrected_date=date,
            corrected_time=time,
        )

    @pytest.mark.asyncio
    async def test_no_date_change_does_not_call_move(self):
        from handlers.food_handler import FoodHandler

        ctx = self._make_ctx()
        handler = FoodHandler(ctx)
        correction = self._make_correction()

        message = MagicMock()
        message.text = "תיקון"
        context = MagicMock()
        context.chat_data = {}
        last_entry = {
            "entry_id": "abc123",
            "calories": 300, "protein": 25, "description": "original",
            "date": "16/06/2026", "time": "12:00",
        }
        profile = MagicMock()
        profile.timezone = "Asia/Jerusalem"

        await handler.handle_correction(
            message, context, correction, last_entry,
            profile, "16/06/2026", 123,
        )

        ctx.food_repo.move.assert_not_called()
        ctx.food_repo.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_date_change_calls_move(self):
        from handlers.food_handler import FoodHandler

        ctx = self._make_ctx()
        handler = FoodHandler(ctx)
        correction = self._make_correction(date="15/06/2026", time="20:00")

        message = MagicMock()
        message.text = "זה היה אתמול בערב"
        context = MagicMock()
        context.chat_data = {}
        last_entry = {
            "entry_id": "abc123",
            "calories": 300, "protein": 25, "description": "original",
            "date": "16/06/2026", "time": "12:00",
        }
        profile = MagicMock()
        profile.timezone = "Asia/Jerusalem"

        await handler.handle_correction(
            message, context, correction, last_entry,
            profile, "16/06/2026", 123,
        )

        ctx.food_repo.move.assert_called_once()
        move_args = ctx.food_repo.move.call_args
        assert move_args[0][0] == "abc123"
        assert move_args[0][1] == "15/06/2026"
        assert move_args[1]["new_time"] == "20:00"

    @pytest.mark.asyncio
    async def test_date_change_to_different_day_sets_within_window_true(self):
        from handlers.food_handler import FoodHandler

        ctx = self._make_ctx()
        handler = FoodHandler(ctx)
        correction = self._make_correction(date="15/06/2026")

        message = MagicMock()
        message.text = "זה היה אתמול"
        context = MagicMock()
        context.chat_data = {}
        last_entry = {
            "entry_id": "abc123",
            "calories": 300, "protein": 25, "description": "original",
            "date": "16/06/2026", "time": "12:00",
        }
        profile = MagicMock()
        profile.timezone = "Asia/Jerusalem"

        await handler.handle_correction(
            message, context, correction, last_entry,
            profile, "16/06/2026", 123,
        )

        move_call = ctx.food_repo.move.call_args
        assert move_call[1]["within_window"] is True


class TestPendingCorrectionIncludesDate:
    @pytest.mark.asyncio
    async def test_pending_correction_entry_has_date_and_time(self):
        from handlers.callback_handler import CallbackHandler

        ctx = MagicMock()
        food_entry = MagicMock()
        food_entry.description = "שווארמה"
        food_entry.calories = 700
        food_entry.protein = 40
        food_entry.photo_file_id = None
        food_entry.original_description = None
        food_entry.original_calories = None
        food_entry.original_protein = None
        food_entry.correction_history = []
        food_entry.date = "16/06/2026"
        food_entry.time = "12:00"
        ctx.food_repo.get.return_value = food_entry
        ctx.landing_page_url = "https://example.com"

        handler = CallbackHandler(ctx)

        update = MagicMock()
        query = MagicMock()
        query.data = "fedit_abc123"
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()
        update.callback_query = query

        context = MagicMock()
        context.chat_data = {}

        await handler.handle_food_edit_callback(update, context)

        pending = context.chat_data["pending_correction"]
        assert pending["entry"]["date"] == "16/06/2026"
        assert pending["entry"]["time"] == "12:00"
