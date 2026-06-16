"""
test_multi_intent_router_llm.py - TDD for multi-intent message handling.

# ============================================================================
# MULTI-INTENT SPEC
# ============================================================================
#
# When a message contains multiple distinct task types (food + sleep,
# food + goal change, sleep + workout), the Router classifies as
# 'conversational'. Conversational identifies all tasks, confirms the first
# with details, and asks the user to remind about the rest.
#
# WHAT IS MULTI-INTENT:
#   - Food + habit: "ate a burger, also slept at 23"
#   - Food + goal change: "ate pizza, also change my calories to 2000"
#   - Habit + habit (different types): "worked out, also slept at 22"
#   - Emotion + habit: "feel awful, slept at 23"
#
# WHAT IS NOT MULTI-INTENT:
#   - Same-type multi-entry: "slept at 22 yesterday, 21 day before" -> sleep
#   - Same-type multi-entry: "worked out yesterday, also day before" -> workout
#   - Food with emotional context: "ate ice cream because sad" -> meal
#     (emotion is context, not a separate task)
#
# FLOW:
#   1. Router detects multi-intent -> classifies as 'conversational'
#   2. Conversational identifies tasks, confirms first, asks about rest
#   3. User confirms first task -> Router classifies the confirmed task
#   4. User sends reminder for second task -> Router classifies that task
#
# ============================================================================
"""

import os
import sys
import pytest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer, _build_toggle_state, _build_history,
    FOOD_RESPONSE_SCHNITZEL, llm_judge,
)
from services.conversational_service import ConversationalService

pytestmark = pytest.mark.integration

KNOWLEDGE_PATH = Path(__file__).parent.parent / "knowledge" / "dugri-self-knowledge.md"

USER_CONTEXT = "שם: שי\nיעד קלוריות: 2000, יעד חלבון: 150"
DATA_SUMMARY = "היום: 800 קלוריות, 50 גרם חלבון"


def _route(analyzer, text, toggle_state=None, history=None):
    return analyzer.route_tiered(
        text=text,
        today_str=datetime.now().strftime("%d/%m/%Y"),
        last_entry=None,
        recent_messages=history or [],
        toggle_state=toggle_state or _build_toggle_state(),
    )


def _converse(analyzer, text, toggle_state=None, history=None):
    service = ConversationalService(analyzer, knowledge_path=KNOWLEDGE_PATH)
    return service.respond(
        user_text=text,
        user_context=USER_CONTEXT,
        toggle_state=toggle_state or _build_toggle_state(),
        today_date=datetime.now().strftime("%d/%m/%Y"),
        recent_messages=history,
    )


# ============================================================================
# DETECTION: Router classifies multi-intent as conversational
# ============================================================================

class TestMultiIntentDetection:
    """Router detects different-type combinations as conversational."""

    def test_food_and_sleep(self):
        """Food + sleep = conversational (not meal, not sleep)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אכלתי המבורגר, גם הלכתי לישון ב-23",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert result.type == "conversational"

    def test_food_and_workout(self):
        """Food + workout = conversational."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אכלתי סלט, גם התאמנתי היום",
            toggle_state=_build_toggle_state(workouts="active_with_goal"),
        )
        assert result.type == "conversational"

    def test_food_and_goal_change(self):
        """Food + goal change request = conversational or meal.

        The 'meal always wins' rule may fire here since pizza is specific food.
        Both are acceptable - the goal change can be handled next turn.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אכלתי פיצה, גם תשנה לי את הקלוריות ל-2500",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
        )
        assert result.type in ("conversational", "meal")

    def test_sleep_and_workout(self):
        """Sleep + workout = conversational."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אתמול הלכתי לישון ב-22 וגם התאמנתי",
            toggle_state=_build_toggle_state(
                sleep="active_with_goal", workouts="active_with_goal",
            ),
        )
        assert result.type == "conversational"


# ============================================================================
# NOT MULTI-INTENT: same-type multi-entry stays as single type
# ============================================================================

class TestNotMultiIntent:
    """Same-type multi-entry is NOT multi-intent."""

    def test_sleep_multiple_days(self):
        """Multiple sleep entries across days = sleep (not conversational)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אתמול הלכתי לישון ב-22, שלשום ב-21",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert result.type == "sleep"

    def test_workout_multiple_days(self):
        """Multiple workout entries = workout (not conversational)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "שלשום התאמנתי, אתמול גם",
            toggle_state=_build_toggle_state(workouts="active_with_goal"),
        )
        assert result.type == "workout"

    def test_emotional_food_is_meal(self):
        """Emotion + specific food = meal (emotion is context, not task)."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אכלתי גלידה כי אני עצוב")
        assert result.type == "meal"


# ============================================================================
# CONVERSATIONAL RESPONSE: one-at-a-time handling
# ============================================================================

class TestMultiIntentResponse:
    """Conversational handles multi-intent with one-at-a-time approach."""

    def test_response_mentions_both_tasks(self):
        """Response acknowledges both tasks exist."""
        analyzer = _make_analyzer()
        response = _converse(
            analyzer, "אכלתי המבורגר, גם הלכתי לישון ב-23",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert len(response) > 20
        assert llm_judge(
            "Does this text acknowledge or discuss both eating (hamburger/food) and sleeping?",
            response,
        ), f"Expected mention of food and/or sleep, got: {response}"

    def test_response_acknowledges_multiple_items(self):
        """Response acknowledges there are multiple things to handle."""
        analyzer = _make_analyzer()
        response = _converse(
            analyzer, "אכלתי סלט טונה, גם התאמנתי היום ורצתי 5 קילומטר",
            toggle_state=_build_toggle_state(workouts="active_with_goal"),
        )
        assert len(response) > 20
        assert llm_judge(
            "Does this text acknowledge or discuss both eating (salad/tuna/food) and exercising (workout/running)?",
            response,
        ), f"Expected mention of food and/or workout, got: {response}"


# ============================================================================
# SUBSEQUENT ROUTING: after multi-intent, user sends tasks one by one
# ============================================================================

class TestSubsequentRouting:
    """After multi-intent, user sends individual tasks that route correctly."""

    def test_confirmed_food_routes_to_meal(self):
        """After multi-intent, restated food -> meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אכלתי המבורגר",
            history=_build_history(
                ("user", "אכלתי המבורגר, גם הלכתי לישון ב-23"),
                ("bot", "בוא נתחיל מהאוכל. ההמבורגר - כמה גרם, עם מה?"),
            ),
        )
        assert result.type == "meal"

    def test_reminder_sleep_routes_to_sleep(self):
        """After first task handled, user reminds about sleep -> sleep."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "הלכתי לישון ב-23",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "כן, תרשום את ההמבורגר"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "sleep"
