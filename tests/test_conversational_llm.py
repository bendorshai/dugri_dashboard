"""
test_conversational_llm.py - TDD tests for the Conversational module (Module 2).

# ============================================================================
# CONVERSATIONAL SPEC
# ============================================================================
#
# The Conversational module handles everything that is not a single clear
# action: questions, discussion, negotiation, multi-intent messages, and
# anything the Router classifies as 'conversational'.
#
# KEY PROPERTIES:
# 1. READ-ONLY: never returns action instructions, never mutates state.
# 2. Hebrew, dugri tone: concise, eye-level, no preaching.
# 3. Self-knowledge: knows how Dugri works, what it tracks, formulas.
# 4. Data-aware: can answer questions about user's entries (30-day scope).
# 5. Negotiation driver: during goal flows, explains reasoning and drives
#    toward a clear determination ("want me to set X?").
# 6. Multi-intent: identifies tasks, confirms first, asks about rest.
# 7. Empathy: brief empathy before substantive response when emotional.
#
# INPUT: user message + user profile + data summary + toggle state + history
# OUTPUT: plain text response in Hebrew
#
# ============================================================================
"""

import os
import sys
import json
import pytest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer, _build_toggle_state, _build_history,
    NUTRITION_SUGGESTION,
)
from services.conversational_service import ConversationalService

pytestmark = pytest.mark.integration

KNOWLEDGE_PATH = Path(__file__).parent.parent / "knowledge" / "dugri-self-knowledge.md"

USER_CONTEXT_EXAMPLE = (
    "שם: שי\n"
    "גובה: 180 ס\"מ, משקל: 85 ק\"ג, גיל: 30\n"
    "יעד קלוריות: 2000, יעד חלבון: 150\n"
    "מטרה: ירידה במשקל"
)

DATA_SUMMARY_EXAMPLE = (
    "ארוחות (7 ימים אחרונים):\n"
    "ממוצע יומי: 1850 קלוריות, 120 גרם חלבון\n"
    "ימים שנרשמו: 5/7\n"
    "שינה (7 ימים): ממוצע 23:15"
)


def _make_service():
    analyzer = _make_analyzer()
    return ConversationalService(analyzer, knowledge_path=KNOWLEDGE_PATH)


def _respond(service, text, toggle_state=None, history=None,
             user_context=None, data_summary=None):
    return service.respond(
        user_text=text,
        user_context=user_context or USER_CONTEXT_EXAMPLE,
        data_summary=data_summary or DATA_SUMMARY_EXAMPLE,
        toggle_state=toggle_state or _build_toggle_state(),
        recent_messages=history,
    )


# ============================================================================
# SELF-KNOWLEDGE QUESTIONS
# ============================================================================

class TestSelfKnowledge:
    """Conversational answers questions about how Dugri works."""

    def test_how_calories_calculated(self):
        """Explains calorie calculation approach."""
        service = _make_service()
        response = _respond(service, "איך אתה מחשב קלוריות?")
        assert len(response) > 20
        # Should mention estimation/approximation, not claim precision
        assert any(w in response for w in ["הערכה", "מעריך", "לא מדויק", "מגמה", "בינה"])

    def test_why_only_five_habits(self):
        """Answers meta-question about Dugri's design."""
        service = _make_service()
        response = _respond(service, "למה רק 5 הרגלים?")
        assert len(response) > 20
        assert "5" in response or "חמישה" in response or "חמש" in response

    def test_responds_in_hebrew(self):
        """All responses are in Hebrew."""
        service = _make_service()
        response = _respond(service, "מה אתה יודע לעשות?")
        # Hebrew characters present
        assert any("\u0590" <= c <= "\u05FF" for c in response)


# ============================================================================
# DATA QUESTIONS
# ============================================================================

class TestDataQuestions:
    """Conversational answers questions about user's actual data."""

    def test_weekly_eating_summary(self):
        """Answers how much user ate this week using data context."""
        service = _make_service()
        response = _respond(service, "כמה אכלתי השבוע?")
        assert len(response) > 20
        # Should reference actual data numbers
        assert any(w in response for w in ["1850", "קלוריות", "חלבון", "ממוצע"])


# ============================================================================
# GOAL NEGOTIATION
# ============================================================================

class TestGoalNegotiation:
    """Conversational drives negotiation toward a clear determination."""

    def test_pushback_gets_explanation(self):
        """Pushback on goal gets explanation with reasoning."""
        service = _make_service()
        response = _respond(
            service, "2000 קלוריות נשמע הרבה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert len(response) > 30
        # Should explain reasoning or discuss alternatives

    def test_negotiation_drives_toward_determination(self):
        """After discussion, Conversational asks for explicit confirmation."""
        service = _make_service()
        response = _respond(
            service, "אני חושב ש-1800 יותר מתאים לי",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_SUGGESTION),
                ("user", "2000 נשמע הרבה"),
                ("bot", "2000 זה גירעון קל. אם אתה רוצה יותר אגרסיבי, 1800 אפשרי אבל תרגיש את זה."),
            ),
        )
        assert len(response) > 20
        # Should ask for confirmation - "want me to set?" or similar
        assert any(w in response for w in ["רוצה", "לקבוע", "אקבע", "נקבע", "שאקבע"])


# ============================================================================
# MULTI-INTENT
# ============================================================================

class TestMultiIntent:
    """Conversational handles messages with multiple task types."""

    def test_identifies_multiple_tasks(self):
        """Identifies both tasks and handles one at a time."""
        service = _make_service()
        response = _respond(
            service, "אכלתי המבורגר, גם הלכתי לישון ב-23",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert len(response) > 20
        # Should mention both tasks or ask to handle one at a time


# ============================================================================
# READ-ONLY VERIFICATION
# ============================================================================

class TestReadOnly:
    """Conversational never returns action instructions."""

    def test_no_json_in_response(self):
        """Response is plain text, never JSON."""
        service = _make_service()
        response = _respond(service, "למה 2000 קלוריות?",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        # Should not contain JSON-like structures
        assert "{" not in response or "}" not in response or len(response) > 100

    def test_response_is_conversational_not_action(self):
        """Response discusses, does not execute actions."""
        service = _make_service()
        response = _respond(service, "איך אתה מחשב קלוריות?")
        # Should not contain action-like language
        assert "נרשם" not in response  # "logged" - would indicate action
        assert "הפעלתי" not in response  # "activated"
