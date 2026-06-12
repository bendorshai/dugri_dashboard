"""
test_multi_entry_llm.py - TDD for multi-entry logging, name collection, and feedback requests.

These tests call the actual GPT-4o-mini classifier to verify specialized
classifier routes that are orthogonal to the toggle lifecycle. They are
integration tests that require an OpenAI API key and network access.

Run with: pytest tests/test_multi_entry_llm.py -v -m integration

# ============================================================================
# MULTI-ENTRY, NAME, AND FEEDBACK SPECIFICATION (Single Source of Truth)
#
# This comment defines the expected behavior for three classifier routes
# that are distinct from the core lazy opt-in lifecycle. When behavior
# changes, UPDATE THIS COMMENT FIRST, then update/add tests, then fix
# code to pass.
#
# ============================================================================
#
# MIXED-TYPE & RETROACTIVE MULTI-ENTRY LOGGING
# ----------------------------------------------
# A single message can contain entries across MULTIPLE habit types AND
# food, for different dates. The classifier populates habit_entries
# (list of HabitEntry) alongside the primary type.
#
# Examples:
#   - "שלשום הלכתי לישון ב-21:00 ואתמול ב-22:00"
#     -> type=sleep, habit_entries=[{sleep, שלשום, 21:00}, {sleep, אתמול, 22:00}]
#   - "שלשום התאמנתי ואתמול הלכתי לישון ב-22:00"
#     -> type=workout, habit_entries=[{workout, שלשום}, {sleep, אתמול, 22:00}]
#   - "היום אכלתי צ'יזבורגר, אתמול הלכתי לישון ב-23:00, ושלשום התאמנתי"
#     -> type=meal, meal={...}, habit_entries=[{sleep, אתמול, 23:00}, {workout, שלשום}]
#
# For single-entry messages, the scalar fields (sleep_time, workout_note,
# self_care_description) are still populated for backward compatibility.
# habit_entries is only used for multi-entry or mixed-type messages.
#
# Temporal rules for habits mirror food's temporal extraction: "אתמול",
# "שלשום", "ביום שני", etc. "אותו דבר" / "גם" = same value as the
# previous entry mentioned.
#
# NAME COLLECTION (name_declaration route)
# -------------------------------------------
# After linking, Dugri sends ONBOARDING_GREETING which asks the user's
# name ("איך אתה רוצה שאקרא לך?"). Name is collected via a dedicated
# classifier route "name_declaration" - NOT via conversation_reply.
#
# Two valid triggers:
#   1. DIRECT RESPONSE: greeting is in recent history, user sends a name
#      (e.g., "שי", "דני"). Classifier sees the name question and routes
#      as name_declaration with declared_name extracted.
#   2. EXPLICIT DECLARATION: user says "קוראים לי שי" / "השם שלי דני"
#      at any point, even without the greeting in history. Classifier
#      recognizes the declaration pattern.
#
# What is NOT a name declaration:
#   - "כן" / "יאללה" / "סבבה" when a toggle is offered -> conversation_reply
#   - Food descriptions when greeting is in history -> meal
#   - The classifier never guesses: if it's ambiguous, it's NOT a name.
#
# FEEDBACK REQUEST
# -----------------
# "שלח סיכום שבועי" / "שלח סיכום" -> feedback_request route.
# This is a user-initiated request for the weekly summary, distinct from
# the scheduled weekly summary hook. Must NOT be misclassified as
# toggle_activate (regression from v2.2.2, fixed in 60f3bfe).
#
# ============================================================================
"""

import os
import sys
import pytest

# Add project root and tests dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer, _build_toggle_state, _build_history, _classify,
    FOOD_RESPONSE_SCHNITZEL, FOOD_RESPONSE_COFFEE,
    NUTRITION_OFFER, ONBOARDING_GREETING,
)

pytestmark = pytest.mark.integration


# ============================================================================
# GAP 2: MIXED-TYPE & RETROACTIVE MULTI-ENTRY LOGGING
#
# A single message can contain entries across MULTIPLE habit types AND food,
# for different dates. The classifier returns habit_entries for multi-entry
# and mixed-type cases.
# ============================================================================

class TestMultiEntryHabits:
    """Tests for retroactive and mixed-type habit logging.

    These verify that the classifier correctly populates habit_entries
    when a message contains multiple dates or multiple habit types.
    """

    # --- Single-type, multi-date ---

    def test_sleep_two_days_retroactive(self):
        """'שלשום הלכתי לישון ב-21:00 ואתמול ב-22:00' -> 2 sleep entries."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer,
            "שלשום הלכתי לישון ב-21:00 ואתמול ב-22:00",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "sleep"
        assert result.habit_entries is not None
        assert len(result.habit_entries) == 2
        times = sorted(e.sleep_time for e in result.habit_entries)
        assert "21:00" in times
        assert "22:00" in times

    def test_workout_multi_day(self):
        """'התאמנתי ביום שני וביום רביעי' -> 2 workout entries."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer,
            "התאמנתי ביום שני וביום רביעי",
            toggle_state=_build_toggle_state(workouts="active_with_goal"),
            history=_build_history(
                ("user", "קפה עם חלב"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "workout"
        assert result.habit_entries is not None
        assert len(result.habit_entries) == 2
        assert all(e.habit_type == "workout" for e in result.habit_entries)

    def test_sleep_same_time_shorthand(self):
        """'אתמול הלכתי לישון ב-22:00, שלשום אותו דבר' -> 2 entries both 22:00."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer,
            "אתמול הלכתי לישון ב-22:00, שלשום אותו דבר",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "sleep"
        assert result.habit_entries is not None
        assert len(result.habit_entries) == 2
        assert all(e.sleep_time == "22:00" for e in result.habit_entries)

    # --- Mixed-type (multiple habit types in one message) ---

    def test_mixed_workout_and_sleep(self):
        """'שלשום התאמנתי ואתמול הלכתי לישון ב-22:00' -> workout + sleep entries."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer,
            "שלשום התאמנתי ואתמול הלכתי לישון ב-22:00",
            toggle_state=_build_toggle_state(
                sleep="active_with_goal", workouts="active_with_goal",
            ),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.habit_entries is not None
        assert len(result.habit_entries) == 2
        types = {e.habit_type for e in result.habit_entries}
        assert "sleep" in types
        assert "workout" in types

    def test_mixed_food_and_habits(self):
        """'היום אכלתי צ'יזבורגר, אתמול הלכתי לישון ב-23:00, ושלשום התאמנתי'
        -> type=meal with food data, plus habit_entries with sleep + workout."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer,
            "היום אכלתי צ'יזבורגר, אתמול הלכתי לישון ב-23:00, ושלשום התאמנתי",
            toggle_state=_build_toggle_state(
                nutrition="active_with_goal",
                sleep="active_with_goal",
                workouts="active_with_goal",
            ),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "meal"
        assert result.meal is not None
        assert result.habit_entries is not None
        assert len(result.habit_entries) == 2
        types = {e.habit_type for e in result.habit_entries}
        assert "sleep" in types
        assert "workout" in types

    def test_mixed_all_types(self):
        """Full mixed message: workout + 2 sleep entries + food.
        'שלשום התאמנתי, אתמול הלכתי לישון ב-22:00, שלשום גם בדיוק אותו דבר, והיום אכלתי צ'יזבורגר'
        -> type=meal, habit_entries has 3 entries (1 workout + 2 sleep)."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer,
            "שלשום התאמנתי, אתמול הלכתי לישון ב-22:00, שלשום גם בדיוק אותו דבר, והיום אכלתי צ'יזבורגר",
            toggle_state=_build_toggle_state(
                nutrition="active_with_goal",
                sleep="active_with_goal",
                workouts="active_with_goal",
            ),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "meal"
        assert result.meal is not None
        assert result.habit_entries is not None
        assert len(result.habit_entries) == 3
        sleep_entries = [e for e in result.habit_entries if e.habit_type == "sleep"]
        workout_entries = [e for e in result.habit_entries if e.habit_type == "workout"]
        assert len(sleep_entries) == 2
        assert len(workout_entries) == 1

    # --- Backward compatibility ---

    def test_sleep_single_still_works(self):
        """Single sleep entry still uses the scalar sleep_time field."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "הלכתי לישון ב-23:00",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "sleep"
        assert result.sleep_time is not None
        assert "23:00" in result.sleep_time

    def test_food_single_still_works(self):
        """Single food entry has no habit_entries."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שניצל עם אורז",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "meal"
        assert not result.habit_entries


# ============================================================================
# NAME COLLECTION (name_declaration route)
# ============================================================================

class TestNameDeclaration:
    """Tests for the name_declaration classifier route."""

    def test_direct_name_response_after_greeting(self):
        """User replies with a name right after the greeting -> name_declaration."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שי",
            toggle_state=_build_toggle_state(),
            history=_build_history(
                ("bot", ONBOARDING_GREETING),
            ),
        )
        assert result.type == "name_declaration"
        assert result.declared_name is not None
        assert "שי" in result.declared_name

    def test_name_ghosting_food_instead(self):
        """User ignores name question and sends food -> meal, not name."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אכלתי סלט",
            toggle_state=_build_toggle_state(),
            history=_build_history(
                ("bot", ONBOARDING_GREETING),
            ),
        )
        assert result.type == "meal"

    def test_post_entries_explicit_name_declaration(self):
        """User declares name later with 'קוראים לי' -> name_declaration."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אגב קוראים לי דני",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "name_declaration"
        assert result.declared_name is not None
        assert "דני" in result.declared_name

    def test_yes_to_nutrition_offer_not_name(self):
        """'כן' with nutrition offered must be conversation_reply, NOT name."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "כן",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("bot", ONBOARDING_GREETING),
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "conversation_reply"


# ============================================================================
# FEEDBACK REQUEST (cross-cutting)
# ============================================================================

class TestFeedbackRequest:
    """Regression tests for feedback_request classification."""

    def test_weekly_summary_request(self):
        """'שלח סיכום שבועי' -> feedback_request, not toggle_activate.

        Regression: bug from 2026-05-25 where this was misclassified as
        toggle_activate with no toggle_name, causing 'לא הבנתי איזה מעקב להדליק'.
        Fixed in v2.2.2 (60f3bfe).
        """
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שלח סיכום שבועי",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "feedback_request", (
            f"'שלח סיכום שבועי' misclassified as {result.type} "
            f"(toggle_name={result.toggle_name})"
        )

    def test_weekly_summary_request_short(self):
        """'שלח סיכום' -> feedback_request."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שלח סיכום",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "feedback_request"
