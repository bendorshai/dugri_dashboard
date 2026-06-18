"""
test_food_list_classification.py - Regression tests for food list misclassification.

Reproduces a production bug (2026-06-17) where a multi-line food list was
classified as 'conversational' instead of 'meal'. The conversational handler
then mimicked the meal format (bullet points, calories, daily summary) using
history context, making the bug invisible to the user -- but nothing was
actually saved. It also included אגוזי מלך from a previous entry in history
that wasn't in the user's message.

Uses exact production message history from 2026-06-17.
"""

import os
import sys
import pytest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer,
    _build_toggle_state,
    _build_history,
    _route,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Production history stubs (exact messages from 2026-06-17)
# ---------------------------------------------------------------------------

# Bot meal response with daily summary (Message 1)
PROD_MEAL_RESPONSE_DETAILED = (
    "• 5 פרובות פסטרמה\n"
    "  ~100 גרם | 250 קל׳ | 30 גרם חלבון\n"
    "• 2 ביצים\n"
    "  ~136 גרם | 180 קל׳ | 12 גרם חלבון\n"
    "• 3 שורות גבינת פטה\n"
    "  ~90 גרם | 240 קל׳ | 12 גרם חלבון\n"
    "• חופן חומוסים מטוגנים בשמן זית\n"
    "  ~50 גרם | 150 קל׳ | 5 גרם חלבון\n"
    "• חופן עגבניות שרי\n"
    "  ~100 גרם | 18 קל׳ | 1 גרם חלבון\n\n"
    'סה"כ: 838 קל׳ | 60 גרם חלבון\n\n'
    "📊 סיכום יומי:\n"
    "✅ קלוריות: 958/2000 (48%, נותרו: 1042)\n"
    "⚠️ גרם חלבון: 61/150 (41%, נותרו: 89)"
)

# Bot sleep opt-in offer (Message 2)
PROD_SLEEP_OFFER = (
    "אגב - בא לי להציע לך משהו חדש. אם תרשום לי מתי הלכת לישון, "
    "אני אעקוב איתך אחרי דפוס השינה. רוצה שננסה?"
)

# Bot sleep confirmation (Message 4)
PROD_SLEEP_CONFIRM = (
    "רשמתי שינה ב-06:00.\n\n"
    "קלטתי. השינה היא הדבר שהכי משפיע בלי שמרגישים - "
    "על הרעב למחרת, על האנרגיה, ועל הכוח להתמיד. "
    "עכשיו תראה את עצמך לאורך זמן."
)

# Bot walnut response (Message 6)
PROD_WALNUT_RESPONSE = (
    "• אגוזי מלך\n"
    "  ~30 גרם | 200 קל׳ | 5 גרם חלבון\n\n"
    "📊 סיכום יומי:\n"
    "✅ קלוריות: 1158/2000 (58%, נותרו: 842)\n"
    "⚠️ גרם חלבון: 66/150 (44%, נותרו: 84)"
)

# Conversational response that mimicked meal format (Message 8 - the broken response)
PROD_CONVERSATIONAL_MEAL_MIMIC = (
    "• חופן אגוזי מלך\n"
    "  ~30 גרם | 200 קל׳ | 5 גרם חלבון\n\n"
    "• שניצל חזיר\n"
    "  ~150 גרם | 400 קל׳ | 30 גרם חלבון\n\n"
    "• צ'יפס\n"
    "  ~150 גרם | 400 קל׳ | 4 גרם חלבון\n\n"
    "• מוסקה\n"
    "  ~200 גרם | 350 קל׳ | 15 גרם חלבון\n\n"
    "• טיפ טיפה סלט עלים\n"
    "  ~50 גרם | 10 קל׳ | 1 גרם חלבון\n\n"
    "• פרוסת עוגה\n"
    "  ~100 גרם | 300 קל׳ | 3 גרם חלבון\n\n"
    'סה"כ: 1660 קל׳ | 58 גרם חלבון\n\n'
    "📊 סיכום יומי:\n"
    "✅ קלוריות: 2680/2000 (134%, נותרו: -680)\n"
    "⚠️ גרם חלבון: 119/150 (79%, נותרו: 31)"
)


def _production_history_for_food_list():
    """Build the exact 6-message history that preceded the food list message."""
    return _build_history(
        ("bot", PROD_MEAL_RESPONSE_DETAILED),         # Message 1
        ("bot", PROD_SLEEP_OFFER),                     # Message 2
        ("user", "יאללה. הלכתי לישון ב6 לפנות בוקר"),   # Message 3
        ("bot", PROD_SLEEP_CONFIRM),                   # Message 4
        ("user", "חופן אגוזי מלך"),                     # Message 5
        ("bot", PROD_WALNUT_RESPONSE),                 # Message 6
    )


def _production_history_for_banana():
    """Build the exact 10-message history that preceded 'אתמול ב 18:00 בננה'.

    This is the full production history from 2026-06-17 including the
    misclassified food list and the workout report that followed it.
    """
    return _build_history(
        # Meal: detailed pastrami/eggs/feta response
        ("bot", PROD_MEAL_RESPONSE_DETAILED),
        # Sleep offer
        ("bot", PROD_SLEEP_OFFER),
        # User accepts sleep + reports sleep time
        ("user", "יאללה. הלכתי לישון ב6 לפנות בוקר"),
        # Bot confirms sleep
        ("bot", PROD_SLEEP_CONFIRM),
        # User reports walnuts
        ("user", "חופן אגוזי מלך"),
        # Bot meal response for walnuts
        ("bot", PROD_WALNUT_RESPONSE),
        # User sends food list (was misclassified as conversational!)
        ("user", "שניצל חזיר\nצ'יפס\nמוסקה\nטיפ טיפה סלט עלים\nפרוסת עוגה"),
        # Bot's broken conversational response (mimicked meal format)
        ("bot", PROD_CONVERSATIONAL_MEAL_MIMIC),
        # User reports workout
        ("user", "הלכתי היום שעה ברגל"),
        # Bot confirms workout
        ("bot", "רשמתי אימון."),
    )


# ============================================================================
# FOOD LIST MISCLASSIFICATION TESTS
# ============================================================================

class TestFoodListClassification:
    """Food lists must classify as meal, not conversational.

    Production bug 2026-06-17: a multi-line food list was classified as
    'conversational'. The conversational handler used history context
    to generate a response that looked exactly like a meal log (with daily
    summary, calories, protein) -- but nothing was saved to the database.
    It also included אגוזי מלך from a previous entry in history.
    """

    def test_multiline_food_list_with_heavy_history(self):
        """Exact production scenario: 5 foods on separate lines, 6 msgs history.

        This is the exact message and context from the 2026-06-17 bug.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "שניצל חזיר\nצ'יפס\nמוסקה\nטיפ טיפה סלט עלים\nפרוסת עוגה",
            history=_production_history_for_food_list(),
        )
        assert result.type == "meal", (
            f"Multi-line food list classified as '{result.type}' instead of 'meal'. "
            "Iron rule: specific food names = meal, always."
        )

    def test_multiline_food_list_without_history(self):
        """Same food list without history -- should also be meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "שניצל חזיר\nצ'יפס\nמוסקה\nטיפ טיפה סלט עלים\nפרוסת עוגה",
        )
        assert result.type == "meal"

    def test_comma_separated_food_list(self):
        """Food items separated by commas."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "שניצל חזיר, צ'יפס, מוסקה, סלט עלים, פרוסת עוגה",
        )
        assert result.type == "meal"

    def test_bare_food_name_no_prefix(self):
        """Single food name without 'אכלתי' prefix."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "שניצל עם צ'יפס")
        assert result.type == "meal"

    def test_retroactive_food_with_timestamp(self):
        """Food report with 'yesterday' and a time -- meal, not a question.

        Production bug: 'אתמול ב 18:00 בננה' was classified as conversational.
        Uses minimal history.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "אתמול ב 18:00 בננה",
            history=_production_history_for_food_list(),
        )
        assert result.type == "meal", (
            f"Retroactive food with timestamp classified as '{result.type}'. "
            "Reporting food at a past time = meal, not a question."
        )

    def test_retroactive_food_without_history(self):
        """Retroactive food without history context."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אתמול ב 18:00 בננה")
        assert result.type == "meal"

    def test_retroactive_banana_with_full_production_history(self):
        """Exact production scenario for banana misclassification.

        Production bug 2026-06-17: 'אתמול ב 18:00 בננה' was classified as
        'conversational' after 10 messages of heavy history including:
        - A detailed meal log (pastrami, eggs, feta, hummus, tomatoes)
        - A sleep offer + acceptance + confirmation
        - A walnut meal entry
        - A misclassified food list (שניצל חזיר...) and its broken response
        - A workout report + confirmation

        The bot's response was: "קלטתי שהלכת שעה ברגל - זה מצוין! לגבי הבננה,
        אני לא יכול לרשום את זה עכשיו..." -- treating a clear food report as
        a conversation and refusing to log it.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "אתמול ב 18:00 בננה",
            history=_production_history_for_banana(),
        )
        assert result.type == "meal", (
            f"Retroactive banana with full production history classified as "
            f"'{result.type}' instead of 'meal'. "
            "The message 'אתמול ב 18:00 בננה' is a retroactive food report "
            "(date + time + specific food name), not a question."
        )
