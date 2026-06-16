"""
test_goal_service.py - Unit tests for GoalService.

Tests the nutrition confirmation flow (partial adjustment, targets sync)
and user-initiated goal updates.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod in [
    "telegram", "telegram.ext",
    "pymongo", "openai",
]:
    sys.modules.setdefault(mod, MagicMock())

from models.profile import User, Targets, ToggleState, Toggles
from repositories.user_repository import UserRepository
from services.toggle_service import ToggleService
from services.goal_service import GoalService


def _make_user(
    nutrition_goal_value=None,
    nutrition_goal_status="pending",
    nutrition_status="active",
    targets_cal=None,
    targets_prot=None,
    sleep_goal_value=None,
    sleep_goal_status="pending",
    sleep_status="dormant",
    **kwargs,
):
    """Build a User with customizable toggle/target state."""
    toggles = Toggles(
        nutrition=ToggleState(
            status=nutrition_status,
            goal_status=nutrition_goal_status,
            goal_value=nutrition_goal_value,
        ),
        sleep=ToggleState(
            status=sleep_status,
            goal_status=sleep_goal_status,
            goal_value=sleep_goal_value,
        ),
        eating_window=ToggleState(),
        workouts=ToggleState(),
        self_care=ToggleState(),
        weekly_summary=ToggleState(status="active"),
    )
    targets = Targets(calories=targets_cal, protein=targets_prot)
    return User(
        email="test@test.com",
        telegram_user_id=123,
        toggles=toggles,
        targets=targets,
        **kwargs,
    )


def _make_service(analyzer=None):
    """Create GoalService with mocked dependencies."""
    user_repo = MagicMock(spec=UserRepository)
    toggle_service = MagicMock(spec=ToggleService)
    svc = GoalService(user_repo, toggle_service, analyzer)
    return svc, user_repo, toggle_service


# ============================================================================
# Gap 1: Partial Nutrition Adjustment + Targets Sync
# ============================================================================


class TestNutritionConfirmPartialAdjustment:
    """When user adjusts one value from the suggestion, merge with original."""

    ORIGINAL_SUGGESTION = {"calories": 2200, "protein": 179}

    def test_partial_protein_merges_with_original(self):
        """User says 'אני מעדיף 170 גרם חלבון' -> keep original calories, update protein."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"protein": 170}

        user = _make_user(nutrition_goal_value=self.ORIGINAL_SUGGESTION)
        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get.return_value = user

        svc.handle_nutrition_confirm(123, "אני מעדיף 170 גרם חלבון")

        # Should merge: original calories + new protein
        toggle_svc.set_goal_value.assert_called_once_with(
            123, "nutrition", {"calories": 2200, "protein": 170},
        )
        # Should sync targets
        update_calls = user_repo.update_fields.call_args_list
        target_update = next(
            c for c in update_calls
            if "targets.calories" in c[0][1]
        )
        assert target_update[0][1]["targets.calories"] == 2200
        assert target_update[0][1]["targets.protein"] == 170

    def test_partial_calories_merges_with_original(self):
        """User says 'בוא נעשה 2000 קלוריות' -> update calories, keep original protein."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"calories": 2000}

        user = _make_user(nutrition_goal_value=self.ORIGINAL_SUGGESTION)
        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get.return_value = user

        svc.handle_nutrition_confirm(123, "בוא נעשה 2000 קלוריות")

        toggle_svc.set_goal_value.assert_called_once_with(
            123, "nutrition", {"calories": 2000, "protein": 179},
        )

    def test_both_values_uses_both(self):
        """User provides both values -> uses both (no merge needed)."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"calories": 2000, "protein": 160}

        user = _make_user(nutrition_goal_value=self.ORIGINAL_SUGGESTION)
        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get.return_value = user

        svc.handle_nutrition_confirm(123, "2000 קלוריות ו-160 חלבון")

        toggle_svc.set_goal_value.assert_called_once_with(
            123, "nutrition", {"calories": 2000, "protein": 160},
        )


class TestNutritionConfirmTargetsSync:
    """Targets.calories/protein must be synced on ALL confirm paths."""

    SUGGESTION = {"calories": 2200, "protein": 179}

    def test_accept_original_syncs_targets(self):
        """User says 'נשמע טוב' (no numbers) -> targets populated from suggestion."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = None  # no numbers found

        user = _make_user(nutrition_goal_value=self.SUGGESTION)
        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get.return_value = user

        svc.handle_nutrition_confirm(123, "נשמע טוב")

        # goal_status should be set
        toggle_svc.set_goal_status.assert_called_once_with(123, "nutrition", "set")
        # targets must be synced from original suggestion
        update_calls = user_repo.update_fields.call_args_list
        target_update = next(
            c for c in update_calls
            if "targets.calories" in c[0][1]
        )
        assert target_update[0][1]["targets.calories"] == 2200
        assert target_update[0][1]["targets.protein"] == 179

    def test_corrected_values_sync_targets(self):
        """User provides corrected numbers -> targets match corrected values."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"calories": 1800, "protein": 150}

        user = _make_user(nutrition_goal_value=self.SUGGESTION)
        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get.return_value = user

        svc.handle_nutrition_confirm(123, "1800 ו-150")

        update_calls = user_repo.update_fields.call_args_list
        target_update = next(
            c for c in update_calls
            if "targets.calories" in c[0][1]
        )
        assert target_update[0][1]["targets.calories"] == 1800
        assert target_update[0][1]["targets.protein"] == 150

    def test_no_profile_uses_defaults(self):
        """Edge case: no profile found -> uses defaults 2000/150."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = None

        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get.return_value = None  # no profile

        svc.handle_nutrition_confirm(123, "סבבה")

        toggle_svc.set_goal_status.assert_called_once_with(123, "nutrition", "set")
        update_calls = user_repo.update_fields.call_args_list
        target_update = next(
            c for c in update_calls
            if "targets.calories" in c[0][1]
        )
        assert target_update[0][1]["targets.calories"] == 2000
        assert target_update[0][1]["targets.protein"] == 150


# ============================================================================
# Gap 2: User-Initiated Goal Update
# ============================================================================


class TestGoalUpdate:
    """When user requests to update an already-set goal."""

    def test_sleep_update_with_value(self):
        """'שנה את יעד השינה ל-23:00' -> updates goal directly."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"sleep_time": "23:00"}

        user = _make_user(
            sleep_status="active",
            sleep_goal_status="set",
            sleep_goal_value={"sleep_time": "22:00"},
        )
        svc, user_repo, toggle_svc = _make_service(analyzer)

        result = svc.handle_goal_update(123, "sleep", "שנה ל-23:00", user)

        toggle_svc.set_goal_value.assert_called_once_with(
            123, "sleep", {"sleep_time": "23:00"},
        )
        assert result  # should return confirmation text

    def test_sleep_update_no_value_reoffers(self):
        """'שנה את יעד השינה' (no number) -> re-offers goal question."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = None

        user = _make_user(
            sleep_status="active",
            sleep_goal_status="set",
            sleep_goal_value={"sleep_time": "22:00"},
        )
        svc, user_repo, toggle_svc = _make_service(analyzer)

        result = svc.handle_goal_update(123, "sleep", "שנה את יעד השינה", user)

        # Should re-offer the goal (ask for value)
        assert result  # should return the goal question text

    def test_nutrition_update_with_both(self):
        """'2000 קלוריות ו-160 חלבון' -> updates both targets directly."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"calories": 2000, "protein": 160}

        user = _make_user(
            nutrition_status="active",
            nutrition_goal_status="set",
            nutrition_goal_value={"calories": 2200, "protein": 179},
        )
        svc, user_repo, toggle_svc = _make_service(analyzer)

        svc.handle_goal_update(123, "nutrition", "2000 קלוריות ו-160 חלבון", user)

        toggle_svc.set_goal_value.assert_called_once_with(
            123, "nutrition", {"calories": 2000, "protein": 160},
        )
        update_calls = user_repo.update_fields.call_args_list
        target_update = next(
            c for c in update_calls
            if "targets.calories" in c[0][1]
        )
        assert target_update[0][1]["targets.calories"] == 2000
        assert target_update[0][1]["targets.protein"] == 160

    def test_nutrition_update_partial_merges(self):
        """'שנה ל-2000 קלוריות' -> merges with existing protein."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"calories": 2000}

        user = _make_user(
            nutrition_status="active",
            nutrition_goal_status="set",
            nutrition_goal_value={"calories": 2200, "protein": 179},
        )
        svc, user_repo, toggle_svc = _make_service(analyzer)

        svc.handle_goal_update(123, "nutrition", "שנה ל-2000 קלוריות", user)

        toggle_svc.set_goal_value.assert_called_once_with(
            123, "nutrition", {"calories": 2000, "protein": 179},
        )

    def test_nutrition_update_no_value_asks(self):
        """'שנה את היעדים שלי' (no number) -> asks for specific values."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = None

        user = _make_user(
            nutrition_status="active",
            nutrition_goal_status="set",
            nutrition_goal_value={"calories": 2200, "protein": 179},
        )
        svc, user_repo, toggle_svc = _make_service(analyzer)

        result = svc.handle_goal_update(123, "nutrition", "שנה את היעדים שלי", user)

        # Should ask for specific numbers
        assert result
        toggle_svc.set_goal_offered.assert_called()

    def test_self_care_no_goal_returns_none(self):
        """Self-care has no goal -> handle_goal_update returns None."""
        svc, _, _ = _make_service()
        user = _make_user()

        result = svc.handle_goal_update(123, "self_care", "שנה", user)

        assert result is None


# ============================================================================
# Context-aware goal value extraction (confirmation recovery)
# ============================================================================


class TestHandleGoalValueWithHistory:
    """When user confirms a bot-proposed goal (e.g. 'כן!' after bot said
    '5 אימונים בשבוע, רוצה שאקבע?'), handle_goal_value should pass
    conversation history to extract_goal_value so the extraction GPT
    can resolve the value from context."""

    def test_confirmation_resolves_from_history(self):
        """'כן!' with bot history containing '5 אימונים' -> sets goal."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"weekly_target": 5}

        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get_recent_messages.return_value = [
            {"role": "bot", "text": "5 אימונים של 15 דקות כל שבוע. רוצה שאקבע?"},
            {"role": "user", "text": "כן!"},
        ]

        result = svc.handle_goal_value(123, "workouts", "כן!")

        # Should pass recent_messages to extraction
        call_args = analyzer.extract_goal_value.call_args
        assert call_args[1].get("recent_messages") is not None
        # Should set the goal
        toggle_svc.set_goal_value.assert_called_once_with(
            123, "workouts", {"weekly_target": 5},
        )
        assert result  # confirmation text

    def test_direct_value_still_works(self):
        """'5' with history context -> still extracts directly."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"weekly_target": 5}

        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get_recent_messages.return_value = [
            {"role": "bot", "text": "כמה אימונים בשבוע?"},
            {"role": "user", "text": "5"},
        ]

        result = svc.handle_goal_value(123, "workouts", "5")

        toggle_svc.set_goal_value.assert_called_once_with(
            123, "workouts", {"weekly_target": 5},
        )
        assert result

    def test_no_value_anywhere_reasks(self):
        """'כן!' with no number in bot history -> re-asks."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = None

        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get_recent_messages.return_value = [
            {"role": "bot", "text": "מה נשמע?"},
            {"role": "user", "text": "כן!"},
        ]

        result = svc.handle_goal_value(123, "workouts", "כן!")

        toggle_svc.set_goal_value.assert_not_called()
        assert result  # re-ask text

    def test_sleep_confirmation_resolves(self):
        """Sleep goal confirmation from history works too."""
        analyzer = MagicMock()
        analyzer.extract_goal_value.return_value = {"sleep_time": "23:00"}

        svc, user_repo, toggle_svc = _make_service(analyzer)
        user_repo.get_recent_messages.return_value = [
            {"role": "bot", "text": "אז נקבע יעד שינה ל-23:00? רוצה?"},
            {"role": "user", "text": "סבבה"},
        ]

        result = svc.handle_goal_value(123, "sleep", "סבבה")

        toggle_svc.set_goal_value.assert_called_once_with(
            123, "sleep", {"sleep_time": "23:00"},
        )
        assert result
