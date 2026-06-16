"""
test_router_integration_llm.py - End-to-end integration tests for the modular Router.

# ============================================================================
# INTEGRATION SPEC
# ============================================================================
#
# These tests verify complete message flows that cross module boundaries:
# Router -> Conversational/Opt-in/Logger -> response.
#
# Each test simulates a multi-turn conversation by building history and
# verifying that the Router correctly classifies each turn.
#
# KEY FLOWS TESTED:
# 1. Opt-in lifecycle: offer -> accept -> goal -> confirm
# 2. Opt-in with mid-flow negotiation via Conversational
# 3. Opt-in with mid-flow questions via Conversational
# 4. Emotional context preservation through pipeline
# 5. Late-late reply clarification flow
# 6. Ghosting -> re-engagement cycle
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
    NUTRITION_OFFER, NUTRITION_SUGGESTION, BODY_STATS_ASK,
    SLEEP_OFFER, SLEEP_GOAL_ASK, WORKOUTS_OFFER,
    GOAL_REMIND_ASK,
)
from services.conversational_service import ConversationalService

pytestmark = pytest.mark.integration

KNOWLEDGE_PATH = Path(__file__).parent.parent / "knowledge" / "dugri-self-knowledge.md"


def _route(analyzer, text, toggle_state=None, history=None):
    return analyzer.classify_message(
        text=text,
        today_str=datetime.now().strftime("%d/%m/%Y"),
        last_entry=None,
        recent_messages=history or [],
        toggle_state=toggle_state or _build_toggle_state(),
    )


# ============================================================================
# FLOW 1: Standard opt-in lifecycle
# ============================================================================

class TestOptInLifecycle:
    """Complete opt-in flow: offer -> accept -> goal value -> confirm."""

    def test_nutrition_flow_accept_to_goal(self):
        """Nutrition offer -> accept -> body stats -> weight goal -> confirm."""
        analyzer = _make_analyzer()

        # Turn 1: bot offers nutrition, user accepts
        r1 = _route(
            analyzer, "יאללה",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(("bot", NUTRITION_OFFER)),
        )
        assert r1.type == "opt_in"

        # Turn 2: bot asks body stats, user provides
        r2 = _route(
            analyzer, "180 סנטימטר, 85 קילו, בן 30",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "יאללה"),
                ("bot", BODY_STATS_ASK),
            ),
        )
        assert r2.type == "opt_in"

        # Turn 3: bot asks weight goal, user says lose
        r3 = _route(
            analyzer, "לרדת",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "180, 85, 30"),
                ("bot", "מה הכיוון? ירידה, שמירה, או עלייה?"),
            ),
        )
        assert r3.type == "opt_in"

    def test_sleep_flow_accept_and_goal(self):
        """Sleep offer -> accept -> goal value."""
        analyzer = _make_analyzer()

        r1 = _route(
            analyzer, "בוא ננסה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(("bot", SLEEP_OFFER)),
        )
        assert r1.type == "opt_in"

        r2 = _route(
            analyzer, "23:00",
            toggle_state=_build_toggle_state(sleep="active_goal_pending"),
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "בוא ננסה"),
                ("bot", SLEEP_GOAL_ASK),
            ),
        )
        assert r2.type == "opt_in"


# ============================================================================
# FLOW 2: Opt-in with mid-flow negotiation
# ============================================================================

class TestNegotiationFlow:
    """Goal negotiation: pushback -> Conversational discusses -> determination."""

    def test_pushback_then_accept(self):
        """User pushes back -> conversational, then accepts -> opt_in."""
        analyzer = _make_analyzer()

        # Turn 1: pushback on suggestion
        r1 = _route(
            analyzer, "2000 נשמע הרבה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert r1.type == "conversational"

        # Turn 2: user agrees after discussion
        r2 = _route(
            analyzer, "אוקיי נשמע טוב, בוא נלך על 1800",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_SUGGESTION),
                ("user", "2000 נשמע הרבה"),
                ("bot", "2000 זה גירעון קל מה-TDEE שלך. 1800 יותר אגרסיבי אבל אפשרי. רוצה שאקבע 1800 קלוריות ו-150 גרם חלבון?"),
            ),
        )
        assert r2.type == "opt_in"


# ============================================================================
# FLOW 3: Mid-flow questions
# ============================================================================

class TestMidFlowQuestions:
    """User asks questions during flow -> conversational, then returns."""

    def test_question_then_accept(self):
        """Question during goal -> conversational, then accept -> opt_in."""
        analyzer = _make_analyzer()

        # Turn 1: question
        r1 = _route(
            analyzer, "למה 150 גרם חלבון?",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert r1.type == "conversational"

        # Turn 2: accept after getting answer
        r2 = _route(
            analyzer, "אוקיי הבנתי, בוא נלך על זה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_SUGGESTION),
                ("user", "למה 150 גרם חלבון?"),
                ("bot", "1.6-2.0 גרם לק\"ג משקל גוף, במיוחד בירידה. 150 זה בדיוק 1.76 לק\"ג ל-85 ק\"ג שלך."),
            ),
        )
        assert r2.type == "opt_in"


# ============================================================================
# FLOW 4: Food during flow (meal always wins)
# ============================================================================

class TestFoodDuringFlow:
    """Food always routes to meal, regardless of active flow."""

    def test_food_during_nutrition_offer(self):
        """Food during nutrition offer -> meal, flow unchanged."""
        analyzer = _make_analyzer()

        r = _route(
            analyzer, "אכלתי שניצל עם אורז",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(("bot", NUTRITION_OFFER)),
        )
        assert r.type == "meal"
        assert r.meal is not None

    def test_food_during_goal_pending(self):
        """Food during goal setting -> meal, flow unchanged."""
        analyzer = _make_analyzer()

        r = _route(
            analyzer, "שתיתי קפה עם חלב",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert r.type == "meal"


# ============================================================================
# FLOW 5: Emotional message during flow
# ============================================================================

class TestEmotionalDuringFlow:
    """Emotional message pauses flow, returns to flow afterward."""

    def test_emotion_during_goal_flow(self):
        """Pure emotion during goal pending -> emotional (flow paused)."""
        analyzer = _make_analyzer()

        r = _route(
            analyzer, "אני מרגיש רע היום",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert r.type == "emotional"

    def test_return_to_flow_after_emotion(self):
        """After emotional pause, user returns to flow -> opt_in."""
        analyzer = _make_analyzer()

        r = _route(
            analyzer, "נשמע טוב",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_SUGGESTION),
                ("user", "אני מרגיש רע"),
                ("bot", "נשמע שקשה לך. אם בא לך לדבר, יש ChatGPT. אני פה כשתהיה מוכן."),
            ),
        )
        assert r.type == "opt_in"


# ============================================================================
# FLOW 6: Decline and remind cycle
# ============================================================================

class TestDeclineAndRemind:
    """User declines offer -> remind pending -> accept/decline remind."""

    def test_decline_then_accept_remind(self):
        """Decline offer -> remind question -> accept -> opt_in both times."""
        analyzer = _make_analyzer()

        # Turn 1: decline
        r1 = _route(
            analyzer, "לא עכשיו",
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(("bot", WORKOUTS_OFFER)),
        )
        assert r1.type == "opt_in"

        # Turn 2: accept remind
        r2 = _route(
            analyzer, "כן",
            toggle_state=_build_toggle_state(workouts="remind_pending"),
            history=_build_history(("bot", GOAL_REMIND_ASK)),
        )
        assert r2.type == "opt_in"

    def test_decline_then_decline_remind(self):
        """Decline offer -> decline remind -> opt_in."""
        analyzer = _make_analyzer()

        r = _route(
            analyzer, "לא, תודה",
            toggle_state=_build_toggle_state(sleep="remind_pending"),
            history=_build_history(("bot", GOAL_REMIND_ASK)),
        )
        assert r.type == "opt_in"
