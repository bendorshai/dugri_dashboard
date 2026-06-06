"""Tests for super debug mode: predict_next_step, format_debug_metadata, _append_debug gating."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

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
        assert "--- SUPER DEBUG (day" in result
        assert "[Source] handler" in result
        assert "[Classification] meal" in result
        assert "[Toggles]" in result
        assert "[Next]" in result

    def test_scheduled_classification(self):
        profile = _make_profile()
        svc = _make_toggle_service()
        result = format_debug_metadata(None, profile, svc, source="scheduler")
        assert "[Source] scheduler" in result
        assert "N/A (scheduled)" in result

    def test_toggle_states_shown(self):
        profile = _make_profile()
        profile.toggles.nutrition.status = "active"
        profile.toggles.nutrition.goal_status = "set"
        profile.toggles.nutrition.goal_value = {"calories": 2000, "protein": 150}
        profile.toggles.sleep.status = "cancelled"
        svc = _make_toggle_service()
        result = format_debug_metadata("meal", profile, svc)
        assert "nutrition (day 0): active" in result
        assert "goal=set" in result
        assert "sleep (day 1): cancelled" in result


# ---------------------------------------------------------------------------
# _append_debug gating
# ---------------------------------------------------------------------------

class TestAppendDebugGating:
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
        h._debug_classification = "meal"
        return h

    @patch("constants.SUPER_DEBUG", True)
    def test_debug_appended_for_admin(self):
        h = self._make_handlers(admin_chat_id=999)
        profile = _make_profile(telegram_user_id=999)
        h.user_repo.get.return_value = profile
        result = h._append_debug(999, "hello")
        assert "--- SUPER DEBUG (day" in result
        assert result.startswith("hello\n\n")

    @patch("constants.SUPER_DEBUG", True)
    def test_debug_not_appended_for_non_admin(self):
        h = self._make_handlers(admin_chat_id=999)
        result = h._append_debug(123, "hello")
        assert result == "hello"

    @patch("constants.SUPER_DEBUG", False)
    def test_debug_not_appended_when_disabled(self):
        h = self._make_handlers(admin_chat_id=999)
        result = h._append_debug(999, "hello")
        assert result == "hello"
