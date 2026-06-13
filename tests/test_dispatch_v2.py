"""
test_dispatch_v2.py - Unit tests for the Router v2 dispatch layer.

Covers all untested handler wiring: _dispatch_v2, _handle_conversational,
_handle_opt_in, ConversationalService, and LoggerService.

These tests use mocked services (no LLM calls, no MongoDB). They verify
that the handler reads User model fields correctly, calls the right
services, and doesn't crash on None/missing fields.

Regression context: production crash on 2026-06-12 because
_handle_conversational accessed profile.age (doesn't exist - field is
birth_year). These tests prevent that class of bug.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Stub heavy imports only if not already loaded (same pattern as test_handlers.py)
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

from analyzer import (
    RouterClassification, TimedFoodAnalysisResult, TimedFoodGroup,
    FoodItem, MessageClassification,
)
from models.profile import User, EatingWindow, Targets, ToggleState, Toggles
from models.food import FoodEntry


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _make_profile(**kwargs):
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "eating_window": EatingWindow(start="08:00", end="20:00"),
        "targets": Targets(calories=2000, protein=150),
        "timezone": "Asia/Jerusalem",
    }
    defaults.update(kwargs)
    return User(**defaults)


def _make_handler(**overrides):
    from handlers.base import HealthHandlers
    h = HealthHandlers.__new__(HealthHandlers)
    h.user_repo = MagicMock()
    h.food_repo = MagicMock()
    h.feedback_repo = MagicMock()
    h.eating_day_svc = MagicMock()
    h.analyzer = MagicMock()
    h.message_router = MagicMock()
    h.toggle_service = MagicMock()
    h.trial_service = None
    h.goal_service = MagicMock()
    h.feedback_service = MagicMock()
    h.onboarding_service = MagicMock()
    h.emotional_support_service = MagicMock()
    h.conversational_service = MagicMock()
    h.token_log_repo = None
    h.landing_page_url = "https://test.com"
    h.admin_chat_id = 0
    h._debug_mode = False
    for k, v in overrides.items():
        setattr(h, k, v)
    return h


def _make_message(text="test"):
    msg = AsyncMock()
    msg.text = text
    msg.reply_to_message = None
    return msg


def _make_context():
    ctx = MagicMock()
    ctx.chat_data = {}
    return ctx


def _make_router_result(rtype, **kwargs):
    return RouterClassification(type=rtype, **kwargs)


# Standard params for _dispatch_v2
_DISPATCH_PARAMS = dict(
    calendar_today="13/06/2026",
    day_name="שישי",
    stats_date="13/06/2026",
    time_str="14:00",
    within_window=True,
    last_entry=None,
    recent_messages=[],
    toggle_state="- תזונה: active\n- שינה: dormant",
    reply_context=None,
)


# ---------------------------------------------------------------------------
# Class 1: TestDispatchV2Routing
# ---------------------------------------------------------------------------

class TestDispatchV2Routing:
    """Verify each router type branch calls the correct service."""

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_opt_in(self, mock_send):
        h = _make_handler()
        h._handle_opt_in = AsyncMock()
        profile = _make_profile()
        rr = _make_router_result("opt_in", toggle_name="sleep")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h._handle_opt_in.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_conversational(self, mock_send):
        h = _make_handler()
        h._handle_conversational = AsyncMock()
        profile = _make_profile()
        rr = _make_router_result("conversational")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h._handle_conversational.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_inappropriate(self, mock_send):
        h = _make_handler()
        profile = _make_profile()
        rr = _make_router_result("inappropriate")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "הרגלי בריאות" in sent_text

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_correction_with_last_entry(self, mock_send):
        from analyzer import CorrectionResult, CorrectionFoodItem
        h = _make_handler()
        h._handle_correction = AsyncMock()
        profile = _make_profile()
        rr = _make_router_result("correction")
        last_entry = {"description": "שניצל", "calories": 650, "protein": 35, "entry_id": "abc"}
        correction = CorrectionResult(
            items=[CorrectionFoodItem(description="שניצל 300g", estimated_grams=300, calories=750, protein=45)],
            corrected_description="שניצל 300g",
            corrected_calories=750,
            corrected_protein=45,
        )
        h.analyzer.classify_message.return_value = MessageClassification(
            type="correction", correction=correction,
        )

        params = {**_DISPATCH_PARAMS, "last_entry": last_entry}
        await h._dispatch_v2(
            _make_message("השניצל היה 300 גרם"), _make_context(), 123, profile, rr, **params,
        )
        h._handle_correction.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_sleep(self, mock_send):
        h = _make_handler()
        h.message_router.route_sleep.return_value = MagicMock(response_text="שינה נרשמה")
        profile = _make_profile()
        rr = _make_router_result("sleep")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.message_router.route_sleep.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_workout(self, mock_send):
        h = _make_handler()
        h.message_router.route_workout.return_value = MagicMock(response_text="אימון נרשם")
        profile = _make_profile()
        rr = _make_router_result("workout")

        await h._dispatch_v2(
            _make_message("התאמנתי"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.message_router.route_workout.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_self_care(self, mock_send):
        h = _make_handler()
        h.message_router.route_self_care.return_value = MagicMock(response_text="נרשם")
        profile = _make_profile()
        rr = _make_router_result("self_care")

        await h._dispatch_v2(
            _make_message("הלכתי לים"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.message_router.route_self_care.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_name_declaration(self, mock_send):
        h = _make_handler()
        h.onboarding_service.handle_name_response.return_value = "שלום דני!"
        h.user_repo.get_recent_messages.return_value = []
        profile = _make_profile()
        rr = _make_router_result("name_declaration")

        await h._dispatch_v2(
            _make_message("קוראים לי דני"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.onboarding_service.handle_name_response.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.make_main_menu_keyboard", return_value="kb")
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_feedback_request(self, mock_send, _kb):
        h = _make_handler()
        h.feedback_service.is_first_feedback.return_value = False
        h.feedback_service.give_feedback.return_value = "הסיכום שלך"
        profile = _make_profile()
        rr = _make_router_result("feedback_request")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.feedback_service.give_feedback.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_feedback_reaction(self, mock_send):
        h = _make_handler()
        h.feedback_service.process_reaction.return_value = "תודה על הפידבק"
        profile = _make_profile()
        rr = _make_router_result("feedback_reaction")

        await h._dispatch_v2(
            _make_message("מעניין, תודה"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.feedback_service.process_reaction.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.make_emotional_support_keyboard", return_value="kb")
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_emotional(self, mock_send, _kb):
        h = _make_handler()
        h.emotional_support_service.get_empathy_response.return_value = "אני פה"
        h.analyzer.converse.return_value = "נשמע שקשה לך"
        profile = _make_profile()
        rr = _make_router_result("emotional")

        await h._dispatch_v2(
            _make_message("אני מרגיש רע"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "אני פה" in sent_text

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_meal_with_inline_data(self, mock_send, mock_react, _kb):
        h = _make_handler()
        h.eating_day_svc.get_eating_day_totals.return_value = (500, 30)
        h.food_repo.add.side_effect = lambda e: setattr(e, "id", "test_id") or e
        h.food_repo.get_all_for_user.return_value = [MagicMock(), MagicMock()]
        profile = _make_profile()
        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="עכשיו", date="13/06/2026", time="14:00",
                items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
                total_calories=400, total_protein=30,
            ),
        ])
        rr = _make_router_result("meal", meal=timed)

        await h._dispatch_v2(
            _make_message("אכלתי שניצל"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.food_repo.add.assert_called_once()
        # Should NOT call analyze_food_text since meal data was inline
        h.analyzer.analyze_food_text.assert_not_called()

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_meal_without_inline_falls_back(self, mock_send, mock_react, _kb):
        h = _make_handler()
        h.eating_day_svc.get_eating_day_totals.return_value = (500, 30)
        h.food_repo.add.side_effect = lambda e: setattr(e, "id", "test_id") or e
        h.food_repo.get_all_for_user.return_value = [MagicMock(), MagicMock()]
        timed = TimedFoodAnalysisResult(groups=[
            TimedFoodGroup(
                temporal_label="עכשיו", date="13/06/2026", time="14:00",
                items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
                total_calories=400, total_protein=30,
            ),
        ])
        h.analyzer.analyze_food_text.return_value = timed
        profile = _make_profile()
        rr = _make_router_result("meal")  # No inline meal data

        await h._dispatch_v2(
            _make_message("אכלתי שניצל"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.analyzer.analyze_food_text.assert_called_once()


# ---------------------------------------------------------------------------
# Class 2: TestDispatchV2NoneGuards
# ---------------------------------------------------------------------------

class TestDispatchV2NoneGuards:
    """Missing optional services don't crash."""

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_sleep_without_message_router(self, mock_send, mock_react, _kb):
        h = _make_handler(message_router=None)
        h.analyzer.analyze_food_text.return_value = None
        profile = _make_profile()
        rr = _make_router_result("sleep")

        # Should fall through to meal default and send fallback
        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        # No crash is the assertion

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_workout_without_message_router(self, mock_send, mock_react, _kb):
        h = _make_handler(message_router=None)
        h.analyzer.analyze_food_text.return_value = None
        profile = _make_profile()
        rr = _make_router_result("workout")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_self_care_without_message_router(self, mock_send, mock_react, _kb):
        h = _make_handler(message_router=None)
        h.analyzer.analyze_food_text.return_value = None
        profile = _make_profile()
        rr = _make_router_result("self_care")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_name_without_onboarding_service(self, mock_send, mock_react, _kb):
        h = _make_handler(onboarding_service=None)
        h.analyzer.analyze_food_text.return_value = None
        profile = _make_profile()
        rr = _make_router_result("name_declaration")

        await h._dispatch_v2(
            _make_message("דני"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_feedback_request_without_service(self, mock_send):
        h = _make_handler(feedback_service=None, message_router=None)
        profile = _make_profile()
        rr = _make_router_result("feedback_request")

        # Should return silently, no crash
        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_feedback_reaction_without_service(self, mock_send):
        h = _make_handler(feedback_service=None)
        profile = _make_profile()
        rr = _make_router_result("feedback_reaction")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

    @pytest.mark.asyncio
    @patch("handlers.base.make_food_entry_keyboard", return_value="kb")
    @patch("handlers.base.safe_react", new_callable=AsyncMock)
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_emotional_without_service(self, mock_send, mock_react, _kb):
        h = _make_handler(emotional_support_service=None)
        h.analyzer.analyze_food_text.return_value = None
        profile = _make_profile()
        rr = _make_router_result("emotional")

        await h._dispatch_v2(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )


# ---------------------------------------------------------------------------
# Class 3: TestHandleConversational
# ---------------------------------------------------------------------------

class TestHandleConversational:
    """Test user_context construction and service delegation.

    This class prevents the production crash where profile.age was accessed
    instead of profile.birth_year.
    """

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_full_profile_builds_complete_context(self, mock_send):
        h = _make_handler()
        h.conversational_service.respond.return_value = "תשובה"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (1200, 80)
        profile = _make_profile(
            name="דני", birth_year=1990, height_cm=175.0, weight_kg=80.0,
        )

        await h._handle_conversational(
            _make_message("שאלה"), 123, profile, "toggle_state", [],
        )

        call_kwargs = h.conversational_service.respond.call_args
        user_context = call_kwargs.kwargs.get("user_context") or call_kwargs[1].get("user_context")
        assert "דני" in user_context
        assert "175" in user_context
        assert "80" in user_context
        assert "גיל" in user_context
        assert "2000" in user_context  # target calories

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_minimal_profile_all_none(self, mock_send):
        h = _make_handler()
        h.conversational_service.respond.return_value = "תשובה"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile()  # No name, no birth_year, no height/weight

        await h._handle_conversational(
            _make_message("שאלה"), 123, profile, "toggle_state", [],
        )

        call_kwargs = h.conversational_service.respond.call_args
        user_context = call_kwargs.kwargs.get("user_context") or call_kwargs[1].get("user_context")
        # Only targets should be present (from Targets defaults)
        assert "דני" not in user_context
        assert "גיל" not in user_context

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_birth_year_to_age_calculation(self, mock_send):
        """REGRESSION TEST: production crashed on profile.age (doesn't exist)."""
        h = _make_handler()
        h.conversational_service.respond.return_value = "תשובה"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile(birth_year=2000)

        await h._handle_conversational(
            _make_message("שאלה"), 123, profile, "toggle_state", [],
        )

        call_kwargs = h.conversational_service.respond.call_args
        user_context = call_kwargs.kwargs.get("user_context") or call_kwargs[1].get("user_context")
        # 2026 - 2000 = 26
        assert "26" in user_context

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_birth_year_none_skips_age(self, mock_send):
        h = _make_handler()
        h.conversational_service.respond.return_value = "תשובה"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile(birth_year=None)

        await h._handle_conversational(
            _make_message("שאלה"), 123, profile, "toggle_state", [],
        )

        call_kwargs = h.conversational_service.respond.call_args
        user_context = call_kwargs.kwargs.get("user_context") or call_kwargs[1].get("user_context")
        assert "גיל" not in user_context

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_conversational_service_none_sends_fallback(self, mock_send):
        h = _make_handler(conversational_service=None)
        profile = _make_profile()

        await h._handle_conversational(
            _make_message("שאלה"), 123, profile, "toggle_state", [],
        )

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "מה נשמע" in sent_text

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_toggle_state_none_passes_empty_string(self, mock_send):
        h = _make_handler()
        h.conversational_service.respond.return_value = "תשובה"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile()

        await h._handle_conversational(
            _make_message("שאלה"), 123, profile, None, [],
        )

        call_kwargs = h.conversational_service.respond.call_args
        toggle_state = call_kwargs.kwargs.get("toggle_state") or call_kwargs[1].get("toggle_state")
        assert toggle_state == ""

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_data_summary_includes_daily_totals(self, mock_send):
        h = _make_handler()
        h.conversational_service.respond.return_value = "תשובה"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (1500, 95)
        profile = _make_profile()

        await h._handle_conversational(
            _make_message("כמה אכלתי?"), 123, profile, "", [],
        )

        call_kwargs = h.conversational_service.respond.call_args
        data_summary = call_kwargs.kwargs.get("data_summary") or call_kwargs[1].get("data_summary")
        assert "1500" in data_summary
        assert "95" in data_summary


# ---------------------------------------------------------------------------
# Class 4: TestHandleOptIn
# ---------------------------------------------------------------------------

class TestHandleOptIn:
    """Test toggle state routing in _handle_opt_in."""

    def _make_toggle(self, **kwargs):
        return ToggleState(**kwargs)

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_toggle_offered_delegates_to_conversation_reply(self, mock_send):
        h = _make_handler()
        h._handle_conversation_reply = AsyncMock()
        toggles = Toggles(sleep=self._make_toggle(
            status="dormant", revealed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        ))
        profile = _make_profile(toggles=toggles)
        rr = _make_router_result("opt_in", toggle_name="sleep")

        await h._handle_opt_in(
            _make_message("יאללה"), _make_context(), 123, profile, rr,
        )
        h._handle_conversation_reply.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_toggle_goal_pending_delegates_to_conversation_reply(self, mock_send):
        h = _make_handler()
        h._handle_conversation_reply = AsyncMock()
        toggles = Toggles(nutrition=self._make_toggle(
            status="active", goal_status="pending",
            goal_offered_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        ))
        profile = _make_profile(toggles=toggles)
        rr = _make_router_result("opt_in", toggle_name="nutrition")

        await h._handle_opt_in(
            _make_message("2000 קלוריות"), _make_context(), 123, profile, rr,
        )
        h._handle_conversation_reply.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_toggle_remind_pending_delegates_to_conversation_reply(self, mock_send):
        h = _make_handler()
        h._handle_conversation_reply = AsyncMock()
        toggles = Toggles(sleep=self._make_toggle(
            status="dormant", goal_status="remind_pending",
        ))
        profile = _make_profile(toggles=toggles)
        rr = _make_router_result("opt_in", toggle_name="sleep")

        await h._handle_opt_in(
            _make_message("כן"), _make_context(), 123, profile, rr,
        )
        h._handle_conversation_reply.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dormant_user_initiated_activates_toggle(self, mock_send):
        h = _make_handler()
        h.goal_service.should_offer_goal.return_value = False
        profile = _make_profile()  # All toggles dormant, no revealed_at
        rr = _make_router_result("opt_in", toggle_name="sleep")

        await h._handle_opt_in(
            _make_message("אני רוצה לעקוב"), _make_context(), 123, profile, rr,
        )
        h.toggle_service.activate_toggle.assert_called_once_with(123, "sleep")

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_cancelled_user_initiated_activates_toggle(self, mock_send):
        h = _make_handler()
        h.goal_service.should_offer_goal.return_value = False
        toggles = Toggles(workouts=self._make_toggle(status="cancelled"))
        profile = _make_profile(toggles=toggles)
        rr = _make_router_result("opt_in", toggle_name="workouts")

        await h._handle_opt_in(
            _make_message("אני רוצה לעקוב"), _make_context(), 123, profile, rr,
        )
        h.toggle_service.activate_toggle.assert_called_once_with(123, "workouts")

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_active_goal_set_calls_handle_goal_update(self, mock_send):
        h = _make_handler()
        h.goal_service.handle_goal_update.return_value = "יעד עודכן"
        toggles = Toggles(nutrition=self._make_toggle(
            status="active", goal_status="set", goal_value={"calories": 2000},
        ))
        profile = _make_profile(toggles=toggles)
        rr = _make_router_result("opt_in", toggle_name="nutrition")

        await h._handle_opt_in(
            _make_message("תשנה ל-2500"), _make_context(), 123, profile, rr,
        )
        h.goal_service.handle_goal_update.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_toggle_name_from_router_result(self, mock_send):
        """Router-provided toggle_name is used directly."""
        h = _make_handler()
        h._handle_conversation_reply = AsyncMock()
        toggles = Toggles(
            sleep=self._make_toggle(
                status="dormant",
                revealed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            ),
            workouts=self._make_toggle(
                status="dormant",
                revealed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            ),
        )
        profile = _make_profile(toggles=toggles)
        # Router says workouts, even though sleep is also offered
        rr = _make_router_result("opt_in", toggle_name="workouts")

        await h._handle_opt_in(
            _make_message("יאללה"), _make_context(), 123, profile, rr,
        )
        h._handle_conversation_reply.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_toggle_name_inferred_from_flow(self, mock_send):
        """When router_result.toggle_name is None, infer from toggle in flow."""
        h = _make_handler()
        h._handle_conversation_reply = AsyncMock()
        toggles = Toggles(sleep=self._make_toggle(
            status="dormant",
            revealed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        ))
        profile = _make_profile(toggles=toggles)
        rr = _make_router_result("opt_in")  # No toggle_name

        await h._handle_opt_in(
            _make_message("יאללה"), _make_context(), 123, profile, rr,
        )
        h._handle_conversation_reply.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_no_toggle_in_flow_fallback(self, mock_send):
        """No toggle in flow and no toggle_name -> fallback to conversation_reply."""
        h = _make_handler()
        h._handle_conversation_reply = AsyncMock()
        profile = _make_profile()  # All toggles dormant, no revealed_at
        rr = _make_router_result("opt_in")  # No toggle_name

        await h._handle_opt_in(
            _make_message("יאללה"), _make_context(), 123, profile, rr,
        )
        h._handle_conversation_reply.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_activate_offers_goal_when_should_offer(self, mock_send):
        h = _make_handler()
        h.goal_service.should_offer_goal.return_value = True
        h.goal_service.offer_goal_with_shortcut.return_value = "מה היעד שלך?"
        profile = _make_profile()
        rr = _make_router_result("opt_in", toggle_name="sleep")

        await h._handle_opt_in(
            _make_message("אני רוצה לעקוב"), _make_context(), 123, profile, rr,
        )
        h.toggle_service.activate_toggle.assert_called_once()
        h.goal_service.offer_goal_with_shortcut.assert_called_once()


# ---------------------------------------------------------------------------
# Class 5: TestConversationalService
# ---------------------------------------------------------------------------

class TestConversationalService:
    """Unit test ConversationalService (no LLM)."""

    def test_respond_happy_path(self):
        from services.conversational_service import ConversationalService
        analyzer = MagicMock()
        analyzer.converse.return_value = "תשובה חכמה"
        svc = ConversationalService(analyzer)

        result = svc.respond(
            user_text="שאלה",
            user_context="שם: דני",
            data_summary="היום: 500 קל",
            toggle_state="",
        )
        assert result == "תשובה חכמה"
        analyzer.converse.assert_called_once()

    def test_respond_exception_returns_fallback(self):
        from services.conversational_service import ConversationalService
        analyzer = MagicMock()
        analyzer.converse.side_effect = Exception("API error")
        svc = ConversationalService(analyzer)

        result = svc.respond(
            user_text="שאלה",
            user_context="",
            data_summary="",
            toggle_state="",
        )
        assert "לא הצלחתי" in result

    def test_respond_builds_messages_with_history(self):
        from services.conversational_service import ConversationalService
        analyzer = MagicMock()
        analyzer.converse.return_value = "ok"
        svc = ConversationalService(analyzer)

        svc.respond(
            user_text="שאלה",
            user_context="",
            data_summary="",
            toggle_state="",
            recent_messages=[
                {"role": "bot", "text": "הי"},
                {"role": "user", "text": "שלום"},
            ],
        )

        messages = analyzer.converse.call_args[0][0]
        # system + bot(assistant) + user(history) + user(current)
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "assistant"  # bot mapped to assistant
        assert messages[1]["content"] == "הי"
        assert messages[2]["role"] == "user"
        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == "שאלה"

    def test_system_prompt_includes_user_context(self):
        from services.conversational_service import ConversationalService
        analyzer = MagicMock()
        analyzer.converse.return_value = "ok"
        svc = ConversationalService(analyzer)

        svc.respond(
            user_text="test",
            user_context="שם: דני, גיל: 30",
            data_summary="היום: 1000 קל",
            toggle_state="שינה: active",
        )

        messages = analyzer.converse.call_args[0][0]
        system_prompt = messages[0]["content"]
        assert "שם: דני, גיל: 30" in system_prompt
        assert "היום: 1000 קל" in system_prompt
        assert "שינה: active" in system_prompt


# ---------------------------------------------------------------------------
# Class 6: TestLoggerService
# ---------------------------------------------------------------------------

class TestLoggerService:
    """Unit test LoggerService extraction methods."""

    def test_extract_name_strips_prefix_korim_li(self):
        from services.logger_service import LoggerService
        svc = LoggerService(MagicMock())
        result = svc.extract_name("קוראים לי דני")
        assert result.declared_name == "דני"

    def test_extract_name_strips_prefix_hashem_sheli(self):
        from services.logger_service import LoggerService
        svc = LoggerService(MagicMock())
        result = svc.extract_name("השם שלי יוסי")
        assert result.declared_name == "יוסי"

    def test_extract_name_no_prefix(self):
        from services.logger_service import LoggerService
        svc = LoggerService(MagicMock())
        result = svc.extract_name("דני")
        assert result.declared_name == "דני"

    def test_generate_empathy_happy_path(self):
        from services.logger_service import LoggerService
        analyzer = MagicMock()
        analyzer.converse.return_value = "נשמע שקשה לך היום"
        svc = LoggerService(analyzer)

        result = svc.generate_empathy("אני מרגיש רע")
        assert result.empathy_reflection == "נשמע שקשה לך היום"

    def test_generate_empathy_exception_fallback(self):
        from services.logger_service import LoggerService
        analyzer = MagicMock()
        analyzer.converse.side_effect = Exception("fail")
        svc = LoggerService(analyzer)

        result = svc.generate_empathy("אני מרגיש רע")
        assert result.empathy_reflection == "נשמע שקשה לך."


# ---------------------------------------------------------------------------
# Class 7: TestDispatchV2NameDeclaration
# ---------------------------------------------------------------------------

class TestDispatchV2NameDeclaration:
    """Test name extraction and onboarding delegation in _dispatch_v2."""

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_name_strips_prefix_and_calls_onboarding(self, mock_send):
        h = _make_handler()
        h.onboarding_service.handle_name_response.return_value = "שלום דני!"
        h.user_repo.get_recent_messages.return_value = [
            {"role": "bot", "text": "היי! איך אתה רוצה שאקרא לך?"},
        ]
        profile = _make_profile()
        rr = _make_router_result("name_declaration")

        await h._dispatch_v2(
            _make_message("קוראים לי דני"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

        call_args = h.onboarding_service.handle_name_response.call_args
        name_arg = call_args[0][1]  # (tid, name, ...)
        assert name_arg == "דני"

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_name_late_detection(self, mock_send):
        h = _make_handler()
        h.onboarding_service.handle_name_response.return_value = "שלום!"
        # Last bot message is NOT the name prompt -> late=True
        h.user_repo.get_recent_messages.return_value = [
            {"role": "bot", "text": "מה אכלת היום?"},
        ]
        profile = _make_profile()
        rr = _make_router_result("name_declaration")

        await h._dispatch_v2(
            _make_message("דני"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

        call_kwargs = h.onboarding_service.handle_name_response.call_args
        assert call_kwargs.kwargs.get("late") is True or call_kwargs[1].get("late") is True
