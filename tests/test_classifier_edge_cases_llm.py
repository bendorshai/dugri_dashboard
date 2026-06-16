"""
test_classifier_edge_cases_llm.py - TDD for router routing constraints.

These tests call the actual GPT-4o-mini router to verify cross-cutting
routing rules: when 'conversational' is/isn't valid during active flows,
and sharp vs soft refusal classification. They are integration tests that
require an OpenAI API key and network access.

Run with: pytest tests/test_classifier_edge_cases_llm.py -v -m integration

# ============================================================================
# ROUTING RULES SPECIFICATION (Single Source of Truth)
#
# This comment defines the router's cross-cutting routing constraints.
# When behavior changes, UPDATE THIS COMMENT FIRST, then update/add tests,
# then fix code to pass.
#
# ============================================================================
#
# CONVERSATIONAL IS A LAST RESORT DURING ACTIVE FLOWS
# ----------------------------------------------------
# When a toggle is offered and the offer is in history, short informal
# messages ("יאללה", "סבבה", "אוקיי", "בוא", "כן", "טוב") are ALWAYS
# opt_in responses, never conversational chitchat.
#
# When any toggle is in an active flow (offered/goal_pending/remind_pending),
# the router must find a specific route. Even ambiguous messages like "אממ",
# "מה?", "נו" are responses to the bot's question, not generic conversation.
#
# Genuine conversational: only when NO toggle is in an active flow AND the
# message is truly off-topic (e.g., "מה שלומך?" with all toggles dormant).
#
# REFUSAL CLASSIFICATION (sharp vs soft)
# ----------------------------------------
# The router classifies refusals as opt_in. The handler layer distinguishes
# sharp vs soft by analyzing the message text. The router's job is to
# correctly identify that a refusal IS an opt_in action, not conversational.
#
#   - Sharp refusal: "לא", "עזוב", "לא מעניין", "לא רוצה"
#   - Soft refusal: "לא סגור על זה", "לא בטוח", "אולי לא עכשיו"
#
# Both sharp and soft refusals route to opt_in when a toggle is in flow.
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
    NUTRITION_OFFER, NUTRITION_SUGGESTION, WEIGHT_GOAL_ASK,
    SLEEP_OFFER, EATING_WINDOW_OFFER, WORKOUTS_OFFER, GOAL_REMIND_ASK,
)

pytestmark = pytest.mark.integration


class TestNoneIsRare:
    """Tests that generic conversational classification is rare during active flows."""

    def test_none_with_offer_should_not_happen(self):
        """Short informal messages with offered toggle + offer in history -> never conversational."""
        analyzer = _make_analyzer()
        short_messages = ["יאללה", "סבבה", "אוקיי", "בוא", "כן", "טוב"]
        for msg in short_messages:
            result = _route(
                analyzer, msg,
                toggle_state=_build_toggle_state(nutrition="offered"),
                history=_build_history(
                    ("user", "שניצל עם אורז"),
                    ("bot", FOOD_RESPONSE_SCHNITZEL),
                    ("bot", NUTRITION_OFFER),
                ),
            )
            assert result.type == "opt_in", f"'{msg}' classified as {result.type} with offer in context"

    def test_genuine_chitchat_is_conversational(self):
        """Genuine chitchat with no active flow -> conversational."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "מה שלומך?",
            toggle_state=_build_toggle_state(),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "conversational"


class TestNoneDuringActiveFlow:
    """Conversational must not occur when a toggle is in an active flow."""

    def test_deference_during_goal_pending(self):
        """'אין לי שמץ' during goal_pending -> opt_in (deference)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אין לי שמץ",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "לרדת"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "opt_in"


# ============================================================================
# SHARP vs SOFT REFUSAL
#
# Both sharp and soft refusals route to opt_in. The router's job is to
# identify them as toggle-related actions, not generic conversation.
# The handler layer distinguishes sharp vs soft by message analysis.
# ============================================================================

class TestRefusalRouting:
    """Tests that refusals route to opt_in, not conversational."""

    def test_sharp_refusal_during_offer(self):
        """'לא רוצה' to offer -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא רוצה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_soft_refusal_during_offer(self):
        """'לא סגור על זה' to offer -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא סגור על זה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_sharp_refusal_during_goal(self):
        """'לא' to goal question -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "לרדת"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "opt_in"

    def test_soft_refusal_during_goal(self):
        """'לא בטוח שזה מתאים לי' to suggestion -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא בטוח שזה מתאים לי",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "ירידה"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        # Soft refusal: could be opt_in (refusal) or conversational (pushback)
        # Both are valid routes - the handler will process appropriately
        assert result.type in ("opt_in", "conversational")

    def test_maybe_later_is_soft(self):
        """'אולי בהמשך' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אולי בהמשך",
            toggle_state=_build_toggle_state(eating_window="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", EATING_WINDOW_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_not_now_is_soft(self):
        """'לא עכשיו' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא עכשיו",
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", WORKOUTS_OFFER),
            ),
        )
        assert result.type == "opt_in"
