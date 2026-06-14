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
# 9. Data-accurate: when data is fetched, the response must reflect the
#    actual entries, not hallucinated data. Dates are labeled with Hebrew
#    day names so the LLM can match temporal references without arithmetic.
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
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer, _build_toggle_state, _build_history,
    NUTRITION_SUGGESTION,
)
from unittest.mock import MagicMock
from services.conversational_service import ConversationalService
from models.food import FoodEntry

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


# ============================================================================
# DATA ACCURACY (end-to-end with stubbed food entries)
# ============================================================================
#
# These tests verify that the conversational handler correctly retrieves and
# reports food history data. Unlike the TestDataQuestions tests above (which
# use a mock fetcher returning hardcoded CSV), these tests use a FakeRepo
# with real FoodEntry objects and the actual fetch_history date-range logic.
#
# This catches bugs where the LLM requests the wrong number of days or where
# the date-range computation silently excludes the needed dates.
#
# Test data layout (today = 14/06/2026, Sunday):
#   Today (14/06):      eggs+bread (400cal/25p), chicken salad (550cal/45p)
#   Yesterday (13/06):  granola (350cal/15p), pizza (700cal/20p),
#                        Ben&Jerry's ice cream (450cal/8p)
#   3 days ago (11/06): shakshuka (350cal/20p)
#   Monday (08/06):     shawarma (800cal/40p), hummus (300cal/12p)
#   8 days ago (06/06): protein shake (200cal/40p), steak+rice (700cal/50p)
#
# ============================================================================

TID = 12345
# Today is Sunday 14/06/2026 - last Monday was 08/06/2026
DATA_TODAY = "14/06/2026"
DATA_TODAY_DISPLAY = "14/06/2026 (יום ראשון)"


class _FakeRepo:
    """In-memory food repository for conversational data accuracy tests."""

    def __init__(self, entries: list[FoodEntry]):
        self._entries = entries

    def get_by_user_and_dates(
        self, telegram_user_id: int, dates: list[str],
    ) -> list[FoodEntry]:
        return [
            e for e in self._entries
            if e.date in dates and e.telegram_user_id == telegram_user_id
        ]


def _entry(date: str, time: str, desc: str, cal: int, prot: int) -> FoodEntry:
    return FoodEntry(
        telegram_user_id=TID, date=date, time=time,
        description=desc, calories=cal, protein=prot,
    )


def _build_test_entries() -> list[FoodEntry]:
    """Build realistic multi-day food entries for data accuracy tests."""
    today = datetime.strptime(DATA_TODAY, "%d/%m/%Y").date()
    fmt = "%d/%m/%Y"
    d0 = today.strftime(fmt)                              # today (14/06)
    d1 = (today - timedelta(days=1)).strftime(fmt)         # yesterday (13/06)
    d3 = (today - timedelta(days=3)).strftime(fmt)         # 3 days ago (11/06)
    d6 = (today - timedelta(days=6)).strftime(fmt)         # Monday (08/06)
    d8 = (today - timedelta(days=8)).strftime(fmt)         # 8 days ago (06/06)

    return [
        # Today
        _entry(d0, "08:00", "ביצים ולחם", 400, 25),
        _entry(d0, "13:00", "סלט עם חזה עוף", 550, 45),
        # Yesterday
        _entry(d1, "09:00", "גרנולה עם יוגורט", 350, 15),
        _entry(d1, "13:00", "פיצה", 700, 20),
        _entry(d1, "21:00", "גלידה בן אנד ג'ריס", 450, 8),
        # 3 days ago
        _entry(d3, "10:00", "שקשוקה", 350, 20),
        # Monday (6 days ago)
        _entry(d6, "12:00", "שווארמה בפיתה", 800, 40),
        _entry(d6, "18:00", "חומוס עם פיתה", 300, 12),
        # 8 days ago
        _entry(d8, "07:00", "שייק חלבון", 200, 40),
        _entry(d8, "19:00", "סטייק עם אורז", 700, 50),
    ]


def _build_fetch_history(entries: list[FoodEntry], today_str: str):
    """Build a fetch_history closure using FakeRepo - mirrors handlers/base.py:779-789."""
    repo = _FakeRepo(entries)

    def fetch_history(days: int) -> str:
        today = datetime.strptime(today_str, "%d/%m/%Y").date()
        # +1 buffer matching production code in handlers/base.py
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(days + 1)]
        found = repo.get_by_user_and_dates(TID, dates)
        if not found:
            return "אין נתונים לתקופה המבוקשת."
        # Label dates so the LLM doesn't need date arithmetic
        heb_days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        day_labels = {}
        for offset in range(days + 1):
            d = today - timedelta(days=offset)
            ds = d.strftime("%d/%m/%Y")
            if offset == 0:
                day_labels[ds] = "היום"
            elif offset == 1:
                day_labels[ds] = "אתמול"
            else:
                day_labels[ds] = f"יום {heb_days[d.weekday()]}"
        lines = ["תאריך,יום,שעה,תיאור,קלוריות,חלבון"]
        for e in found:
            label = day_labels.get(e.date, e.date)
            lines.append(f"{e.date},{label},{e.time},{e.description},{e.calories},{e.protein}")
        return "\n".join(lines)

    return fetch_history


class TestDataAccuracy:
    """Conversational returns correct, data-backed answers using real date logic.

    These tests use a FakeRepo with stubbed FoodEntry objects and the actual
    fetch_history date-range logic (not a mock). The LLM must request the
    right number of days AND the response must reference the actual data.
    """

    def setup_method(self):
        self.service = _make_service()
        self.entries = _build_test_entries()
        self.fetcher = _build_fetch_history(self.entries, DATA_TODAY)

    def test_yesterday_food_found(self):
        """Asking 'what did I eat yesterday' returns yesterday's entries.

        This is the exact bug scenario: if LLM sends days=1, only today is
        fetched and the bot wrongly says 'no data'. With the fix, days>=2
        is sent and yesterday's entries are found.
        """
        response = _respond(
            self.service, "מה אכלתי אתמול?",
            today_date=DATA_TODAY_DISPLAY,
            fetch_history=self.fetcher,
        )
        # Must mention at least 2 of yesterday's 3 items
        found = sum(1 for w in ["גרנולה", "פיצה", "גלידה"] if w in response)
        assert found >= 2, f"Expected >=2 of yesterday's foods, found {found}. Response: {response}"

    def test_sweets_yesterday(self):
        """Asking 'did I eat sweets yesterday' finds the ice cream."""
        response = _respond(
            self.service, "אכלתי ממתקים אתמול?",
            today_date=DATA_TODAY_DISPLAY,
            fetch_history=self.fetcher,
        )
        assert any(w in response for w in ["גלידה", "בן אנד ג'ריס", "כן", "ממתקים", "450"]), \
            f"Expected ice cream mention. Response: {response}"

    def test_specific_day_name(self):
        """Asking 'what did I eat on Monday' resolves to the correct date.

        Today is Sunday 14/06/2026, so last Monday was 08/06/2026.
        Entries on that date: shawarma (800cal) and hummus (300cal).
        """
        response = _respond(
            self.service, "מה אכלתי ביום שני?",
            today_date=DATA_TODAY_DISPLAY,
            fetch_history=self.fetcher,
        )
        assert any(w in response for w in ["שווארמה", "שוורמה", "חומוס", "800", "300"]), \
            f"Expected Monday's foods. Response: {response}"

    def test_highest_calorie_meal(self):
        """Asking for highest calorie meal in past 10 days finds shawarma (800cal).

        The shawarma at 800cal is the single highest-calorie entry across all
        test data. The LLM must fetch enough days and identify the max.
        """
        response = _respond(
            self.service, "מה הארוחה הכי קלורית ב-10 ימים האחרונים?",
            today_date=DATA_TODAY_DISPLAY,
            fetch_history=self.fetcher,
        )
        assert any(w in response for w in ["שווארמה", "שוורמה", "800"]), \
            f"Expected shawarma/800cal. Response: {response}"

    def test_weekly_protein(self):
        """Asking about weekly protein returns a plausible total.

        Last 7 days (days 0-6) protein sum: 25+45+15+20+8+20+40+12 = 185g.
        The LLM should report a number in the ballpark.
        """
        response = _respond(
            self.service, "כמה חלבון אכלתי השבוע?",
            today_date=DATA_TODAY_DISPLAY,
            fetch_history=self.fetcher,
        )
        assert any(w in response for w in ["חלבון", "גרם"]), \
            f"Expected protein mention. Response: {response}"
        # Check that some reasonable number appears (100-250 range)
        import re
        numbers = [int(n) for n in re.findall(r'\d+', response) if 50 < int(n) < 500]
        assert len(numbers) > 0, f"Expected a protein total number. Response: {response}"

    def test_no_data_for_empty_period(self):
        """Asking about a period with no entries at all gets an honest answer.

        An empty repo means the tool returns 'no data' for any period.
        """
        empty_fetcher = _build_fetch_history([], DATA_TODAY)
        response = _respond(
            self.service, "מה אכלתי אתמול?",
            today_date=DATA_TODAY_DISPLAY,
            fetch_history=empty_fetcher,
        )
        assert any(w in response for w in ["אין", "לא נמצא", "לא מצאתי", "אין לי", "לא היו", "לא רשמת", "לא תיעדת", "לא דיווחת", "נתונים"]), \
            f"Expected 'no data' indication. Response: {response}"
