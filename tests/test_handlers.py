"""
test_handlers.py - TDD for HealthHandlers (Telegram bot message handlers).

Tests the handler layer that processes classified messages and produces
Telegram responses. All external dependencies (Telegram, MongoDB, OpenAI)
are mocked - these are unit tests, not integration tests.

# ============================================================================
# HANDLERS SPECIFICATION (Single Source of Truth)
#
# This comment defines the expected behavior of each handler. When behavior
# changes, UPDATE THIS COMMENT FIRST, then update/add tests, then fix code
# to pass.
#
# ============================================================================
#
# DAILY STATUS FORMAT (format_daily_status)
# ------------------------------------------
# - Under calorie target: shows checkmark, remaining count
# - Over calorie target: shows warning emoji, over amount
# - Same logic for protein: checkmark when on track, warning when below
#
# CROSSING ALERTS (_check_crossing_alerts)
# -----------------------------------------
# - Protein target reached: congratulations message with "כל הכבוד" + "חלבון"
# - Calorie target exceeded: warning message with "עברת" + "קלוריות"
# - Both can fire simultaneously
# - No alert when both metrics within range
#
# FOOD RESPONSE FORMAT (_build_food_response, _format_items_text)
# ----------------------------------------------------------------
# - Each food item on two lines: name, then grams/calories/protein
# - Single item: no total line
# - Multiple items: total line with "סה״כ"
# - Items joined with ", " in one-row-per-message format
# - Totals correctly summed across items
#
# DAILY SUMMARY CALLBACK (handle_daily_callback)
# ------------------------------------------------
# - Shows itemized entries with time and totals
# - Empty day shows "אין רשומות" (no entries)
#
# CORRECTION FLOW (_handle_pending_correction, _format_correction_response)
# --------------------------------------------------------------------------
# - Calls analyzer.analyze_correction with original description + new text
# - Correction history accumulates across multiple rounds
# - Response shows three sections: "רשומה מקורית" (original), "עריכה"
#   (edit), "חדש" (new), "רשומה מעודכנת" (updated)
# - Removed items show "הוסר" marker, don't appear in updated section
# - First correction saves original_description, original_calories,
#   original_protein, correction_history, and edit_expires_at
# - Second correction preserves the FIRST original values (not the
#   already-corrected values)
# - Photo corrections: photo_file_id is re-downloaded and passed as
#   photo_base64 to analyzer
#
# FOOD AGAIN CALLBACK (handle_food_again_callback)
# --------------------------------------------------
# - Duplicates the entry with new date/time
# - Response includes description and calories
#
# TOGGLE CANCEL HANDLER (_handle_toggle_cancel)
# -----------------------------------------------
# Context-aware refusal behavior based on toggle state and refusal tone:
#
#   - Sharp refusal during offer -> ask remind (don't activate the toggle)
#   - Soft refusal during offer -> softer message + ask remind
#   - Sharp refusal during goal-setting -> keep habit active, skip goal,
#     ask remind
#   - Soft refusal during goal-setting -> keep active, per-habit soft
#     message ("סבבה, בלי יעד בינתיים..."), ask remind
#   - Decline during remind_pending -> permanent decline
#     (GOAL_DECLINED_FOREVER message, never asks again)
#   - Cancel active habit (no flow) -> full cancel (EXIT_DOOR_CANCELLED)
#
# ============================================================================
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

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

from types import SimpleNamespace
from analyzer import FoodItem, FoodAnalysisResult, FoodPhotoResult, CorrectionFoodItem
from keyboards import format_daily_status
from models.profile import UserProfile, EatingWindow, Targets, ToggleState, Toggles
from models.food import FoodEntry


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


class TestFormatDailyStatus:
    def test_under_calorie_target(self):
        result = format_daily_status(1500, 120, 2000, 150)
        assert "✅" in result
        assert "1500/2000" in result
        assert "500" in result

    def test_over_calorie_target(self):
        result = format_daily_status(2200, 120, 2000, 150)
        assert "⚠️" in result
        assert "2200/2000" in result

    def test_protein_above_target(self):
        result = format_daily_status(1500, 160, 2000, 150)
        assert "✅" in result
        assert "160" in result

    def test_protein_below_target(self):
        result = format_daily_status(1500, 100, 2000, 150)
        lines = result.split("\n")
        protein_line = [l for l in lines if "חלבון" in l][0]
        assert "⚠️" in protein_line


class TestCrossingAlerts:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        return h

    def test_no_alert_when_both_within_range(self):
        h = self._make_handler()
        profile = _make_profile()
        result = h._check_crossing_alerts(1000, 80, 1500, 100, profile)
        assert result == ""

    def test_protein_target_reached(self):
        h = self._make_handler()
        profile = _make_profile()
        result = h._check_crossing_alerts(1000, 130, 1400, 155, profile)
        assert "כל הכבוד" in result
        assert "חלבון" in result

    def test_calorie_target_exceeded(self):
        h = self._make_handler()
        profile = _make_profile()
        result = h._check_crossing_alerts(1800, 100, 2100, 120, profile)
        assert "עברת" in result
        assert "קלוריות" in result

    def test_both_alerts(self):
        h = self._make_handler()
        profile = _make_profile()
        result = h._check_crossing_alerts(1800, 140, 2100, 160, profile)
        assert "כל הכבוד" in result
        assert "עברת" in result


class TestBuildFoodResponse:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        return h

    def test_includes_items_and_status(self):
        h = self._make_handler()
        profile = _make_profile()
        response = h._build_food_response("• שניצל: 400 קל׳", 400, 30, profile)
        assert "שניצל" in response
        assert "400/2000" in response
        assert "30/150" in response


class TestFormatItemsText:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        return h

    def test_single_item_shows_grams(self):
        h = self._make_handler()
        items = [FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)]
        result = h._format_items_text(items, 400, 30)
        assert "• שניצל" in result
        assert "~200 גרם" in result
        assert "400 קל׳" in result
        assert "30 גרם חלבון" in result
        assert "סה\"כ" not in result

    def test_multiple_items_shows_total(self):
        h = self._make_handler()
        items = [
            FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30),
            FoodItem(description="סלט", estimated_grams=150, calories=50, protein=3),
        ]
        result = h._format_items_text(items, 450, 33)
        assert "• שניצל" in result
        assert "• סלט" in result
        assert "סה\"כ: 450 קל׳ | 33 גרם חלבון" in result

    def test_two_line_format_per_item(self):
        h = self._make_handler()
        items = [FoodItem(description="חביתה מ-2 ביצים", estimated_grams=120, calories=180, protein=12)]
        result = h._format_items_text(items, 180, 12)
        lines = result.split("\n")
        assert lines[0] == "• חביתה מ-2 ביצים"
        assert lines[1].strip().startswith("~120 גרם")


class TestOneRowPerMessage:
    def test_items_joined_with_comma(self):
        items = [
            MagicMock(description="שניצל", calories=400, protein=30),
            MagicMock(description="סלט", calories=50, protein=3),
        ]
        combined = ", ".join(item.description for item in items)
        assert combined == "שניצל, סלט"

    def test_totals_summed(self):
        items = [
            MagicMock(description="שניצל", calories=400, protein=30),
            MagicMock(description="סלט", calories=50, protein=3),
        ]
        total_cal = sum(item.calories for item in items)
        total_prot = sum(item.protein for item in items)
        assert total_cal == 450
        assert total_prot == 33


class TestDailySummaryCallback:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        h.landing_page_url = ""
        return h

    @pytest.mark.asyncio
    @patch("handlers.base.make_daily_summary_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_shows_itemized_entries(self, mock_send, mock_answer, mock_now, _kb):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_entries.return_value = [
            FoodEntry(telegram_user_id=123, date="11/05/2026", time="09:30",
                      description="שניצל ואורז", calories=650, protein=40, within_window=True),
            FoodEntry(telegram_user_id=123, date="11/05/2026", time="13:00",
                      description="סלט יווני", calories=300, protein=15, within_window=True),
        ]

        query = AsyncMock()
        query.data = "daily_summary"
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        context = MagicMock()

        await h.handle_daily_callback(update, context)

        mock_answer.assert_called_once()
        call_text = mock_send.call_args[0][1]
        assert "שניצל ואורז" in call_text
        assert "סלט יווני" in call_text
        assert "09:30" in call_text
        assert "950/2000" in call_text

    @pytest.mark.asyncio
    @patch("handlers.base.make_daily_summary_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_shows_empty_message(self, mock_answer, mock_now, _kb):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_entries.return_value = []

        query = AsyncMock()
        query.data = "daily_summary"
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        context = MagicMock()

        await h.handle_daily_callback(update, context)

        query.edit_message_text.assert_called_once()
        call_text = query.edit_message_text.call_args[0][0]
        assert "אין רשומות" in call_text


class TestCorrectionHistory:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        h.landing_page_url = ""
        return h

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_calls_analyze_correction(self, mock_send, mock_react, mock_now, _kb):
        from datetime import datetime as dt
        from analyzer import CorrectionResult
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (950, 55)

        correction_result = CorrectionResult(
            items=[
                CorrectionFoodItem(description="המבורגר 300 גרם", estimated_grams=300, calories=750, protein=45, change_type="modified"),
                CorrectionFoodItem(description="צ'יפס", estimated_grams=150, calories=150, protein=3),
                CorrectionFoodItem(description="סלט", estimated_grams=200, calories=50, protein=7),
            ],
            corrected_description="המבורגר 300 גרם, צ'יפס, סלט",
            corrected_calories=950,
            corrected_protein=55,
        )
        h.analyzer.analyze_correction.return_value = correction_result

        message = AsyncMock()
        message.text = "ההמבורגר הוא 300 גרם"
        context = MagicMock()
        context.chat_data = {
            "pending_correction": {
                "entry": {
                    "description": "המבורגר 100 גרם, צ'יפס, סלט",
                    "calories": 650,
                    "protein": 40,
                    "entry_id": "abc123def456abc123def456",
                },
                "correction_history": [],
                "timestamp": __import__("time").time(),
            }
        }

        await h._handle_pending_correction(message, context, 123, profile)

        h.analyzer.analyze_correction.assert_called_once()
        call_kwargs = h.analyzer.analyze_correction.call_args
        assert call_kwargs[1]["original_description"] == "המבורגר 100 גרם, צ'יפס, סלט"
        assert call_kwargs[1]["new_correction"] == "ההמבורגר הוא 300 גרם"

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_history_accumulates(self, mock_send, mock_react, mock_now, _kb):
        from datetime import datetime as dt
        from analyzer import CorrectionResult
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (1100, 55)

        entry_id = "abc123def456abc123def456"
        correction_result = CorrectionResult(
            items=[
                CorrectionFoodItem(description="המבורגר 300 גרם", estimated_grams=300, calories=750, protein=45, change_type="modified"),
                CorrectionFoodItem(description="צ'יפס גדול", estimated_grams=250, calories=300, protein=4, change_type="modified"),
                CorrectionFoodItem(description="סלט", estimated_grams=200, calories=50, protein=6),
            ],
            corrected_description="המבורגר 300 גרם, צ'יפס גדול, סלט",
            corrected_calories=1100,
            corrected_protein=55,
        )
        h.analyzer.analyze_correction.return_value = correction_result

        message = AsyncMock()
        message.text = "הצ'יפס היה מנה גדולה"
        context = MagicMock()
        context.chat_data = {
            "pending_correction": {
                "entry": {
                    "description": "המבורגר 100 גרם, צ'יפס, סלט",
                    "calories": 650,
                    "protein": 40,
                    "entry_id": entry_id,
                },
                "correction_history": ["ההמבורגר הוא 300 גרם"],
                "timestamp": __import__("time").time(),
            },
            "correction_histories": {entry_id: ["ההמבורגר הוא 300 גרם"]},
        }

        await h._handle_pending_correction(message, context, 123, profile)

        call_kwargs = h.analyzer.analyze_correction.call_args
        assert call_kwargs[1]["correction_history"] == ["ההמבורגר הוא 300 גרם"]
        assert "הצ'יפס היה מנה גדולה" in context.chat_data["correction_histories"][entry_id]


class TestCorrectionResponseFormat:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        h.landing_page_url = ""
        return h

    def test_format_correction_response_shows_three_sections(self):
        from analyzer import CorrectionResult, CorrectionFoodItem
        h = self._make_handler()
        correction = CorrectionResult(
            items=[
                CorrectionFoodItem(description="שניצל", estimated_grams=200, calories=300, protein=25, change_type="modified"),
                CorrectionFoodItem(description="צ'יפס", estimated_grams=200, calories=400, protein=5),
                CorrectionFoodItem(description="סלט ירקות", estimated_grams=150, calories=45, protein=2, change_type="added"),
            ],
            corrected_description="שניצל, צ'יפס, סלט ירקות",
            corrected_calories=745,
            corrected_protein=32,
        )
        result = h._format_correction_response(
            correction,
            orig_desc="שניצל 300 גרם, צ'יפס",
            orig_cal=850, orig_prot=40,
            new_cal=745, new_prot=32,
        )
        assert "רשומה מקורית" in result
        assert "שניצל 300 גרם, צ'יפס" in result
        assert "850" in result
        assert "עריכה" in result
        assert "שניצל" in result
        assert "חדש" in result  # added item
        assert "רשומה מעודכנת" in result
        assert "745" in result

    def test_format_correction_response_removed_item(self):
        from analyzer import CorrectionResult, CorrectionFoodItem
        h = self._make_handler()
        correction = CorrectionResult(
            items=[
                CorrectionFoodItem(description="שניצל", estimated_grams=300, calories=450, protein=35),
                CorrectionFoodItem(description="צ'יפס", estimated_grams=200, calories=400, protein=5, change_type="removed"),
            ],
            corrected_description="שניצל",
            corrected_calories=450,
            corrected_protein=35,
        )
        result = h._format_correction_response(
            correction,
            orig_desc="שניצל, צ'יפס",
            orig_cal=850, orig_prot=40,
            new_cal=450, new_prot=35,
        )
        assert "הוסר" in result
        # Removed item should NOT appear in updated section
        lines_after_updated = result.split("רשומה מעודכנת:")[1]
        assert "צ'יפס" not in lines_after_updated

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_persists_original_values(self, mock_send, mock_react, mock_now, _kb):
        from datetime import datetime as dt
        from analyzer import CorrectionResult, CorrectionFoodItem
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (950, 55)

        entry_id = "abc123def456abc123def456"
        correction = CorrectionResult(
            items=[CorrectionFoodItem(description="שניצל 200 גרם", estimated_grams=200, calories=300, protein=25, change_type="modified")],
            corrected_description="שניצל 200 גרם",
            corrected_calories=300, corrected_protein=25,
        )

        last_entry = {
            "description": "שניצל 300 גרם",
            "calories": 450,
            "protein": 35,
            "entry_id": entry_id,
        }
        message = AsyncMock()
        message.text = "השניצל היה 200 גרם"
        context = MagicMock()
        context.chat_data = {}

        await h._handle_correction(message, context, correction, last_entry, profile, "11/05/2026", 123)

        update_args = h.food_repo.update.call_args
        fields = update_args[0][1]
        assert fields["original_description"] == "שניצל 300 גרם"
        assert fields["original_calories"] == 450
        assert fields["original_protein"] == 35
        assert fields["correction_history"] == ["השניצל היה 200 גרם"]
        assert "edit_expires_at" in fields

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_preserves_existing_originals(self, mock_send, mock_react, mock_now, _kb):
        """Second correction should keep the first correction's original values."""
        from datetime import datetime as dt
        from analyzer import CorrectionResult, CorrectionFoodItem
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (300, 25)

        entry_id = "abc123def456abc123def456"
        correction = CorrectionResult(
            items=[CorrectionFoodItem(description="שניצל 150 גרם", estimated_grams=150, calories=225, protein=18, change_type="modified")],
            corrected_description="שניצל 150 גרם",
            corrected_calories=225, corrected_protein=18,
        )

        # Second correction - already has original_* from first correction
        last_entry = {
            "description": "שניצל 200 גרם",
            "calories": 300,
            "protein": 25,
            "entry_id": entry_id,
            "original_description": "שניצל 300 גרם",
            "original_calories": 450,
            "original_protein": 35,
        }
        message = AsyncMock()
        message.text = "עכשיו 150"
        context = MagicMock()
        context.chat_data = {"correction_histories": {entry_id: ["השניצל 200 גרם"]}}

        await h._handle_correction(message, context, correction, last_entry, profile, "11/05/2026", 123)

        fields = h.food_repo.update.call_args[0][1]
        # Should keep the FIRST original, not the second correction's values
        assert fields["original_description"] == "שניצל 300 גרם"
        assert fields["original_calories"] == 450
        assert fields["original_protein"] == 35

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_passes_photo_to_analyzer(self, mock_send, mock_react, mock_now, _kb):
        from datetime import datetime as dt
        from analyzer import CorrectionResult, CorrectionFoodItem
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (500, 30)

        correction = CorrectionResult(
            items=[CorrectionFoodItem(description="test", estimated_grams=100, calories=100, protein=10)],
            corrected_description="test", corrected_calories=100, corrected_protein=10,
        )
        h.analyzer.analyze_correction.return_value = correction

        # Mock bot.get_file for photo re-download
        mock_file = AsyncMock()
        mock_file.download_as_bytearray.return_value = bytearray(b"fake_photo_data")

        message = AsyncMock()
        message.text = "שכחת את הסלט"
        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=mock_file)
        context.chat_data = {
            "pending_correction": {
                "entry": {
                    "description": "שניצל",
                    "calories": 400,
                    "protein": 30,
                    "entry_id": "abc123def456abc123def456",
                    "photo_file_id": "AgACAgIAAx0CfakePhotoId",
                },
                "correction_history": [],
                "timestamp": __import__("time").time(),
            }
        }

        await h._handle_pending_correction(message, context, 123, profile)

        # Should have called get_file with the photo_file_id
        context.bot.get_file.assert_called_once_with("AgACAgIAAx0CfakePhotoId")
        # Should have passed photo_base64 to analyzer
        call_kwargs = h.analyzer.analyze_correction.call_args[1]
        assert call_kwargs["photo_base64"] is not None


class TestFoodAgainCallback:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        h.landing_page_url = ""
        return h

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_again_duplicates_entry(self, mock_answer, mock_now, mock_kb):
        from datetime import datetime as dt
        from bson import ObjectId
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 13, 15, 30, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile

        original_id = str(ObjectId())
        new_id = str(ObjectId())
        h.food_repo.get.return_value = FoodEntry(
            id=original_id,
            telegram_user_id=123,
            date="12/05/2026",
            time="12:00",
            description="חזה עוף 200 גרם",
            calories=350,
            protein=45,
            within_window=True,
        )
        saved_entry = FoodEntry(
            id=new_id,
            telegram_user_id=123,
            date="13/05/2026",
            time="15:30",
            description="חזה עוף 200 גרם",
            calories=350,
            protein=45,
            within_window=True,
        )
        h.food_repo.add.return_value = saved_entry
        h.eating_day_svc.get_stats_date.return_value = "13/05/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (700, 90)

        query = AsyncMock()
        query.data = f"fagain_{original_id}"
        query.message.chat_id = 12345
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.chat_data = {}

        await h.handle_food_again_callback(update, context)

        h.food_repo.get.assert_called_once_with(original_id)
        h.food_repo.add.assert_called_once()
        mock_kb.assert_called_with(new_id)
        context.bot.send_message.assert_called_once()
        call_text = context.bot.send_message.call_args[1]["text"]
        assert "חזה עוף 200 גרם" in call_text
        assert "350" in call_text


# ============================================================================
# TOGGLE CANCEL HANDLER - context-aware refusal behavior
# ============================================================================

class TestToggleCancelHandler:
    """Tests for the rewritten toggle_cancel handler.

    The handler must distinguish:
    - Sharp refusal during offer -> ask remind (don't activate)
    - Soft refusal during offer -> softer message + ask remind
    - Sharp refusal during goal-setting -> keep habit active, skip goal, ask remind
    - Soft refusal during goal-setting -> keep active, per-habit soft message, ask remind
    - Decline during remind_pending -> permanent decline (GOAL_DECLINED_FOREVER)
    - Cancel active habit (no flow) -> full cancel (EXIT_DOOR_CANCELLED)
    """

    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.toggle_service = MagicMock()
        h.goal_service = MagicMock()
        h.feedback_service = None
        h.message_router = None
        h.trial_service = None
        h.onboarding_service = None
        h.eating_day_svc = MagicMock()
        h.food_repo = MagicMock()
        h.analyzer = None
        h.landing_page_url = "https://test.com"
        h.user_repo.get_recent_messages.return_value = []
        h.user_repo.push_messages = MagicMock()
        return h

    def _make_classification(self, toggle_name=None, refusal_tone="sharp"):
        return SimpleNamespace(
            type="toggle_cancel",
            toggle_name=toggle_name,
            refusal_tone=refusal_tone,
        )

    # -- Sharp refusal during OFFER (dormant + revealed) --

    @pytest.mark.asyncio
    async def test_sharp_cancel_during_offer_asks_remind(self):
        """Sharp refusal of offered toggle -> ask_remind, NOT cancel_toggle."""
        h = self._make_handler()
        profile = _make_profile()
        profile.toggles.sleep.status = "dormant"
        profile.toggles.sleep.revealed_at = "2026-06-01T00:00:00+00:00"

        h.goal_service.ask_remind.return_value = "בסדר. רוצה שאזכיר לך בעתיד?"

        message = AsyncMock()
        message.text = "לא רוצה"
        context = MagicMock()
        context.chat_data = {}

        classification = self._make_classification(toggle_name="sleep", refusal_tone="sharp")
        await h._handle_toggle_cancel(message, context, 123, profile, classification)

        h.toggle_service.cancel_toggle.assert_not_called()
        h.goal_service.ask_remind.assert_called_once_with(123, "sleep")

    # -- Soft refusal during OFFER --

    @pytest.mark.asyncio
    async def test_soft_cancel_during_offer_asks_remind(self):
        """Soft refusal of offered toggle -> soft message + ask remind."""
        h = self._make_handler()
        profile = _make_profile()
        profile.toggles.sleep.status = "dormant"
        profile.toggles.sleep.revealed_at = "2026-06-01T00:00:00+00:00"

        h.goal_service.ask_remind.return_value = "רוצה שאזכיר לך בהמשך?"

        message = AsyncMock()
        message.text = "לא סגור על זה"
        context = MagicMock()
        context.chat_data = {}

        classification = self._make_classification(toggle_name="sleep", refusal_tone="soft")
        await h._handle_toggle_cancel(message, context, 123, profile, classification)

        h.toggle_service.cancel_toggle.assert_not_called()
        h.goal_service.ask_remind.assert_called_once_with(123, "sleep")

    # -- Sharp refusal during GOAL SETTING --

    @pytest.mark.asyncio
    async def test_sharp_cancel_during_goal_keeps_habit_active(self):
        """Sharp refusal during goal-setting -> keep active, skip goal, ask remind."""
        h = self._make_handler()
        profile = _make_profile()
        profile.toggles.nutrition.status = "active"
        profile.toggles.nutrition.goal_status = "pending"
        profile.toggles.nutrition.goal_offered_at = "2026-06-01T00:00:00+00:00"

        h.goal_service.skip_goal.return_value = None
        h.goal_service.ask_remind.return_value = "רוצה שאזכיר לך בעתיד?"

        message = AsyncMock()
        message.text = "לא"
        context = MagicMock()
        context.chat_data = {}

        classification = self._make_classification(toggle_name="nutrition", refusal_tone="sharp")
        await h._handle_toggle_cancel(message, context, 123, profile, classification)

        h.toggle_service.cancel_toggle.assert_not_called()
        h.goal_service.skip_goal.assert_called_once_with(123, "nutrition")
        h.goal_service.ask_remind.assert_called_once_with(123, "nutrition")

    # -- Soft refusal during GOAL SETTING --

    @pytest.mark.asyncio
    async def test_soft_cancel_during_goal_keeps_habit_sends_soft_message(self):
        """Soft refusal during goal-setting -> keep active, soft per-habit message."""
        h = self._make_handler()
        profile = _make_profile()
        profile.toggles.nutrition.status = "active"
        profile.toggles.nutrition.goal_status = "pending"
        profile.toggles.nutrition.goal_offered_at = "2026-06-01T00:00:00+00:00"

        h.goal_service.skip_goal.return_value = None
        h.goal_service.ask_remind.return_value = "רוצה שאזכיר לך בהמשך?"

        message = AsyncMock()
        message.text = "לא בטוח"
        context = MagicMock()
        context.chat_data = {}

        classification = self._make_classification(toggle_name="nutrition", refusal_tone="soft")
        await h._handle_toggle_cancel(message, context, 123, profile, classification)

        h.toggle_service.cancel_toggle.assert_not_called()
        h.goal_service.skip_goal.assert_called_once_with(123, "nutrition")
        # Should have sent a response (soft decline message + remind ask)
        message.reply_text.assert_called()

    # -- Decline during REMIND PENDING --

    @pytest.mark.asyncio
    async def test_cancel_during_remind_pending_uses_declined_forever(self):
        """Decline reminder -> permanent decline with GOAL_DECLINED_FOREVER."""
        import messages as M
        h = self._make_handler()
        profile = _make_profile()
        profile.toggles.nutrition.status = "dormant"
        profile.toggles.nutrition.goal_status = "remind_pending"

        message = AsyncMock()
        message.text = "לא, תעזוב"
        context = MagicMock()
        context.chat_data = {}

        classification = self._make_classification(toggle_name="nutrition", refusal_tone="sharp")
        await h._handle_toggle_cancel(message, context, 123, profile, classification)

        h.toggle_service.cancel_toggle.assert_called_once_with(123, "nutrition")
        sent_text = message.reply_text.call_args[0][0]
        assert sent_text in M.GOAL_DECLINED_FOREVER

    # -- Cancel ACTIVE habit (no flow) --

    @pytest.mark.asyncio
    async def test_cancel_active_habit_full_cancel(self):
        """Cancel an active habit with no pending goal flow -> full cancel."""
        import messages as M
        h = self._make_handler()
        profile = _make_profile()
        profile.toggles.sleep.status = "active"
        profile.toggles.sleep.goal_status = "set"

        message = AsyncMock()
        message.text = "תפסיק לשאול אותי על שינה"
        context = MagicMock()
        context.chat_data = {}

        classification = self._make_classification(toggle_name="sleep", refusal_tone="sharp")
        await h._handle_toggle_cancel(message, context, 123, profile, classification)

        h.toggle_service.cancel_toggle.assert_called_once_with(123, "sleep")
        sent_text = message.reply_text.call_args[0][0]
        assert sent_text == M.EXIT_DOOR_CANCELLED


# ============================================================================
# EDIT FLOW INTEGRATION (handle_message -> _handle_pending_correction)
# ============================================================================
# When pending_correction is set in chat_data, handle_message must:
# - Route to _handle_pending_correction BEFORE the Router/classifier
# - Call analyze_correction (not classify_message) with the original entry context
# - Re-download photo if photo_file_id is present
# - Update the existing food entry (not create a new one)
# - Never reach the Router at all
# ============================================================================

class TestEditFlowIntegration:
    """Integration tests: handle_message correctly routes through pending_correction."""

    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        h.trial_service = None
        h.re_engagement_service = None
        h.toggle_service = MagicMock()
        h.message_router = None
        h.landing_page_url = "https://example.com"
        h.wisdom_gem_service = None
        h._setup_token_tracking = MagicMock()
        return h

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_pending_correction_bypasses_router(self, mock_send, mock_react, mock_now, _kb):
        """When pending_correction exists, handle_message calls _handle_pending_correction,
        not the Router. The Router/classifier should never be invoked."""
        from datetime import datetime as dt
        from analyzer import CorrectionResult
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 10, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h._get_profile = MagicMock(return_value=profile)
        h.eating_day_svc.resolve_eating_day.return_value = "10/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (800, 50)
        h.eating_day_svc.get_stats_date.return_value = "10/06/2026"

        entry_id = "abc123def456abc123def456"
        correction_result = CorrectionResult(
            items=[
                CorrectionFoodItem(description="שניצל 200 גרם", estimated_grams=200, calories=400, protein=35, change_type="modified"),
                CorrectionFoodItem(description="אורז", estimated_grams=200, calories=260, protein=5),
            ],
            corrected_description="שניצל 200 גרם, אורז",
            corrected_calories=660,
            corrected_protein=40,
        )
        h.analyzer.analyze_correction.return_value = correction_result

        # Build the Update/Message mocks as handle_message expects
        message = AsyncMock()
        message.text = "השניצל היה 200 גרם לא 100"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123

        context = MagicMock()
        context.chat_data = {
            "pending_correction": {
                "entry": {
                    "description": "שניצל 100 גרם, אורז",
                    "calories": 500,
                    "protein": 30,
                    "entry_id": entry_id,
                },
                "correction_history": [],
                "timestamp": __import__("time").time(),
            }
        }

        await h.handle_message(update, context)

        # _handle_pending_correction was used (analyze_correction called)
        h.analyzer.analyze_correction.assert_called_once()
        call_kwargs = h.analyzer.analyze_correction.call_args[1]
        assert call_kwargs["original_description"] == "שניצל 100 גרם, אורז"
        assert call_kwargs["new_correction"] == "השניצל היה 200 גרם לא 100"

        # Router/classifier was NOT called
        h.analyzer.classify_message.assert_not_called()
        h.analyzer.classify_message.assert_not_called()

        # pending_correction was consumed
        assert "pending_correction" not in context.chat_data

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_pending_correction_with_photo_redownloads(self, mock_send, mock_react, mock_now, _kb):
        """When pending entry has photo_file_id, the photo is re-downloaded and
        passed as photo_base64 to analyze_correction."""
        from datetime import datetime as dt
        from analyzer import CorrectionResult
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 10, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h._get_profile = MagicMock(return_value=profile)
        h.eating_day_svc.resolve_eating_day.return_value = "10/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (800, 50)
        h.eating_day_svc.get_stats_date.return_value = "10/06/2026"

        entry_id = "photo_entry_id_123456789012"
        correction_result = CorrectionResult(
            items=[
                CorrectionFoodItem(description="שווארמה בפיתה", estimated_grams=350, calories=650, protein=40, change_type="modified"),
            ],
            corrected_description="שווארמה בפיתה",
            corrected_calories=650,
            corrected_protein=40,
        )
        h.analyzer.analyze_correction.return_value = correction_result

        message = AsyncMock()
        message.text = "זה שווארמה לא פלאפל"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123

        # Mock photo re-download
        mock_file = AsyncMock()
        mock_file.download_as_bytearray.return_value = bytearray(b"fake_photo_bytes")
        context = MagicMock()
        context.bot.get_file = AsyncMock(return_value=mock_file)
        context.chat_data = {
            "pending_correction": {
                "entry": {
                    "description": "פלאפל בפיתה",
                    "calories": 450,
                    "protein": 15,
                    "entry_id": entry_id,
                    "photo_file_id": "AgACAgIAAxk_photo_id",
                },
                "correction_history": [],
                "timestamp": __import__("time").time(),
            }
        }

        await h.handle_message(update, context)

        # Photo was re-downloaded
        context.bot.get_file.assert_called_once_with("AgACAgIAAxk_photo_id")

        # analyze_correction received photo_base64
        call_kwargs = h.analyzer.analyze_correction.call_args[1]
        assert call_kwargs["photo_base64"] is not None
        assert len(call_kwargs["photo_base64"]) > 0

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_no_pending_correction_reaches_router(self, mock_send, mock_react, mock_now, _kb):
        """Without pending_correction, handle_message proceeds to Router classification."""
        from datetime import datetime as dt
        from analyzer import RouterClassification
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 10, 14, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h._get_profile = MagicMock(return_value=profile)
        h.eating_day_svc.resolve_eating_day.return_value = "10/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        h.eating_day_svc.get_stats_date.return_value = "10/06/2026"
        h.user_repo.get_recent_messages.return_value = []

        # Router returns conversational so we don't need meal extraction mocks
        h.analyzer.classify_message.return_value = RouterClassification(type="conversational")
        h._handle_conversational = AsyncMock()

        message = AsyncMock()
        message.text = "מה שלומך"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123

        context = MagicMock()
        context.chat_data = {}  # No pending_correction

        await h.handle_message(update, context)

        # Router WAS called (no pending state to intercept)
        h.analyzer.classify_message.assert_called_once()
        # analyze_correction was NOT called
        h.analyzer.analyze_correction.assert_not_called()


# ============================================================================
# KEYBOARD PRESERVATION
# ============================================================================
# Food entry messages must always preserve their inline keyboard (edit/delete/
# duplicate buttons). The menu is the user's only way to interact with an entry.
#
# EDIT FLOW KEYBOARD RESTORATION
# --------------------------------
# - handle_food_edit_callback stores edit_message_id + edit_chat_id in
#   pending_correction so the original message can be found later
# - After correction completes, the original "edit prompt" message gets
#   its keyboard restored via edit_message_reply_markup
# - If correction fails or pending state expires, the keyboard is still
#   restored on the original message
#
# SILENT EXCEPTION HANDLERS
# ---------------------------
# - handle_food_delete_callback exception: must send error + keyboard
# - handle_food_edit_callback exception: must send error + keyboard
# - handle_food_again_callback exception: must send error + keyboard
# ============================================================================


class TestKeyboardPreservation:
    """Tests that food entry keyboards are never permanently lost."""

    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        h.landing_page_url = ""
        return h

    # -- Edit flow stores message coordinates for later restoration --

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_edit_callback_stores_message_id(self, mock_answer):
        """handle_food_edit_callback must store the original message_id and
        chat_id in pending_correction so the keyboard can be restored later."""
        from bson import ObjectId

        h = self._make_handler()
        entry_id = str(ObjectId())
        h.food_repo.get.return_value = FoodEntry(
            id=entry_id, telegram_user_id=123, date="15/06/2026",
            time="15:00", description="בשר ושקדים", calories=500,
            protein=40, within_window=True,
        )

        query = AsyncMock()
        query.data = f"fedit_{entry_id}"
        query.message.message_id = 42
        query.message.chat_id = 12345
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        context = MagicMock()
        context.chat_data = {}

        await h.handle_food_edit_callback(update, context)

        pending = context.chat_data["pending_correction"]
        assert pending["edit_message_id"] == 42
        assert pending["edit_chat_id"] == 12345

    # -- After correction completes, original message keyboard is restored --

    @pytest.mark.asyncio
    @patch("handlers.pending_handler.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.pending_handler.get_user_now")
    @patch("handlers.pending_handler.safe_react", new_callable=AsyncMock)
    async def test_correction_restores_keyboard_on_original_message(self, mock_react, mock_now, mock_kb):
        """After pending_correction completes, the original edit-prompt message
        should get its keyboard restored via edit_message_reply_markup."""
        from datetime import datetime as dt
        from analyzer import CorrectionResult, CorrectionFoodItem as CFI
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 15, 15, 0, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "15/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (500, 40)

        entry_id = "abc123def456abc123def456"
        correction_result = CorrectionResult(
            items=[CFI(description="בשר 200 גרם", estimated_grams=200, calories=500, protein=40, change_type="modified")],
            corrected_description="בשר 200 גרם",
            corrected_calories=500,
            corrected_protein=40,
        )
        h.analyzer.analyze_correction.return_value = correction_result

        message = AsyncMock()
        message.text = "הבשר היה 200 גרם"
        context = MagicMock()
        context.bot.edit_message_reply_markup = AsyncMock()
        context.chat_data = {
            "pending_correction": {
                "entry": {
                    "description": "בשר ושקדים",
                    "calories": 500,
                    "protein": 40,
                    "entry_id": entry_id,
                },
                "correction_history": [],
                "timestamp": __import__("time").time(),
                "edit_message_id": 42,
                "edit_chat_id": 12345,
            }
        }

        from handlers.pending_handler import PendingHandler
        ph = PendingHandler(h)
        result = await ph.handle_pending_correction(message, context, 123, profile)

        assert result is True
        # Keyboard restored on original message
        context.bot.edit_message_reply_markup.assert_called_once_with(
            chat_id=12345,
            message_id=42,
            reply_markup=mock_kb.return_value,
        )

    # -- Exception handlers must send error + keyboard, not fail silently --

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_food_delete_exception_sends_error_with_keyboard(self, mock_answer):
        """When food deletion throws, user must see an error message (not silence)."""
        h = self._make_handler()
        h.food_repo.delete.side_effect = Exception("DB error")

        query = AsyncMock()
        query.data = "fdel_some_entry_id"
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        context = MagicMock()

        await h.handle_food_delete_callback(update, context)

        # Must edit message with error text + keyboard (not silent)
        query.edit_message_text.assert_called_once()
        call_kwargs = query.edit_message_text.call_args
        assert call_kwargs[1].get("reply_markup") is not None

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_food_edit_exception_sends_error_with_keyboard(self, mock_answer):
        """When food edit read throws, user must see an error message (not silence)."""
        h = self._make_handler()
        h.food_repo.get.side_effect = Exception("DB error")

        query = AsyncMock()
        query.data = "fedit_some_entry_id"
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        context = MagicMock()
        context.chat_data = {}

        await h.handle_food_edit_callback(update, context)

        query.edit_message_text.assert_called_once()
        call_kwargs = query.edit_message_text.call_args
        assert call_kwargs[1].get("reply_markup") is not None

    @pytest.mark.asyncio
    @patch("handlers.callback_handler.get_user_now")
    @patch("handlers.callback_handler.safe_answer", new_callable=AsyncMock)
    async def test_food_again_exception_sends_error_with_keyboard(self, mock_answer, mock_now):
        """When food duplication throws, user must see an error message (not silence)."""
        from datetime import datetime as dt
        import pytz
        mock_now.return_value = dt(2026, 6, 15, 15, 0, tzinfo=pytz.timezone("Asia/Jerusalem"))

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.food_repo.get.return_value = FoodEntry(
            id="orig_id", telegram_user_id=123, date="15/06/2026",
            time="12:00", description="חזה עוף", calories=350,
            protein=45, within_window=True,
        )
        h.food_repo.add.side_effect = Exception("DB error")

        query = AsyncMock()
        query.data = "fagain_orig_id"
        query.message.chat_id = 12345
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.chat_data = {}

        await h.handle_food_again_callback(update, context)

        # Must send error to user (not silent)
        context.bot.send_message.assert_called_once()
        call_kwargs = context.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None
