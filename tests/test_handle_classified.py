"""
test_handle_classified.py - Unit tests for the classified message handler.

Covers all untested handler wiring: _handle_classified, _handle_conversational,
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
    RouterClassification, MealResult, MealGroup,
    FoodItem,
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
    h.sleep_repo = MagicMock()
    h.workout_repo = MagicMock()
    h.self_care_repo = MagicMock()
    h.inappropriate_service = MagicMock()
    h.landing_page_url = "https://test.com"
    h.admin_chat_id = 0
    h._debug_mode = False
    h._current_classification = None
    for k, v in overrides.items():
        setattr(h, k, v)
    return h


def _make_message(text="test"):
    msg = AsyncMock()
    msg.text = text
    msg.message_id = 12345
    msg.reply_to_message = None
    return msg


def _make_context():
    ctx = MagicMock()
    ctx.chat_data = {}
    return ctx


def _make_router_result(rtype, **kwargs):
    return RouterClassification(type=rtype, **kwargs)


# Standard params for _handle_classified
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

        await h._handle_classified(
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

        await h._handle_classified(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h._handle_conversational.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_inappropriate_records_strike(self, mock_send):
        h = _make_handler()
        h.inappropriate_service.record_strike.return_value = {"action": "strike", "strike_number": 1}
        profile = _make_profile()
        rr = _make_router_result("inappropriate")

        await h._handle_classified(
            _make_message("לך תזדיין"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.inappropriate_service.record_strike.assert_called_once_with(123, "לך תזדיין", profile)
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "הרגלי בריאות" in sent_text

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_inappropriate_ban_sends_ban_message(self, mock_send):
        h = _make_handler()
        h.inappropriate_service.record_strike.return_value = {
            "action": "ban",
            "logs": [
                {"message_text": "msg1", "created_at": "2026-06-10"},
                {"message_text": "msg2", "created_at": "2026-06-11"},
                {"message_text": "msg3", "created_at": "2026-06-12"},
            ],
        }
        h.inappropriate_service.format_ban_message.return_value = "ban message with list"
        profile = _make_profile(gender="male")
        rr = _make_router_result("inappropriate")

        await h._handle_classified(
            _make_message("third offense"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.inappropriate_service.format_ban_message.assert_called_once()
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert sent_text == "ban message with list"

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
        h.analyzer.analyze_correction.return_value = correction

        params = {**_DISPATCH_PARAMS, "last_entry": last_entry}
        await h._handle_classified(
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

        await h._handle_classified(
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

        await h._handle_classified(
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

        await h._handle_classified(
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

        await h._handle_classified(
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

        await h._handle_classified(
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

        # Guardrail requires recent feedback in last 2 messages
        params = {**_DISPATCH_PARAMS, "recent_messages": [
            {"role": "bot", "text": "💬 הנה הסיכום השבועי שלך...", "classification": "feedback_request"},
            {"role": "user", "text": "מעניין, תודה"},
        ]}
        await h._handle_classified(
            _make_message("מעניין, תודה"), _make_context(), 123, profile, rr, **params,
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

        await h._handle_classified(
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
        timed = MealResult(groups=[
            MealGroup(
                temporal_label="עכשיו", date="13/06/2026", time="14:00",
                items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
                total_calories=400, total_protein=30,
            ),
        ])
        rr = _make_router_result("meal", meal=timed)

        await h._handle_classified(
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
        timed = MealResult(groups=[
            MealGroup(
                temporal_label="עכשיו", date="13/06/2026", time="14:00",
                items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
                total_calories=400, total_protein=30,
            ),
        ])
        h.analyzer.analyze_food_text.return_value = timed
        profile = _make_profile()
        rr = _make_router_result("meal")  # No inline meal data

        await h._handle_classified(
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
        await h._handle_classified(
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

        await h._handle_classified(
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

        await h._handle_classified(
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

        await h._handle_classified(
            _make_message("דני"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_feedback_request_without_service(self, mock_send):
        h = _make_handler(feedback_service=None, message_router=None)
        profile = _make_profile()
        rr = _make_router_result("feedback_request")

        # Should return silently, no crash
        await h._handle_classified(
            _make_message(), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_feedback_reaction_without_service(self, mock_send):
        h = _make_handler(feedback_service=None)
        profile = _make_profile()
        rr = _make_router_result("feedback_reaction")

        await h._handle_classified(
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

        await h._handle_classified(
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
    async def test_fetch_history_passed_as_callable(self, mock_send):
        h = _make_handler()
        h.conversational_service.respond.return_value = "תשובה"
        profile = _make_profile()

        await h._handle_conversational(
            _make_message("כמה אכלתי?"), 123, profile, "", [],
            calendar_today="13/06/2026",
        )

        call_kwargs = h.conversational_service.respond.call_args
        fetch_history = call_kwargs.kwargs.get("fetch_history") or call_kwargs[1].get("fetch_history")
        assert callable(fetch_history)


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
            toggle_state="",
            today_date="13/06/2026",
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
            toggle_state="",
            today_date="13/06/2026",
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
            toggle_state="",
            today_date="13/06/2026",
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
            toggle_state="שינה: active",
            today_date="13/06/2026",
        )

        messages = analyzer.converse.call_args[0][0]
        system_prompt = messages[0]["content"]
        assert "שם: דני, גיל: 30" in system_prompt
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
    """Test name extraction and onboarding delegation in _handle_classified."""

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

        await h._handle_classified(
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

        await h._handle_classified(
            _make_message("דני"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )

        call_kwargs = h.onboarding_service.handle_name_response.call_args
        assert call_kwargs.kwargs.get("late") is True or call_kwargs[1].get("late") is True


# ---------------------------------------------------------------------------
# Class: TestGuardrailIntegration
# ---------------------------------------------------------------------------

class TestGuardrailIntegration:
    """Test guardrails integrated at the _handle_classified level."""

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_feedback_reaction_without_feedback_goes_conversational(self, mock_send):
        """feedback_reaction without recent feedback is redirected to conversational."""
        h = _make_handler()
        h.conversational_service.respond.return_value = "בכיף"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile()
        rr = _make_router_result("feedback_reaction")

        # No feedback in recent messages -> should route to conversational
        params = {**_DISPATCH_PARAMS, "recent_messages": [
            {"role": "bot", "text": "שווארמה ≈ 720 קל׳, 38 ג' חלבון", "classification": "meal"},
            {"role": "user", "text": "תודה דוגרי"},
        ]}
        await h._handle_classified(
            _make_message("תודה דוגרי"), _make_context(), 123, profile, rr, **params,
        )
        h.conversational_service.respond.assert_called_once()
        h.feedback_service.process_reaction.assert_not_called()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_without_last_entry_goes_conversational(self, mock_send):
        """correction without last_entry should NOT fall through to meal handler."""
        h = _make_handler()
        h.conversational_service.respond.return_value = "כדי לתקן, תגיב על ההודעה המקורית"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile()
        rr = _make_router_result("correction")

        # No correctable context and no last_entry -> conversational
        await h._handle_classified(
            _make_message("בלי אורז"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.conversational_service.respond.assert_called_once()
        h.analyzer.analyze_food_text.assert_not_called()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_name_declaration_blocked_when_name_set(self, mock_send):
        """name_declaration when name is already set -> goes to conversational."""
        h = _make_handler()
        h.conversational_service.respond.return_value = "אפשר לשנות שם באתר"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile(name="שי")
        rr = _make_router_result("name_declaration")

        await h._handle_classified(
            _make_message("קוראים לי דני"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.conversational_service.respond.assert_called_once()
        h.onboarding_service.handle_name_response.assert_not_called()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_gender_declaration_blocked_when_gender_set(self, mock_send):
        """gender_declaration when gender is already set -> goes to conversational."""
        h = _make_handler()
        h.conversational_service.respond.return_value = "אפשר לשנות מגדר באתר"
        h.eating_day_svc.resolve_eating_day.return_value = "13/06/2026"
        h.eating_day_svc.get_eating_day_totals.return_value = (0, 0)
        profile = _make_profile(gender="male")
        rr = _make_router_result("gender_declaration", declared_gender="female")

        await h._handle_classified(
            _make_message("אני בת"), _make_context(), 123, profile, rr, **_DISPATCH_PARAMS,
        )
        h.conversational_service.respond.assert_called_once()
        h.onboarding_service.handle_gender_response.assert_not_called()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_with_recent_meal_allowed(self, mock_send):
        """correction when meal was in last 2 messages -> allowed through guardrail."""
        h = _make_handler()
        last = {"entry_id": "abc", "description": "שווארמה", "calories": 720, "protein": 38}
        h.analyzer.analyze_correction.return_value = MagicMock()
        h._handle_correction = AsyncMock()
        profile = _make_profile()
        rr = _make_router_result("correction")

        params = {**_DISPATCH_PARAMS,
            "last_entry": last,
            "recent_messages": [
                {"role": "bot", "text": "שווארמה ≈ 720 קל׳, 38 ג' חלבון", "classification": "meal"},
                {"role": "user", "text": "בלי אורז"},
            ],
        }
        await h._handle_classified(
            _make_message("בלי אורז"), _make_context(), 123, profile, rr, **params,
        )
        h.analyzer.analyze_correction.assert_called_once()

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_correction_with_reply_context_allowed(self, mock_send):
        """correction via Telegram reply -> allowed even without recent meal in history."""
        h = _make_handler()
        last = {"entry_id": "abc", "description": "שווארמה", "calories": 720, "protein": 38}
        h.analyzer.analyze_correction.return_value = MagicMock()
        h._handle_correction = AsyncMock()
        profile = _make_profile()
        rr = _make_router_result("correction")

        params = {**_DISPATCH_PARAMS,
            "last_entry": last,
            "reply_context": "שווארמה ≈ 720 קל׳, 38 ג' חלבון",
            "recent_messages": [],  # empty history, but reply_context is set
        }
        await h._handle_classified(
            _make_message("בלי אורז"), _make_context(), 123, profile, rr, **params,
        )
        h.analyzer.analyze_correction.assert_called_once()


# ---------------------------------------------------------------------------
# Class: TestFindEntryByMessageId
# ---------------------------------------------------------------------------

class TestFindEntryByMessageId:
    """Test _find_entry_by_message_id which looks up entries across all collections."""

    def test_finds_food_by_bot_message_id(self):
        h = _make_handler()
        h.food_repo._collection.find_one.return_value = {
            "_id": "food123",
            "description": "שווארמה",
            "calories": 720,
            "protein": 38,
            "photo_file_id": None,
            "bot_message_id": 999,
        }

        result = h._find_entry_by_message_id(tid=123, message_id=999)
        assert result is not None
        assert result["entry_id"] == "food123"
        assert result["entry_type"] == "food"
        assert result["calories"] == 720

    def test_finds_food_by_user_message_id(self):
        h = _make_handler()
        h.food_repo._collection.find_one.return_value = {
            "_id": "food456",
            "description": "סלט",
            "calories": 200,
            "protein": 5,
            "user_message_id": 888,
        }

        result = h._find_entry_by_message_id(tid=123, message_id=888)
        assert result is not None
        assert result["entry_id"] == "food456"
        assert result["entry_type"] == "food"

    def test_finds_sleep_entry(self):
        h = _make_handler()
        h.food_repo._collection.find_one.return_value = None  # not food
        h.sleep_repo._collection.find_one.return_value = {
            "_id": "sleep789",
            "sleep_time": "23:00",
            "bot_message_id": 777,
        }

        result = h._find_entry_by_message_id(tid=123, message_id=777)
        assert result is not None
        assert result["entry_id"] == "sleep789"
        assert result["entry_type"] == "sleep"
        assert result["description"] == "23:00"

    def test_finds_workout_entry(self):
        h = _make_handler()
        h.food_repo._collection.find_one.return_value = None
        h.sleep_repo._collection.find_one.return_value = None
        h.workout_repo._collection.find_one.return_value = {
            "_id": "workout101",
            "note": "אימון ריצה",
            "bot_message_id": 666,
        }

        result = h._find_entry_by_message_id(tid=123, message_id=666)
        assert result is not None
        assert result["entry_id"] == "workout101"
        assert result["entry_type"] == "workout"
        assert result["description"] == "אימון ריצה"

    def test_finds_self_care_entry(self):
        h = _make_handler()
        h.food_repo._collection.find_one.return_value = None
        h.sleep_repo._collection.find_one.return_value = None
        h.workout_repo._collection.find_one.return_value = None
        h.self_care_repo._collection.find_one.return_value = {
            "_id": "sc202",
            "description": "הלכתי לים",
            "bot_message_id": 555,
        }

        result = h._find_entry_by_message_id(tid=123, message_id=555)
        assert result is not None
        assert result["entry_id"] == "sc202"
        assert result["entry_type"] == "self_care"
        assert result["description"] == "הלכתי לים"

    def test_returns_none_when_not_found(self):
        h = _make_handler()
        h.food_repo._collection.find_one.return_value = None
        h.sleep_repo._collection.find_one.return_value = None
        h.workout_repo._collection.find_one.return_value = None
        h.self_care_repo._collection.find_one.return_value = None

        result = h._find_entry_by_message_id(tid=123, message_id=999)
        assert result is None

    def test_returns_none_when_no_repos(self):
        h = _make_handler(food_repo=None, sleep_repo=None, workout_repo=None, self_care_repo=None)

        result = h._find_entry_by_message_id(tid=123, message_id=999)
        assert result is None

    def test_queries_with_correct_filter(self):
        """Verify the MongoDB query uses $or for both user_message_id and bot_message_id."""
        h = _make_handler()
        h.food_repo._collection.find_one.return_value = None
        h.sleep_repo._collection.find_one.return_value = None
        h.workout_repo._collection.find_one.return_value = None
        h.self_care_repo._collection.find_one.return_value = None

        h._find_entry_by_message_id(tid=123, message_id=999)

        query = h.food_repo._collection.find_one.call_args[0][0]
        assert query["telegram_user_id"] == 123
        assert "$or" in query
        assert {"user_message_id": 999} in query["$or"]
        assert {"bot_message_id": 999} in query["$or"]


# ---------------------------------------------------------------------------
# Class: TestStoreMessageIds
# ---------------------------------------------------------------------------

class TestStoreMessageIds:
    """Test _store_message_ids stores Telegram message IDs on entries."""

    def test_stores_both_ids(self):
        from bson import ObjectId
        h = _make_handler()
        h._store_message_ids(h.food_repo, "abc123abc123abc123abc123", 111, 222)
        h.food_repo.update_by_id.assert_called_once()
        call_args = h.food_repo.update_by_id.call_args
        assert call_args[0][1] == {"user_message_id": 111, "bot_message_id": 222}

    def test_stores_only_user_id_when_bot_is_none(self):
        h = _make_handler()
        h._store_message_ids(h.food_repo, "abc123abc123abc123abc123", 111, None)
        call_args = h.food_repo.update_by_id.call_args
        assert call_args[0][1] == {"user_message_id": 111}

    def test_stores_only_bot_id_when_user_is_none(self):
        h = _make_handler()
        h._store_message_ids(h.food_repo, "abc123abc123abc123abc123", None, 222)
        call_args = h.food_repo.update_by_id.call_args
        assert call_args[0][1] == {"bot_message_id": 222}

    def test_no_op_when_entry_id_is_none(self):
        h = _make_handler()
        h._store_message_ids(h.food_repo, None, 111, 222)
        h.food_repo.update_by_id.assert_not_called()

    def test_no_op_when_repo_is_none(self):
        h = _make_handler()
        # Should not raise
        h._store_message_ids(None, "abc123abc123abc123abc123", 111, 222)

    def test_no_op_when_both_ids_none(self):
        h = _make_handler()
        h._store_message_ids(h.food_repo, "abc123abc123abc123abc123", None, None)
        h.food_repo.update_by_id.assert_not_called()


# ---------------------------------------------------------------------------
# Class: TestClassificationMetadata
# ---------------------------------------------------------------------------

class TestClassificationMetadata:
    """Test that classification metadata is stored on bot messages."""

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_bot_message_includes_classification(self, mock_send):
        """_save_bot_message should include classification from _current_classification."""
        h = _make_handler()
        h._current_classification = "meal"
        h._save_bot_message(123, "שווארמה ≈ 720 קל׳")

        call_args = h.user_repo.push_messages.call_args
        msg = call_args[0][1][0]  # first message in list
        assert msg["role"] == "bot"
        assert msg["classification"] == "meal"

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_bot_message_no_classification_when_not_set(self, mock_send):
        """_save_bot_message without _current_classification should not include field."""
        h = _make_handler()
        h._current_classification = None
        h._save_bot_message(123, "שווארמה ≈ 720 קל׳")

        call_args = h.user_repo.push_messages.call_args
        msg = call_args[0][1][0]
        assert "classification" not in msg

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_send_returns_message_id(self, mock_send):
        """_send should return the message_id from send_long_text."""
        mock_send.return_value = 42  # send_long_text returns message_id
        h = _make_handler()
        h._current_classification = "meal"

        result = await h._send("test", tid=123, message=_make_message())
        assert result == 42


# ---------------------------------------------------------------------------
# Banned user tests
# ---------------------------------------------------------------------------

class TestBannedUser:
    """Banned users get a canned response; no routing or LLM calls."""

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_banned_user_gets_canned_response(self, mock_send):
        h = _make_handler()
        h._get_profile = MagicMock(return_value=_make_profile(
            banned_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        ))
        msg = _make_message("שלום")
        update = MagicMock()
        update.effective_message = msg
        update.effective_user.id = 123
        ctx = _make_context()

        await h.handle_message(update, ctx)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "שירות" in sent_text

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_banned_user_no_routing(self, mock_send):
        h = _make_handler()
        h._get_profile = MagicMock(return_value=_make_profile(
            banned_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        ))
        msg = _make_message("אכלתי פיצה")
        update = MagicMock()
        update.effective_message = msg
        update.effective_user.id = 123
        ctx = _make_context()

        await h.handle_message(update, ctx)

        h.analyzer.classify_message.assert_not_called()
