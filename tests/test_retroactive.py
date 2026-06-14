"""Tests for retroactive food entry support (TDD - written before implementation)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Stub heavy imports (same pattern as test_handlers.py)
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

from analyzer import FoodItem, FoodAnalysisResult, RouterClassification
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


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestTimedFoodGroupModel:
    def test_create_timed_food_group(self):
        from analyzer import TimedFoodGroup
        group = TimedFoodGroup(
            temporal_label="אתמול בערב",
            date="04/06/2026",
            time="20:00",
            items=[FoodItem(description="שווארמה", estimated_grams=300, calories=600, protein=30)],
            total_calories=600,
            total_protein=30,
        )
        assert group.temporal_label == "אתמול בערב"
        assert group.date == "04/06/2026"
        assert group.time == "20:00"
        assert len(group.items) == 1
        assert group.total_calories == 600

    def test_create_timed_food_analysis_result(self):
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult
        group1 = TimedFoodGroup(
            temporal_label="אתמול בערב",
            date="04/06/2026",
            time="20:00",
            items=[FoodItem(description="שווארמה", estimated_grams=300, calories=600, protein=30)],
            total_calories=600,
            total_protein=30,
        )
        group2 = TimedFoodGroup(
            temporal_label="עכשיו",
            date="05/06/2026",
            time="13:00",
            items=[FoodItem(description="סלט", estimated_grams=200, calories=100, protein=5)],
            total_calories=100,
            total_protein=5,
        )
        result = TimedFoodAnalysisResult(groups=[group1, group2])
        assert len(result.groups) == 2
        assert result.groups[0].date == "04/06/2026"
        assert result.groups[1].date == "05/06/2026"

    def test_single_group_backward_compatible(self):
        """A message with no temporal markers should produce a single group."""
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult
        group = TimedFoodGroup(
            temporal_label="עכשיו",
            date="05/06/2026",
            time="13:00",
            items=[
                FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30),
                FoodItem(description="אורז", estimated_grams=150, calories=200, protein=5),
            ],
            total_calories=600,
            total_protein=35,
        )
        result = TimedFoodAnalysisResult(groups=[group])
        assert len(result.groups) == 1


class TestMessageClassificationWithTimedMeal:
    def test_classification_meal_field_accepts_timed_result(self):
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult, MessageClassification
        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="עכשיו",
                date="05/06/2026",
                time="13:00",
                items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
                total_calories=400,
                total_protein=30,
            ),
        ])
        mc = MessageClassification(type="meal", meal=timed)
        assert mc.type == "meal"
        assert mc.meal is not None
        assert len(mc.meal.groups) == 1


# ---------------------------------------------------------------------------
# Response formatting tests
# ---------------------------------------------------------------------------

class TestFormatGroupedItemsText:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        return h

    def test_single_group_today_no_label(self):
        """Single group for today should not show a temporal label."""
        from analyzer import TimedFoodGroup
        h = self._make_handler()
        groups = [TimedFoodGroup(
            temporal_label="עכשיו",
            date="05/06/2026",
            time="13:00",
            items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
            total_calories=400,
            total_protein=30,
        )]
        result = h._format_grouped_items_text(groups, "05/06/2026")
        assert "שניצל" in result
        assert "400 קל" in result
        # Single group for today - no temporal header
        assert "📅" not in result

    def test_multiple_groups_show_labels(self):
        """Multiple groups should show temporal labels for each."""
        from analyzer import TimedFoodGroup
        h = self._make_handler()
        groups = [
            TimedFoodGroup(
                temporal_label="אתמול בערב",
                date="04/06/2026",
                time="20:00",
                items=[FoodItem(description="שווארמה", estimated_grams=300, calories=600, protein=30)],
                total_calories=600,
                total_protein=30,
            ),
            TimedFoodGroup(
                temporal_label="עכשיו",
                date="05/06/2026",
                time="13:00",
                items=[FoodItem(description="סלט", estimated_grams=200, calories=100, protein=5)],
                total_calories=100,
                total_protein=5,
            ),
        ]
        result = h._format_grouped_items_text(groups, "05/06/2026")
        assert "📅 אתמול בערב:" in result
        assert "📅 עכשיו:" in result
        assert "שווארמה" in result
        assert "סלט" in result

    def test_retro_group_shows_label_even_if_single(self):
        """A single group for a past date should still show a label."""
        from analyzer import TimedFoodGroup
        h = self._make_handler()
        groups = [TimedFoodGroup(
            temporal_label="אתמול",
            date="04/06/2026",
            time="20:00",
            items=[FoodItem(description="פיצה", estimated_grams=250, calories=500, protein=20)],
            total_calories=500,
            total_protein=20,
        )]
        result = h._format_grouped_items_text(groups, "05/06/2026")
        assert "📅 אתמול:" in result
        assert "פיצה" in result

    def test_items_show_grams_and_macros(self):
        """Each item should show grams, calories, and protein."""
        from analyzer import TimedFoodGroup
        h = self._make_handler()
        groups = [TimedFoodGroup(
            temporal_label="עכשיו",
            date="05/06/2026",
            time="13:00",
            items=[FoodItem(description="חביתה", estimated_grams=120, calories=180, protein=12)],
            total_calories=180,
            total_protein=12,
        )]
        result = h._format_grouped_items_text(groups, "05/06/2026")
        assert "~120 גרם" in result
        assert "180 קל" in result
        assert "12 גרם חלבון" in result


# ---------------------------------------------------------------------------
# Handler multi-entry tests
# ---------------------------------------------------------------------------

class TestHandleMessageRetroactive:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h._debug_mode = False
        h.user_repo = MagicMock()
        h.food_repo = MagicMock()
        h.feedback_repo = MagicMock()
        h.eating_day_svc = MagicMock()
        h.analyzer = MagicMock()
        h.message_router = None
        h.toggle_service = None
        h.trial_service = None
        h.goal_service = None
        h.feedback_service = None
        h.onboarding_service = None
        h.emotional_support_service = None
        h.conversational_service = None
        h.token_log_repo = None
        h.re_engagement_service = None
        h.landing_page_url = "https://test.com"
        h.admin_chat_id = 0
        return h

    @staticmethod
    def _set_meal_classification(handler, timed):
        """Set both old and new classification mocks for a meal result."""
        from analyzer import MessageClassification
        handler.analyzer.classify_message.return_value = MessageClassification(type="meal", meal=timed)
        handler.analyzer.route_message.return_value = RouterClassification(type="meal", meal=timed)

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_multi_group_creates_multiple_entries(self, mock_send, mock_react, mock_now, _kb):
        """When GPT returns multiple groups, handler should create one FoodEntry per group."""
        from datetime import datetime as dt
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult, MessageClassification
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 5, 13, 45, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "05/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (100, 5)

        # Simulate classifier returning multi-group result
        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="אתמול בערב",
                date="04/06/2026",
                time="20:00",
                items=[FoodItem(description="שווארמה", estimated_grams=300, calories=600, protein=30)],
                total_calories=600,
                total_protein=30,
            ),
            TimedFoodGroup(
                temporal_label="עכשיו",
                date="05/06/2026",
                time="13:45",
                items=[FoodItem(description="סלט", estimated_grams=200, calories=100, protein=5)],
                total_calories=100,
                total_protein=5,
            ),
        ])
        self._set_meal_classification(h, timed)

        saved_entries = []
        def mock_add(entry):
            entry.id = f"id_{len(saved_entries)}"
            saved_entries.append(entry)
            return entry
        h.food_repo.add.side_effect = mock_add
        h.food_repo.get_all_for_user.return_value = [MagicMock(), MagicMock()]

        message = AsyncMock()
        message.text = "אתמול בערב שווארמה\nעכשיו סלט"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123
        context = MagicMock()
        context.chat_data = {}

        await h.handle_message(update, context)

        # Should create 2 entries
        assert h.food_repo.add.call_count == 2
        # First entry: yesterday
        first_entry = saved_entries[0]
        assert first_entry.date == "04/06/2026"
        assert first_entry.time == "20:00"
        assert first_entry.description == "שווארמה"
        # Second entry: today
        second_entry = saved_entries[1]
        assert second_entry.date == "05/06/2026"
        assert second_entry.time == "13:45"
        assert second_entry.description == "סלט"

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_daily_totals_exclude_retroactive_entries(self, mock_send, mock_react, mock_now, _kb):
        """Daily summary should reflect only today's entries, not retroactive ones."""
        from datetime import datetime as dt
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult, MessageClassification
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 5, 13, 45, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "05/06/2026"
        # Daily totals include today's existing (200 cal) + new today entry (100 cal) = 300
        h.eating_day_svc.get_eating_day_totals.return_value = (300, 15)

        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="אתמול",
                date="04/06/2026",
                time="20:00",
                items=[FoodItem(description="פיצה", estimated_grams=300, calories=800, protein=25)],
                total_calories=800,
                total_protein=25,
            ),
            TimedFoodGroup(
                temporal_label="עכשיו",
                date="05/06/2026",
                time="13:45",
                items=[FoodItem(description="סלט", estimated_grams=200, calories=100, protein=5)],
                total_calories=100,
                total_protein=5,
            ),
        ])
        self._set_meal_classification(h, timed)
        h.food_repo.add.side_effect = lambda e: setattr(e, 'id', 'test_id') or e
        h.food_repo.get_all_for_user.return_value = [MagicMock(), MagicMock()]

        message = AsyncMock()
        message.text = "אתמול פיצה\nעכשיו סלט"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123
        context = MagicMock()
        context.chat_data = {}

        await h.handle_message(update, context)

        # Daily totals should show 300 (today only), not 300+800=1100
        response_text = mock_send.call_args_list[0][0][1]
        assert "300/2000" in response_text
        # Should NOT include yesterday's 800 cal in daily summary
        assert "1100" not in response_text

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_all_retro_shows_confirmation_no_daily_summary(self, mock_send, mock_react, mock_now, _kb):
        """When all entries are retroactive, show confirmation instead of daily summary."""
        from datetime import datetime as dt
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult, MessageClassification
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 5, 13, 45, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "05/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)

        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="אתמול בערב",
                date="04/06/2026",
                time="20:00",
                items=[FoodItem(description="פיצה", estimated_grams=300, calories=800, protein=25)],
                total_calories=800,
                total_protein=25,
            ),
        ])
        self._set_meal_classification(h, timed)
        h.food_repo.add.side_effect = lambda e: setattr(e, 'id', 'test_id') or e
        h.food_repo.get_all_for_user.return_value = [MagicMock(), MagicMock()]

        message = AsyncMock()
        message.text = "אתמול בערב פיצה"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123
        context = MagicMock()
        context.chat_data = {}

        await h.handle_message(update, context)

        response_text = mock_send.call_args_list[0][0][1]
        # Should show confirmation
        assert "נרשם" in response_text
        # Should NOT show daily summary header (since no today entries)
        assert "סיכום יומי" not in response_text

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_single_group_today_backward_compatible(self, mock_send, mock_react, mock_now, _kb):
        """Single group for today should behave like the old flow."""
        from datetime import datetime as dt
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult, MessageClassification
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 5, 13, 45, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "05/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (400, 30)

        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="עכשיו",
                date="05/06/2026",
                time="13:45",
                items=[
                    FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30),
                ],
                total_calories=400,
                total_protein=30,
            ),
        ])
        self._set_meal_classification(h, timed)
        h.food_repo.add.side_effect = lambda e: setattr(e, 'id', 'test_id') or e
        h.food_repo.get_all_for_user.return_value = [MagicMock()]

        message = AsyncMock()
        message.text = "שניצל"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123
        context = MagicMock()
        context.chat_data = {}

        await h.handle_message(update, context)

        # Should create exactly 1 entry
        assert h.food_repo.add.call_count == 1
        entry = h.food_repo.add.call_args[0][0]
        assert entry.date == "05/06/2026"

        # Response should include daily summary (backward compat)
        response_text = mock_send.call_args_list[0][0][1]
        assert "סיכום יומי" in response_text
        assert "400/2000" in response_text
        # No temporal labels for single today group
        assert "📅" not in response_text

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.get_user_now")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_last_entry_stores_latest_group(self, mock_send, mock_react, mock_now, _kb):
        """last_entry in chat_data should be the chronologically latest entry."""
        from datetime import datetime as dt
        from analyzer import TimedFoodGroup, TimedFoodAnalysisResult, MessageClassification
        import pytz
        tz = pytz.timezone("Asia/Jerusalem")
        mock_now.return_value = dt(2026, 6, 5, 13, 45, tzinfo=tz)

        h = self._make_handler()
        profile = _make_profile()
        h.user_repo.get.return_value = profile
        h.eating_day_svc.get_stats_date.return_value = "05/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (100, 5)

        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="אתמול",
                date="04/06/2026",
                time="20:00",
                items=[FoodItem(description="פיצה", estimated_grams=300, calories=800, protein=25)],
                total_calories=800,
                total_protein=25,
            ),
            TimedFoodGroup(
                temporal_label="עכשיו",
                date="05/06/2026",
                time="13:45",
                items=[FoodItem(description="סלט", estimated_grams=200, calories=100, protein=5)],
                total_calories=100,
                total_protein=5,
            ),
        ])
        self._set_meal_classification(h, timed)

        entry_counter = [0]
        def mock_add(entry):
            entry.id = f"id_{entry_counter[0]}"
            entry_counter[0] += 1
            return entry
        h.food_repo.add.side_effect = mock_add
        h.food_repo.get_all_for_user.return_value = [MagicMock(), MagicMock()]

        message = AsyncMock()
        message.text = "אתמול פיצה\nעכשיו סלט"
        message.reply_to_message = None
        update = MagicMock()
        update.effective_message = message
        update.effective_user.id = 123
        context = MagicMock()
        context.chat_data = {}

        await h.handle_message(update, context)

        # last_entry should be the "now" entry (latest chronologically)
        last = context.chat_data["last_entry"]
        assert last["description"] == "סלט"
        assert last["entry_id"] == "id_1"


# ---------------------------------------------------------------------------
# Hebrew day name helper tests
# ---------------------------------------------------------------------------

class TestHebrewDayName:
    def test_sunday(self):
        from parsing import hebrew_day_name
        from datetime import datetime
        # 2026-06-07 is a Sunday
        dt = datetime(2026, 6, 7)
        assert hebrew_day_name(dt) == "ראשון"

    def test_saturday(self):
        from parsing import hebrew_day_name
        from datetime import datetime
        # 2026-06-06 is a Saturday
        dt = datetime(2026, 6, 6)
        assert hebrew_day_name(dt) == "שבת"

    def test_thursday(self):
        from parsing import hebrew_day_name
        from datetime import datetime
        # 2026-06-04 is a Thursday
        dt = datetime(2026, 6, 4)
        assert hebrew_day_name(dt) == "חמישי"
