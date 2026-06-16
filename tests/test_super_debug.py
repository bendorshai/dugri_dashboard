"""Tests for debug mode: predict_next_step, format_debug_metadata, debug button gating."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock

import pytest

from models.profile import User, Toggles, ToggleState, Targets
from services.toggle_service import ToggleService
from handlers.utils import format_debug_metadata


def _make_profile(**overrides) -> User:
    """Create a test User with sensible defaults."""
    defaults = dict(
        email="test@test.com",
        telegram_user_id=123,
        trial_started_at=datetime.now(timezone.utc) - timedelta(days=3),
        toggles=Toggles(),
        targets=Targets(),
    )
    defaults.update(overrides)
    return User(**defaults)


def _make_toggle_service() -> ToggleService:
    repo = MagicMock()
    return ToggleService(repo)


# ---------------------------------------------------------------------------
# predict_next_step
# ---------------------------------------------------------------------------

class TestPredictNextStep:
    def test_day_0_predicts_nutrition_after_next_meal(self):
        profile = _make_profile(trial_started_at=datetime.now(timezone.utc))
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert "reveal nutrition" in result
        assert "after next meal" in result

    def test_day_2_predicts_eating_window(self):
        """Day 2: nutrition + sleep past gate, eating_window is next (gate=4)."""
        profile = _make_profile(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        # Nutrition and sleep already active
        profile.toggles.nutrition.status = "active"
        profile.toggles.nutrition.goal_status = "set"
        profile.toggles.sleep.status = "active"
        profile.toggles.sleep.goal_status = "set"
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert "reveal eating_window" in result
        assert "in 2d" in result

    def test_all_active_goals_set(self):
        profile = _make_profile(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care"):
            toggle = getattr(profile.toggles, name)
            toggle.status = "active"
            toggle.goal_status = "set"
        profile.toggles.weekly_summary.status = "active"
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert result == "all toggles resolved"

    def test_dormant_revealed_waiting(self):
        profile = _make_profile()
        profile.toggles.nutrition.status = "dormant"
        profile.toggles.nutrition.revealed_at = datetime.now(timezone.utc)
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert "waiting" in result
        assert "accept" in result
        assert "nutrition" in result

    def test_active_goal_pending_offered(self):
        profile = _make_profile()
        profile.toggles.nutrition.status = "active"
        profile.toggles.nutrition.goal_status = "pending"
        profile.toggles.nutrition.goal_offered_at = datetime.now(timezone.utc)
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert "waiting for user to set nutrition goal" in result

    def test_goal_remind_shows_date(self):
        remind_date = datetime(2026, 6, 15, tzinfo=timezone.utc)
        profile = _make_profile()
        profile.toggles.nutrition.status = "active"
        profile.toggles.nutrition.goal_status = "remind"
        profile.toggles.nutrition.goal_remind_at = remind_date
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert "2026-06-15" in result
        assert "remind" in result

    def test_cancelled_toggle_skipped(self):
        profile = _make_profile(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        profile.toggles.nutrition.status = "cancelled"
        # Sleep should be next
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert "sleep" in result

    def test_workouts_mentions_thursday(self):
        profile = _make_profile(
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        for name in ("nutrition", "sleep", "eating_window"):
            toggle = getattr(profile.toggles, name)
            toggle.status = "active"
            toggle.goal_status = "set"
        svc = _make_toggle_service()
        result = svc.predict_next_step(profile)
        assert "workouts" in result
        assert "Thu" in result


# ---------------------------------------------------------------------------
# format_debug_metadata
# ---------------------------------------------------------------------------

class TestFormatDebugMetadata:
    def test_contains_all_sections(self):
        profile = _make_profile()
        svc = _make_toggle_service()
        result = format_debug_metadata("meal", profile, svc)
        assert "🔍 Debug - Day" in result
        assert "handler" in result
        assert "📋 Classification: meal" in result
        assert "🎚 Toggles:" in result
        assert "🔮 Next:" in result

    def test_scheduled_classification(self):
        profile = _make_profile()
        svc = _make_toggle_service()
        result = format_debug_metadata(None, profile, svc, source="scheduler")
        assert "scheduler" in result
        assert "N/A (scheduled)" in result

    def test_toggle_states_shown(self):
        profile = _make_profile()
        profile.toggles.nutrition.status = "active"
        profile.toggles.nutrition.goal_status = "set"
        profile.toggles.nutrition.goal_value = {"calories": 2000, "protein": 150}
        profile.toggles.sleep.status = "cancelled"
        svc = _make_toggle_service()
        result = format_debug_metadata("meal", profile, svc)
        assert "✅" in result
        assert "nutrition (day 0)" in result
        assert "active" in result
        assert "goal=set" in result
        assert "❌" in result
        assert "sleep (day 1)" in result
        assert "cancelled" in result


# ---------------------------------------------------------------------------
# Debug button gating
# ---------------------------------------------------------------------------

class TestDebugButton:
    def _make_handlers(self, admin_chat_id=999):
        from handlers.base import HealthHandlers
        h = HealthHandlers(
            analyzer=MagicMock(),
            user_repo=MagicMock(),
            food_repo=MagicMock(),
            feedback_repo=MagicMock(),
            eating_day_service=MagicMock(),
            toggle_service=_make_toggle_service(),
            admin_chat_id=admin_chat_id,
        )
        return h

    def test_debug_button_injected_when_mode_on(self):
        h = self._make_handlers(admin_chat_id=999)
        h._debug_mode = True
        h._debug_classification = "meal"
        profile = _make_profile(telegram_user_id=999)
        h.user_repo.get.return_value = profile
        text, markup = h._prepare_debug(999, "hello")
        assert text == "hello"
        assert markup is not None
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        debug_buttons = [b for b in buttons if b.callback_data.startswith("dbg_")]
        assert len(debug_buttons) == 1
        assert debug_buttons[0].text == "🔍"

    def test_debug_button_not_injected_when_mode_off(self):
        h = self._make_handlers(admin_chat_id=999)
        h._debug_mode = False
        text, markup = h._prepare_debug(999, "hello")
        assert text == "hello"
        assert markup is None

    def test_debug_button_not_injected_for_non_admin(self):
        h = self._make_handlers(admin_chat_id=999)
        h._debug_mode = True
        text, markup = h._prepare_debug(123, "hello")
        assert text == "hello"
        assert markup is None

    def test_debug_button_coexists_with_existing_keyboard(self):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        h = self._make_handlers(admin_chat_id=999)
        h._debug_mode = True
        h._debug_classification = "meal"
        profile = _make_profile(telegram_user_id=999)
        h.user_repo.get.return_value = profile
        existing = InlineKeyboardMarkup([[InlineKeyboardButton("Test", callback_data="test")]])
        text, markup = h._prepare_debug(999, "hello", existing)
        assert len(markup.inline_keyboard) == 2
        assert markup.inline_keyboard[0][0].text == "Test"
        assert markup.inline_keyboard[1][0].callback_data.startswith("dbg_")

    def test_debug_store_eviction(self):
        h = self._make_handlers(admin_chat_id=999)
        h._debug_mode = True
        h._debug_classification = "meal"
        profile = _make_profile(telegram_user_id=999)
        h.user_repo.get.return_value = profile
        for i in range(201):
            h._prepare_debug(999, f"msg {i}")
        assert len(h._debug_store) == 200

    def test_debug_mode_reads_from_constant(self):
        """HandlerContext reads DEBUG_MODE from constants at init time."""
        import constants
        original = constants.DEBUG_MODE
        try:
            constants.DEBUG_MODE = True
            h = self._make_handlers(admin_chat_id=999)
            assert h._debug_mode is True
            constants.DEBUG_MODE = False
            h2 = self._make_handlers(admin_chat_id=999)
            assert h2._debug_mode is False
        finally:
            constants.DEBUG_MODE = original

    @pytest.mark.asyncio
    async def test_debug_callback_returns_metadata(self):
        h = self._make_handlers(admin_chat_id=999)
        h._debug_store["abc12345"] = "test metadata"
        update = MagicMock()
        update.callback_query.data = "dbg_abc12345"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.reply_text = AsyncMock()
        await h.handle_debug_callback(update, MagicMock())
        update.callback_query.message.reply_text.assert_called_once_with("test metadata")

    @pytest.mark.asyncio
    async def test_debug_callback_expired_key(self):
        h = self._make_handlers(admin_chat_id=999)
        update = MagicMock()
        update.callback_query.data = "dbg_nonexistent"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.reply_text = AsyncMock()
        await h.handle_debug_callback(update, MagicMock())
        update.callback_query.message.reply_text.assert_called_once_with("Debug info expired.")
