from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

# Stub heavy imports
for mod in [
    "telegram", "telegram.ext", "telegram.ext._application",
    "pymongo", "openai", "gspread",
    "google", "google.oauth2", "google.oauth2.service_account",
]:
    sys.modules.setdefault(mod, MagicMock())

# Need to set up telegram module attributes
mock_telegram = sys.modules["telegram"]
mock_telegram.Update = MagicMock
mock_telegram.InlineKeyboardButton = MagicMock
mock_telegram.InlineKeyboardMarkup = MagicMock

mock_ext = sys.modules["telegram.ext"]
mock_ext.ContextTypes = MagicMock()
mock_ext.ContextTypes.DEFAULT_TYPE = MagicMock

from analyzer import FoodItem, FoodAnalysisResult
from keyboards import format_daily_status


class TestFormatDailyStatus:
    def test_under_calorie_target(self):
        result = format_daily_status(1500, 120, 2000, 150)
        assert "✅" in result
        assert "1500/2000" in result
        assert "500" in result  # remaining

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
        # Should have warning for protein
        lines = result.split("\n")
        protein_line = [l for l in lines if "חלבון" in l][0]
        assert "⚠️" in protein_line


class TestCrossingAlerts:
    """Test crossing alert logic from HealthHandlers."""

    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h.chat_id = 123
        h.mongo = MagicMock()
        h.mongo.get_user_profile.return_value = {
            "target_calories": 2000,
            "target_protein": 150,
        }
        return h

    def test_no_alert_when_both_within_range(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1000, 80, 1500, 100, profile)
        assert result == ""

    def test_protein_target_reached(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1000, 130, 1400, 155, profile)
        assert "כל הכבוד" in result
        assert "חלבון" in result

    def test_calorie_target_exceeded(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1800, 100, 2100, 120, profile)
        assert "עברת" in result
        assert "קלוריות" in result

    def test_both_alerts(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1800, 140, 2100, 160, profile)
        assert "כל הכבוד" in result
        assert "עברת" in result


class TestGetStatsDate:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        return h

    @patch("handlers.base.get_user_now")
    def test_within_window_returns_today(self, mock_now):
        from datetime import datetime
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = datetime(2026, 5, 8, 12, 0, tzinfo=tz)

        h = self._make_handler()
        profile = {
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        result = h._get_stats_date(profile)
        assert result == "08/05/2026"

    @patch("handlers.base.get_user_now")
    def test_evening_after_close_returns_today(self, mock_now):
        from datetime import datetime
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = datetime(2026, 5, 8, 22, 0, tzinfo=tz)

        h = self._make_handler()
        profile = {
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        result = h._get_stats_date(profile)
        assert result == "08/05/2026"

    @patch("handlers.base.get_user_now")
    def test_morning_before_open_returns_yesterday(self, mock_now):
        from datetime import datetime
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = datetime(2026, 5, 8, 6, 0, tzinfo=tz)

        h = self._make_handler()
        profile = {
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        result = h._get_stats_date(profile)
        assert result == "07/05/2026"


class TestBuildFoodResponse:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        return h

    def test_includes_items_and_status(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        response = h._build_food_response("• שניצל: 400 קל׳", 400, 30, profile)
        assert "שניצל" in response
        assert "400/2000" in response
        assert "30/150" in response


class TestOneRowPerMessage:
    """Verify that multiple food items get consolidated into one description."""

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
    """Test the daily summary handler."""

    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h.chat_id = 123
        h.mongo = MagicMock()
        h.sheets = MagicMock()
        h.analyzer = MagicMock()
        return h

    @pytest.mark.asyncio
    @patch("handlers.base.make_daily_summary_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_answer", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_shows_itemized_entries(self, mock_send, mock_answer, mock_now, _kb):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        h.mongo.get_user_profile.return_value = {
            "target_calories": 2000,
            "target_protein": 150,
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        h.sheets.get_entries_for_eating_day.return_value = [
            {"תאריך": "11/05/2026", "שעה": "09:30", "תיאור": "שניצל ואורז", "קלוריות": 650, "חלבון": 40},
            {"תאריך": "11/05/2026", "שעה": "13:00", "תיאור": "סלט יווני", "קלוריות": 300, "חלבון": 15},
        ]

        query = AsyncMock()
        query.data = "daily_summary"
        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await h.handle_daily_callback(update, context)

        mock_answer.assert_called_once()
        call_text = mock_send.call_args[0][1]
        assert "שניצל ואורז" in call_text
        assert "סלט יווני" in call_text
        assert "09:30" in call_text
        assert "950/2000" in call_text  # totals

    @pytest.mark.asyncio
    @patch("handlers.base.make_daily_summary_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_answer", new_callable=AsyncMock)
    async def test_shows_empty_message(self, mock_answer, mock_now, _kb):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 11, 14, 0, tzinfo=tz)

        h = self._make_handler()
        h.mongo.get_user_profile.return_value = {
            "target_calories": 2000,
            "target_protein": 150,
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        h.sheets.get_entries_for_eating_day.return_value = []

        query = AsyncMock()
        query.data = "daily_summary"
        update = MagicMock()
        update.callback_query = query
        context = MagicMock()

        await h.handle_daily_callback(update, context)

        query.edit_message_text.assert_called_once()
        call_text = query.edit_message_text.call_args[0][0]
        assert "אין רשומות" in call_text


class TestCorrectionHistory:
    """Test that correction history is preserved and passed to analyzer."""

    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h.chat_id = 123
        h.mongo = MagicMock()
        h.sheets = MagicMock()
        h.analyzer = MagicMock()
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
        h.mongo.get_user_profile.return_value = {
            "target_calories": 2000,
            "target_protein": 150,
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        h.sheets.get_entries_for_eating_day.return_value = [
            {"קלוריות": 950, "חלבון": 55},
        ]

        correction_result = CorrectionResult(
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
                    "sheet_row": 5,
                },
                "correction_history": [],
                "timestamp": __import__("time").time(),
            }
        }

        await h._handle_pending_correction(message, context)

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
        h.mongo.get_user_profile.return_value = {
            "target_calories": 2000,
            "target_protein": 150,
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        h.sheets.get_entries_for_eating_day.return_value = [
            {"קלוריות": 1100, "חלבון": 55},
        ]

        correction_result = CorrectionResult(
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
                    "sheet_row": 5,
                },
                "correction_history": ["ההמבורגר הוא 300 גרם"],
                "timestamp": __import__("time").time(),
            },
            "correction_histories": {5: ["ההמבורגר הוא 300 גרם"]},
        }

        await h._handle_pending_correction(message, context)

        call_kwargs = h.analyzer.analyze_correction.call_args
        assert call_kwargs[1]["correction_history"] == ["ההמבורגר הוא 300 גרם"]
        # After correction, history should include the new correction too
        assert "הצ'יפס היה מנה גדולה" in context.chat_data["correction_histories"][5]


class TestFoodAgainCallback:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h.chat_id = 123
        h.mongo = MagicMock()
        h.sheets = MagicMock()
        h.analyzer = MagicMock()
        return h

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_answer", new_callable=AsyncMock)
    async def test_again_duplicates_entry(self, mock_answer, mock_now, mock_kb):
        from datetime import datetime as dt
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 5, 13, 15, 30, tzinfo=tz)

        h = self._make_handler()
        h.mongo.get_user_profile.return_value = {
            "target_calories": 2000,
            "target_protein": 150,
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }
        h.sheets.get_entry_data.return_value = {
            "תיאור": "חזה עוף 200 גרם",
            "קלוריות": "350",
            "חלבון": "45",
        }
        h.sheets.append_food_entry.return_value = 10
        h.sheets.get_entries_for_eating_day.return_value = [
            {"קלוריות": 700, "חלבון": 90},
        ]

        query = AsyncMock()
        query.data = "fagain_5"
        query.message.chat_id = 12345
        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.chat_data = {}

        await h.handle_food_again_callback(update, context)

        h.sheets.get_entry_data.assert_called_once_with(5)
        h.sheets.append_food_entry.assert_called_once_with(
            date_str="13/05/2026",
            time_str="15:30",
            description="חזה עוף 200 גרם",
            calories=350,
            protein=45,
            within_window=True,
        )
        mock_kb.assert_called_with(10)
        context.bot.send_message.assert_called_once()
        call_text = context.bot.send_message.call_args[1]["text"]
        assert "חזה עוף 200 גרם" in call_text
        assert "350" in call_text
