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
# 4. Data-aware via on-demand tool: uses function calling to fetch history
#    only when user asks data questions. Casual chat = no data fetch.
# 5. Date-aware: knows today's date and day of week.
# 6. Negotiation driver: during goal flows, explains reasoning and drives
#    toward a clear determination ("want me to set X?").
# 7. Multi-intent: identifies tasks, confirms first, asks about rest.
# 8. Empathy: brief empathy before substantive response when emotional.
#
# INPUT: user message + user profile + toggle state + today_date + history
#        + fetch_history callback (called on demand by LLM)
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
from unittest.mock import MagicMock
from services.conversational_service import ConversationalService

pytestmark = pytest.mark.integration

KNOWLEDGE_PATH = Path(__file__).parent.parent / "knowledge" / "dugri-self-knowledge.md"

USER_CONTEXT_EXAMPLE = (
    "שם: שי\n"
    "גובה: 180 ס\"מ, משקל: 85 ק\"ג, גיל: 30\n"
    "יעד קלוריות: 2000, יעד חלבון: 150\n"
    "מטרה: ירידה במשקל"
)

TODAY_DATE_EXAMPLE = "13/06/2026 (יום שבת)"

FOOD_HISTORY_CSV = (
    "תאריך,שעה,תיאור,קלוריות,חלבון\n"
    "13/06/2026,08:00,ביצים ולחם,400,25\n"
    "13/06/2026,13:00,סלט עם חזה עוף,550,45\n"
    "12/06/2026,09:00,גרנולה עם יוגורט,350,15\n"
    "12/06/2026,14:00,פיצה,700,20\n"
    "12/06/2026,20:00,גלידה בן אנד ג'ריס,450,8"
)


def _make_service():
    analyzer = _make_analyzer()
    return ConversationalService(analyzer, knowledge_path=KNOWLEDGE_PATH)


def _make_history_fetcher(csv=FOOD_HISTORY_CSV):
    """Create a mock history fetcher that returns CSV data and tracks calls."""
    fetcher = MagicMock(return_value=csv)
    return fetcher


def _respond(service, text, toggle_state=None, history=None,
             user_context=None, today_date=None, fetch_history=None):
    return service.respond(
        user_text=text,
        user_context=user_context or USER_CONTEXT_EXAMPLE,
        toggle_state=toggle_state or _build_toggle_state(),
        today_date=today_date or TODAY_DATE_EXAMPLE,
        recent_messages=history,
        fetch_history=fetch_history,
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
# DATA QUESTIONS (on-demand via function calling)
# ============================================================================

class TestDataQuestions:
    """Conversational fetches history via tool only when user asks data questions."""

    def test_data_question_triggers_tool_call(self):
        """When user asks about food data, GPT calls the history tool."""
        service = _make_service()
        fetcher = _make_history_fetcher()
        response = _respond(service, "אכלתי גלידה אתמול?", fetch_history=fetcher)
        assert fetcher.called, "Expected history tool to be called for data question"
        assert len(response) > 10
        # Should reference the ice cream from the CSV
        assert any(w in response for w in ["גלידה", "בן אנד ג'ריס", "כן", "450"])

    def test_casual_chat_no_tool_call(self):
        """Simple chat does not trigger the history tool."""
        service = _make_service()
        fetcher = _make_history_fetcher()
        response = _respond(service, "מה נשמע?", fetch_history=fetcher)
        assert not fetcher.called, "History tool should NOT be called for casual chat"
        assert len(response) > 5

    def test_weekly_eating_question_triggers_tool(self):
        """Weekly questions trigger the tool and get data-based answers."""
        service = _make_service()
        fetcher = _make_history_fetcher()
        response = _respond(service, "כמה אכלתי השבוע?", fetch_history=fetcher)
        assert fetcher.called, "Expected history tool for weekly data question"
        assert len(response) > 20
        assert any(w in response for w in ["קלוריות", "חלבון"])


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


# ============================================================================
# DATE AWARENESS
# ============================================================================

class TestDateAwareness:
    """Conversational knows today's date and day of week."""

    def test_knows_today_date(self):
        """When asked what day it is, knows the answer."""
        service = _make_service()
        response = _respond(service, "מה התאריך היום?", today_date="13/06/2026 (יום שבת)")
        assert any(w in response for w in ["13", "שבת", "יוני", "שישי"])

    def test_uses_date_for_temporal_questions(self):
        """Uses date context for 'yesterday' type questions."""
        service = _make_service()
        fetcher = _make_history_fetcher()
        response = _respond(
            service, "מה אכלתי אתמול?",
            today_date="13/06/2026 (יום שבת)",
            fetch_history=fetcher,
        )
        assert fetcher.called
        assert len(response) > 10
