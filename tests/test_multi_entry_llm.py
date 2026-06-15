"""
test_multi_entry_llm.py - TDD for multi-entry logging, name collection, and feedback requests.

These tests call the actual GPT-4o-mini router to verify specialized
routes that are orthogonal to the toggle lifecycle. They are
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
# MULTI-ENTRY LOGGING (SAME TYPE)
# --------------------------------
# A single message can contain MULTIPLE entries of the SAME habit type
# for different dates. The classifier populates habit_entries
# (list of HabitEntry) alongside the primary type.
#
# Currently Dugri only supports multiple entries of the same type in one
# message. Mixed-type multi-entry (e.g. workout + sleep + food in one
# message) is NOT yet supported.
#
# Examples:
#   - "שלשום הלכתי לישון ב-21:00 ואתמול ב-22:00"
#     -> type=sleep, habit_entries=[{sleep, שלשום, 21:00}, {sleep, אתמול, 22:00}]
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
#   - "כן" / "יאללה" / "סבבה" when a toggle is offered -> opt_in
#   - Food descriptions when greeting is in history -> meal
#   - The classifier never guesses: if it's ambiguous, it's NOT a name.
#
# FEEDBACK REQUEST
# -----------------
# "שלח סיכום שבועי" / "שלח סיכום" -> feedback_request route.
# This is a user-initiated request for the weekly summary, distinct from
# the scheduled weekly summary hook. Must NOT be misclassified as
# opt_in (regression from v2.2.2, fixed in 60f3bfe).
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
    _make_analyzer, _build_toggle_state, _build_history, _route,
    FOOD_RESPONSE_SCHNITZEL, FOOD_RESPONSE_COFFEE,
    NUTRITION_OFFER, ONBOARDING_GREETING,
)

pytestmark = pytest.mark.integration


# ============================================================================
# GAP 2: MIXED-TYPE & RETROACTIVE MULTI-ENTRY LOGGING
#
# A single message can contain entries across MULTIPLE habit types AND food,
# for different dates. The router classifies the primary type; downstream
# handlers extract individual entries.
# ============================================================================

class TestMultiEntryHabits:
    """Tests for retroactive and mixed-type habit logging.

    These verify that the router correctly classifies multi-date and
    mixed-type habit messages. The Router classifies the primary type;
    habit_entries extraction happens downstream in the handler layer.
    """

    # --- Single-type, multi-date ---

    def test_sleep_two_days_retroactive(self):
        """'שלשום הלכתי לישון ב-21:00 ואתמול ב-22:00' -> type=sleep."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "שלשום הלכתי לישון ב-21:00 ואתמול ב-22:00",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "sleep"

    def test_workout_multi_day(self):
        """'התאמנתי ביום שני וביום רביעי' -> type=workout."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "התאמנתי ביום שני וביום רביעי",
            toggle_state=_build_toggle_state(workouts="active_with_goal"),
            history=_build_history(
                ("user", "קפה עם חלב"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "workout"

    def test_sleep_same_time_shorthand(self):
        """'אתמול הלכתי לישון ב-22:00, שלשום אותו דבר' -> type=sleep."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "אתמול הלכתי לישון ב-22:00, שלשום אותו דבר",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "sleep"

    # --- Mixed-type (multiple habit types in one message) ---

    def test_mixed_workout_and_sleep(self):
        """'שלשום התאמנתי ואתמול הלכתי לישון ב-22:00' -> conversational (multi-intent)."""
        analyzer = _make_analyzer()
        result = _route(
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
        # Multi-intent: two different habit types -> conversational
        assert result.type == "conversational"

    def test_mixed_food_and_habits(self):
        """'היום אכלתי צ'יזבורגר, אתמול הלכתי לישון ב-23:00, ושלשום התאמנתי'
        -> conversational (multi-intent: food + sleep + workout)."""
        analyzer = _make_analyzer()
        result = _route(
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
        # Multi-intent with food -> could be meal (meal always wins) or conversational
        assert result.type in ("meal", "conversational")

    # --- Backward compatibility ---

    def test_sleep_single_still_works(self):
        """Single sleep entry -> type=sleep."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "הלכתי לישון ב-23:00",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "sleep"

    def test_food_single_still_works(self):
        """Single food entry -> type=meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "שניצל עם אורז",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "meal"


# ============================================================================
# NAME COLLECTION (name_declaration route)
# ============================================================================

class TestNameDeclaration:
    """Tests for the name_declaration router route."""

    def test_direct_name_response_after_greeting(self):
        """User replies with a name right after the greeting -> name_declaration."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "שי",
            toggle_state=_build_toggle_state(),
            history=_build_history(
                ("bot", ONBOARDING_GREETING),
            ),
        )
        assert result.type == "name_declaration"

    def test_name_ghosting_food_instead(self):
        """User ignores name question and sends food -> meal, not name."""
        analyzer = _make_analyzer()
        result = _route(
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
        result = _route(
            analyzer, "אגב קוראים לי דני",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "name_declaration"

    def test_yes_to_nutrition_offer_not_name(self):
        """'כן' with nutrition offered must be opt_in, NOT name."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("bot", ONBOARDING_GREETING),
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "opt_in"


# ============================================================================
# FEEDBACK REQUEST (cross-cutting)
# ============================================================================

class TestFeedbackRequest:
    """Regression tests for feedback_request classification."""

    def test_weekly_summary_request(self):
        """'שלח סיכום שבועי' -> feedback_request, not opt_in.

        Regression: bug from 2026-05-25 where this was misclassified as
        toggle_activate with no toggle_name, causing 'לא הבנתי איזה מעקב להדליק'.
        Fixed in v2.2.2 (60f3bfe).
        """
        analyzer = _make_analyzer()
        result = _route(
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
        result = _route(
            analyzer, "שלח סיכום",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "feedback_request"
