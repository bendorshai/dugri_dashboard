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
mock_telegram.Update = MagicMock
mock_telegram.InlineKeyboardButton = MagicMock
mock_telegram.InlineKeyboardMarkup = MagicMock

mock_ext = sys.modules["telegram.ext"]
mock_ext.ContextTypes = MagicMock()
mock_ext.ContextTypes.DEFAULT_TYPE = MagicMock

from analyzer import FoodItem, FoodAnalysisResult, FoodPhotoResult
from keyboards import format_daily_status
from models.profile import UserProfile, EatingWindow, Targets
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
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
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
    @patch("handlers.base.safe_answer", new_callable=AsyncMock)
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
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
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
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "11/05/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (950, 55)

        correction_result = CorrectionResult(
            items=[
                FoodItem(description="המבורגר 300 גרם", estimated_grams=300, calories=750, protein=45),
                FoodItem(description="צ'יפס", estimated_grams=150, calories=150, protein=3),
                FoodItem(description="סלט", estimated_grams=200, calories=50, protein=7),
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
                FoodItem(description="המבורגר 300 גרם", estimated_grams=300, calories=750, protein=45),
                FoodItem(description="צ'יפס גדול", estimated_grams=250, calories=300, protein=4),
                FoodItem(description="סלט", estimated_grams=200, calories=50, protein=6),
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


class TestFoodAgainCallback:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        return h

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_answer", new_callable=AsyncMock)
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
