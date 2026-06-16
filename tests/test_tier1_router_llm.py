"""
test_tier1_router_llm.py - TDD tests for the Tier 1 Intent Router.

# ============================================================================
# TIER 1 SPEC
# ============================================================================
#
# The Tier 1 router is the first LLM call for every user message. It answers
# ONE question: "what broad category does this message belong to?"
#
# It is PURELY CONTEXTUAL - it uses message text and conversation history
# but receives NO toggle state. Toggle state is deferred to tier 2.
#
# OUTPUT MODEL: Tier1Classification
#   type: "meal" | "habit_logger" | "goals_talk" | "other"
#   (classification only, no extraction - meal extraction is tier 2)
#
# TYPES:
#   meal   - food description. Includes emotional-meal ("ate ice cream because
#            I'm sad" = meal). Extracted inline with calories/protein/time.
#            One call, done. No tier 2.
#   logger - user is reporting a habit (sleep time, workout, self-care) OR
#            correcting a previous food entry. Tier 2 sub-classifies.
#   opt_in - user is responding to a bot offer/suggestion about goals or
#            toggles. Detected from conversation history (bot's last message
#            was an offer/question about tracking). Tier 2 sub-classifies.
#   other  - everything else: questions, conversation, name/gender declaration,
#            feature requests, pure emotion, inappropriate. Tier 2 sub-classifies.
#
# KEY ROUTING RULES:
# 1. Meal always wins - specific food item name = meal, always.
# 2. Emotional-meal = meal. "Ate ice cream because sad" has a food item -> meal.
#    "Ate a lot" with no specific item -> other (emotional, no food to log).
# 3. Logger = factual habit report. "Slept at 23", "worked out", "went to spa".
#    Also correction: "without rice", "it was smaller" (references last_entry).
# 4. Opt_in = response to a bot offer/question about tracking. Detected from
#    conversation history: bot offered to track something, user responds.
#    Short affirmatives ("yalla", "yes"), refusals ("no", "leave it"),
#    values ("2500 and 200"), hesitation ("not sure") - all opt_in when
#    the bot's last message was an offer.
# 5. Other = catch-all. Questions, chat, name declaration, feature requests,
#    pure emotion, inappropriate.
#
# HARD EDGE - "23:00" AMBIGUITY:
#   Resolved from history alone:
#   - Bot asked "מתי אתה רוצה ללכת לישון?" (goal question) -> opt_in
#   - No such bot question in history -> logger (sleep report)
#
# ============================================================================
"""

import os
import sys
import pytest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer, _build_history,
    NUTRITION_OFFER, NUTRITION_SUGGESTION, BODY_STATS_ASK,
    SLEEP_OFFER, SLEEP_GOAL_ASK, WORKOUTS_OFFER, SELF_CARE_OFFER,
    EATING_WINDOW_OFFER, GOAL_REMIND_ASK,
    FOOD_RESPONSE_SCHNITZEL,
)

pytestmark = pytest.mark.integration


def _tier1(analyzer, text, history=None, last_entry=None, reply_context=None):
    """Route through tier 1 only. No toggle state."""
    return analyzer.route_tier1(
        text=text,
        today_str=datetime.now().strftime("%d/%m/%Y"),
        last_entry=last_entry,
        recent_messages=history or [],
        reply_context=reply_context,
    )


# ============================================================================
# MEAL - food descriptions, inline extraction
# ============================================================================

class TestTier1Meal:
    """Food descriptions -> meal (classification only, no extraction)."""

    def test_simple_food(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "אכלתי שניצל עם אורז")
        assert result.type == "meal"

    def test_food_with_emotion(self):
        """Iron rule: specific food + emotion = meal."""
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "אכלתי גלידה כי אני עצוב")
        assert result.type == "meal"

    def test_coffee(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "שתיתי קפה עם חלב")
        assert result.type == "meal"

    def test_food_during_bot_offer(self):
        """Meal always wins even when bot just offered something."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "אכלתי פיצה",
            history=_build_history(("bot", SLEEP_OFFER)),
        )
        assert result.type == "meal"

    def test_food_during_goal_question(self):
        """Meal always wins even during goal-setting conversation."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "שתיתי קפה עם חלב",
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "meal"

    def test_hamburger(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "המבורגר עם צ'יפס")
        assert result.type == "meal"


# ============================================================================
# LOGGER - habit reports and corrections
# ============================================================================

class TestTier1Logger:
    """Habit reports and corrections -> logger."""

    def test_sleep_report(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "הלכתי לישון ב-23")
        assert result.type == "habit_logger"

    def test_workout_report(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "התאמנתי היום")
        assert result.type == "habit_logger"

    def test_self_care_report(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "הלכתי לים היום")
        assert result.type == "habit_logger"

    def test_yoga_workout(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "עשיתי יוגה בבוקר")
        assert result.type == "habit_logger"

    def test_correction(self):
        """Correction of last entry -> logger."""
        analyzer = _make_analyzer()
        last_entry = {
            "description": "שניצל עם אורז",
            "calories": 650,
            "protein": 35,
        }
        result = _tier1(analyzer, "בלי אורז", last_entry=last_entry)
        assert result.type == "habit_logger"

    def test_correction_smaller(self):
        analyzer = _make_analyzer()
        last_entry = {
            "description": "המבורגר עם צ'יפס",
            "calories": 800,
            "protein": 40,
        }
        result = _tier1(analyzer, "היה יותר קטן", last_entry=last_entry)
        assert result.type == "habit_logger"

    def test_multi_date_sleep(self):
        """Same habit, multiple dates = still logger (not other)."""
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "אתמול הלכתי לישון ב-22, שלשום ב-21")
        assert result.type == "habit_logger"

    def test_confirm_log_suggestion(self):
        """Bot asked 'want to log this as a workout?' -> 'OK' = logger (not opt_in).

        The bot is asking to RECORD something that already happened.
        This is logging, not activating a new tracking feature.
        """
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "אוקיי",
            history=_build_history(
                ("user", "רצתי אתמול בים"),
                ("bot", "נשמע כיף! רוצה לתעד את זה כאימון?"),
            ),
        )
        assert result.type == "habit_logger"


# ============================================================================
# OPT_IN - responses to bot offers (contextual from history)
# ============================================================================

class TestTier1OptIn:
    """Responses to bot offers/questions -> opt_in."""

    def test_yalla_after_offer(self):
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "יאללה",
            history=_build_history(
                ("user", "אכלתי שניצל"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "goals_talk"

    def test_yes_after_offer(self):
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "כן",
            history=_build_history(
                ("user", "אכלתי שניצל"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", WORKOUTS_OFFER),
            ),
        )
        assert result.type == "goals_talk"

    def test_sababa_after_offer(self):
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "סבבה",
            history=_build_history(
                ("user", "אכלתי שניצל"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "goals_talk"

    def test_refuse_after_offer(self):
        """Refusal is still opt_in - it's a toggle decision."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "לא, עזוב",
            history=_build_history(
                ("user", "אכלתי שניצל"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "goals_talk"

    def test_hesitation_after_offer(self):
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "לא בטוח",
            history=_build_history(
                ("user", "אכלתי שניצל"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SELF_CARE_OFFER),
            ),
        )
        assert result.type == "goals_talk"

    def test_values_after_goal_question(self):
        """Providing goal values after bot asked = opt_in."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "2500 קלוריות ו-200 גרם חלבון",
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "יאללה"),
                ("bot", BODY_STATS_ASK),
                ("user", "180 סנטימטר, 85 קילו, בן 30"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "goals_talk"

    def test_time_after_sleep_goal_question(self):
        """Hard edge: '23:00' after bot asked sleep goal = opt_in."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "23:00",
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "יאללה"),
                ("bot", SLEEP_GOAL_ASK),
            ),
        )
        assert result.type == "goals_talk"

    def test_deference_after_offer(self):
        """'You decide' after bot suggested values = opt_in (cooperation)."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "תחליט אתה",
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "יאללה"),
                ("bot", BODY_STATS_ASK),
                ("user", "180 סנטימטר, 85 קילו, בן 30"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "goals_talk"

    def test_short_affirmative_after_suggestion(self):
        """'OK' after bot suggested calorie/protein values = opt_in."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "אוקיי",
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "יאללה"),
                ("bot", BODY_STATS_ASK),
                ("user", "180 סנטימטר, 85 קילו, בן 30"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "goals_talk"

    def test_remind_later_response(self):
        """Response to 'want me to remind you later?' = opt_in."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "כן",
            history=_build_history(("bot", GOAL_REMIND_ASK)),
        )
        assert result.type == "goals_talk"


# ============================================================================
# OTHER - everything else
# ============================================================================

class TestTier1Other:
    """Questions, chat, emotions, declarations, etc. -> other."""

    def test_question_about_data(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "כמה אכלתי השבוע?")
        assert result.type == "other"

    def test_general_chat(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "מה דעתך על צום לסירוגין?")
        assert result.type == "other"

    def test_pure_emotion(self):
        """Pure emotion without specific food = other (not meal)."""
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "יום קשה היום")
        assert result.type == "other"

    def test_vague_eating_emotion(self):
        """'Ate a lot' with no food item = other (emotional)."""
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "אכלתי המון")
        assert result.type == "other"

    def test_name_declaration(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "קוראים לי שי")
        assert result.type == "other"

    def test_feature_request(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "אפשר להוסיף מעקב שתיית מים?")
        assert result.type == "other"

    def test_feedback_request(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "תן לי סיכום שבועי")
        assert result.type == "other"

    def test_inappropriate(self):
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "לך תזדיין")
        assert result.type == "other"

    def test_negotiation_after_suggestion(self):
        """Pushback without values = other (conversational), not opt_in."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "2000 נשמע הרבה",
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "other"

    def test_question_after_suggestion(self):
        """Question about suggestion = other, not opt_in."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "למה 1800?",
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "other"

    def test_proactive_tracking_request(self):
        """User-initiated 'I want to track sleep' with no prior offer = other.
        (Tier 2 will sub-classify as opt_in with toggle context.)"""
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "אני רוצה לעקוב אחרי שינה")
        assert result.type == "goals_talk"

    def test_reply_to_food_confirmation(self):
        """Replying to food confirmation with a question = other."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "תודה",
            reply_context=FOOD_RESPONSE_SCHNITZEL,
        )
        assert result.type == "other"

    def test_new_food_as_reply_to_confirmation(self):
        """New food item as reply to food confirmation = meal (always wins)."""
        analyzer = _make_analyzer()
        result = _tier1(
            analyzer, "וגם שתיתי קולה",
            reply_context=FOOD_RESPONSE_SCHNITZEL,
        )
        assert result.type == "meal"


# ============================================================================
# MULTI-INTENT - different habit types = other
# ============================================================================

class TestTier1MultiIntent:
    """Messages with multiple habit types -> other (conversational)."""

    def test_food_and_sleep(self):
        """Food + sleep in same message = other (multi-intent)."""
        analyzer = _make_analyzer()
        result = _tier1(analyzer, "אכלתי המבורגר, גם הלכתי לישון ב-23")
        assert result.type == "other"
