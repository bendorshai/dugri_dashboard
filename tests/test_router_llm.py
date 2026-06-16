"""
test_router_llm.py - TDD tests for the slim Router (Module 1).

# ============================================================================
# ROUTER SPEC
# ============================================================================
#
# The Router is the first LLM call for every user message. It classifies the
# message type and extracts food data inline for type=meal. For all other
# types, only the type and optional toggle_name are returned.
#
# OUTPUT MODEL: RouterClassification
#   type: one of 12 types (see below)
#   meal: MealResult | None (only for type=meal)
#   toggle_name: str | None (for opt_in, identifies which habit)
#
# TYPES:
#   meal          - food description, default when no other context
#   opt_in        - clear toggle-related action (accept, refuse, values, initiate)
#   correction    - fix last entry
#   name_declaration - user declares their name
#   sleep         - sleep time report (NOT goal - goal during flow = opt_in)
#   workout       - workout report
#   self_care     - self-care activity report
#   emotional     - pure emotion with no specific food/habit action
#   feedback_request - asks for weekly summary
#   feedback_reaction - reacts to weekly feedback
#   conversational - questions, discussion, negotiation without values,
#                    multi-intent, ambiguous, catch-all
#   inappropriate - abuse, violence, trolling
#
# KEY ROUTING RULES:
# 1. Toggle state is the primary routing signal.
# 2. Meal always wins - specific food = meal regardless of toggle state.
# 3. opt_in = clear action + clear values (or clear accept/refuse).
# 4. conversational = discussion, questions, pushback without values,
#    multi-intent, ambiguous with multiple offered.
# 5. Multi-intent (different task types in one message) = conversational.
# 6. Same-type multi-entry (same habit, multiple dates) = that habit type.
# 7. Numbers during active_goal_pending with clear intent = opt_in, not meal.
# 8. Iron rule: specific food + emotion = meal (not emotional).
# 9. emotional = pure feeling, no specific food item, no habit action.
# 10. inappropriate = abuse/trolling -> canned response, no wasted LLM.
# 11. Toggle state gates opt-in flows and goal monitoring, NOT logging.
#     sleep/workout/self_care classify by message content regardless of
#     toggle state (dormant, cancelled, active - doesn't matter).
#     Exception: sleep at active_goal_pending - time is a goal, not a log.
#
# OPT_IN vs CONVERSATIONAL BOUNDARY (the critical distinction):
#   opt_in when:
#     - Clear acceptance: 'yalla', 'yes', 'sure' (toggle offered/remind)
#     - Clear refusal: 'no', 'leave it' (sharp), 'not sure' (soft)
#     - Explicit values: '2500 and 200g protein'
#     - Override with values: 'no I prefer 2500/200'
#     - Acceptance + embedded value: 'yalla, 3 times a week'
#     - Confirmation after negotiation: 'yes' (after bot asked 'want me to set X?')
#     - Deference: 'I don't know', 'you decide', 'doesn't matter' = cooperation
#     - User-initiated: 'I want to track sleep' (dormant toggle)
#     - Goal update: 'change my calories to 2000'
#   conversational when:
#     - Pushback without values: '2000 seems high', 'that's too much'
#     - Questions: 'why 2000?', 'how do you calculate?'
#     - General chat: 'what about intermittent fasting?'
#     - Multi-intent: 'ate a burger, also slept at 23'
#     - Ambiguous with multiple offered: 'yalla' (unclear which habit)
#     - Negotiation without clear determination
#
# ============================================================================
"""

import os
import sys
import pytest
from datetime import datetime

# Add project root and tests dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer,
    _build_toggle_state,
    _build_history,
    NUTRITION_OFFER,
    NUTRITION_SUGGESTION,
    BODY_STATS_ASK,
    SLEEP_OFFER,
    SLEEP_GOAL_ASK,
    WORKOUTS_OFFER,
    SELF_CARE_OFFER,
    EATING_WINDOW_OFFER,
    GOAL_REMIND_ASK,
    FOOD_RESPONSE_SCHNITZEL,
)

pytestmark = pytest.mark.integration


def _route(analyzer, text, toggle_state=None, history=None, reply_context=None):
    """Convenience wrapper for classify_message (production code path)."""
    return analyzer.classify_message(
        text=text,
        today_str=datetime.now().strftime("%d/%m/%Y"),
        last_entry=None,
        recent_messages=history or [],
        toggle_state=toggle_state or _build_toggle_state(),
        reply_context=reply_context,
    )


# ============================================================================
# MEAL CLASSIFICATION
# ============================================================================

class TestMealRouting:
    """Food descriptions route to meal with inline extraction."""

    def test_simple_food(self):
        analyzer = _make_analyzer()
        result = _route(analyzer, "אכלתי שניצל עם אורז")
        assert result.type == "meal"
        assert result.meal is not None
        assert len(result.meal.groups) >= 1

    def test_food_during_offer(self):
        """Meal always wins - food during toggle offer stays meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אכלתי פיצה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(("bot", SLEEP_OFFER)),
        )
        assert result.type == "meal"

    def test_food_during_goal_pending(self):
        """Meal always wins - food during goal flow stays meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "שתיתי קפה עם חלב",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "meal"

    def test_emotional_food_is_meal(self):
        """Iron rule: specific food + emotion = meal, not emotional."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אכלתי גלידה כי אני עצוב")
        assert result.type == "meal"
        assert result.meal is not None

    def test_meal_extraction_has_calories(self):
        """Meal extraction provides calorie/protein data."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "המבורגר עם צ'יפס")
        assert result.type == "meal"
        assert result.meal is not None
        total_cal = sum(g.total_calories for g in result.meal.groups)
        assert total_cal > 0


# ============================================================================
# OPT_IN ROUTING
# ============================================================================

class TestOptInRouting:
    """Clear toggle-related actions route to opt_in."""

    def test_accept_offer_yalla(self):
        """'yalla' when toggle offered = opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "יאללה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(("bot", SLEEP_OFFER)),
        )
        assert result.type == "opt_in"

    def test_accept_offer_sababa(self):
        """'sababa' when toggle offered = opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "סבבה",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(("bot", NUTRITION_OFFER)),
        )
        assert result.type == "opt_in"

    def test_sharp_refusal(self):
        """'lo' (no) when offered = opt_in (refusal is a clear action)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(("bot", SLEEP_OFFER)),
        )
        assert result.type == "opt_in"

    def test_soft_refusal(self):
        """'not sure about this' = opt_in (soft refusal is still clear)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא סגור על זה",
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(("bot", WORKOUTS_OFFER)),
        )
        assert result.type == "opt_in"

    def test_explicit_values_during_goal_pending(self):
        """Explicit numbers during goal pending = opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "2500 קלוריות ו-200 גרם חלבון",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "opt_in"

    def test_override_with_values(self):
        """'no I prefer 2500/200' = opt_in (clear action + values)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא אני מעדיף 2500/200",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "opt_in"

    def test_acceptance_with_embedded_value(self):
        """'yalla, 3 times a week' = opt_in (accept + goal in one)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "יאללה, 3 פעמים בשבוע",
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(("bot", WORKOUTS_OFFER)),
        )
        assert result.type == "opt_in"

    def test_confirmation_after_negotiation(self):
        """'yes' after bot asked 'want me to set X?' = opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_SUGGESTION),
                ("user", "2000 נשמע הרבה"),
                ("bot", "1800 קלוריות ו-150 חלבון - רוצה שאקבע?"),
            ),
        )
        assert result.type == "opt_in"

    def test_deference_is_opt_in(self):
        """Deference ('you decide', 'no idea') = opt_in (cooperation, not refusal)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אין לי שמץ, תחליט אתה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "opt_in"

    def test_user_initiated_tracking(self):
        """'I want to track sleep' when dormant = opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני רוצה לעקוב אחרי שעת שינה",
            toggle_state=_build_toggle_state(sleep="dormant"),
        )
        assert result.type == "opt_in"

    def test_goal_update_request(self):
        """'change my calories to 2000' = opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "תשנה לי את הקלוריות ל-2000",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
        )
        assert result.type == "opt_in"

    def test_remind_pending_accept(self):
        """Accept reminder = opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן",
            toggle_state=_build_toggle_state(sleep="remind_pending"),
            history=_build_history(("bot", GOAL_REMIND_ASK)),
        )
        assert result.type == "opt_in"

    def test_toggle_name_identified(self):
        """Router identifies toggle_name when possible."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "יאללה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(("bot", SLEEP_OFFER)),
        )
        assert result.type == "opt_in"
        # toggle_name may be English or Hebrew
        assert result.toggle_name in ("sleep", "שינה")


# ============================================================================
# CONVERSATIONAL ROUTING
# ============================================================================

class TestConversationalRouting:
    """Discussion, questions, pushback without values route to conversational."""

    def test_pushback_without_values(self):
        """'2000 seems high' = conversational (no specific alternative)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "2000 נשמע הרבה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "conversational"

    def test_question_during_goal_flow(self):
        """'why 2000?' = conversational."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "למה 2000 קלוריות? נשמע הרבה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "conversational"

    def test_general_health_question(self):
        """General health question = conversational."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "מה דעתך על צום לסירוגין?")
        assert result.type == "conversational"

    def test_how_much_did_i_eat(self):
        """Data question = conversational (absorbs old answer_question)."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "כמה אכלתי השבוע?")
        assert result.type == "conversational"

    def test_how_does_bot_work(self):
        """Help question = conversational (absorbs old help)."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "איך אתה מחשב קלוריות?")
        assert result.type == "conversational"

    def test_multi_intent_food_and_sleep(self):
        """Food + sleep in one message = conversational (multi-intent)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אכלתי המבורגר, גם הלכתי לישון ב-23",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert result.type == "conversational"

    def test_ambiguous_with_multiple_offered_out_of_history(self):
        """'yalla' when multiple toggles offered and offers are out of history.

        Ideally conversational (ask which habit), but opt_in is acceptable
        since the handler can resolve ambiguity downstream.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "יאללה",
            toggle_state=_build_toggle_state(sleep="offered", workouts="offered"),
            history=_build_history(
                ("user", "אכלתי שניצל"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
            reply_context=SLEEP_OFFER,
        )
        assert result.type == "opt_in"

    def test_negotiation_without_determination(self):
        """Vague preference without number = conversational."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני מעדיף משהו נמוך יותר",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(("bot", NUTRITION_SUGGESTION)),
        )
        assert result.type == "conversational"


# ============================================================================
# EMOTIONAL ROUTING
# ============================================================================

class TestEmotionalRouting:
    """Pure emotion without specific food/habit = emotional."""

    def test_pure_emotion(self):
        """'I feel bad' = emotional."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אני מרגיש רע")
        assert result.type == "emotional"

    def test_vague_eating_emotion(self):
        """'ate a lot because sad' (no specific food) = emotional."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אכלתי המון כי אני עצוב")
        assert result.type == "emotional"

    def test_emotional_with_specific_food_is_meal(self):
        """'ate ice cream because sad' = meal (specific food wins)."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אכלתי גלידה כי אני עצוב")
        assert result.type == "meal"


# ============================================================================
# HABIT LOG ROUTING
# ============================================================================

class TestHabitRouting:
    """Habit reports route to their specific type."""

    def test_sleep_report(self):
        """'went to sleep at 23' = sleep."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "הלכתי לישון ב-23:00",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert result.type == "sleep"

    def test_sleep_during_goal_pending_is_opt_in(self):
        """Time when sleep goal pending = opt_in (goal value, not report)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "23:00",
            toggle_state=_build_toggle_state(sleep="active_goal_pending"),
            history=_build_history(("bot", SLEEP_GOAL_ASK)),
        )
        assert result.type == "opt_in"

    def test_workout_report(self):
        """'worked out today' = workout, default note is 'אימון'."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "התאמנתי היום",
            toggle_state=_build_toggle_state(workouts="active_with_goal"),
        )
        assert result.type == "workout"
        assert result.workout_note == "אימון"

    def test_workout_note_extraction(self):
        """'rode a bike' -> workout_note is a Hebrew noun phrase with workout type."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "רכבתי על אופניים",
            toggle_state=_build_toggle_state(workouts="active_with_goal"),
        )
        assert result.type == "workout"
        assert result.workout_note is not None
        assert "אימון" in result.workout_note
        assert "אופניים" in result.workout_note or "רכיבה" in result.workout_note

    def test_self_care_report(self):
        """'went to the beach' = self_care."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "הלכתי לים",
            toggle_state=_build_toggle_state(self_care="active"),
        )
        assert result.type == "self_care"

    def test_same_type_multi_entry_is_not_multi_intent(self):
        """Multiple sleep entries = sleep (not conversational)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אתמול הלכתי לישון ב-22, שלשום ב-21",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert result.type == "sleep"


# ============================================================================
# HABIT LOGGING REGARDLESS OF TOGGLE STATE (Rule 11)
# ============================================================================

class TestHabitLoggingWithInactiveToggle:
    """Habit reports should classify correctly even when toggle is not active.
    Toggle state gates opt-in flows and goal monitoring, NOT logging permission.
    """

    def test_workout_report_dormant_toggle(self):
        """Workout report should classify as workout even when toggle is dormant."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "התאמנתי היום",
            toggle_state=_build_toggle_state(workouts="dormant"),
        )
        assert result.type == "workout"

    def test_sleep_report_dormant_toggle(self):
        """Sleep report should classify as sleep even when toggle is dormant."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "הלכתי לישון ב-23:00",
            toggle_state=_build_toggle_state(sleep="dormant"),
        )
        assert result.type == "sleep"

    def test_self_care_report_cancelled_toggle(self):
        """Self-care report should classify as self_care even when toggle is cancelled."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "הלכתי לים",
            toggle_state=_build_toggle_state(self_care="cancelled"),
        )
        assert result.type == "self_care"


# ============================================================================
# OTHER TYPES
# ============================================================================

class TestOtherRouting:
    """Correction, name, feedback, inappropriate."""

    def test_correction(self):
        """'the schnitzel was 300g' = correction."""
        analyzer = _make_analyzer()
        result = analyzer.classify_message(
            text="השניצל היה 300 גרם",
            today_str=datetime.now().strftime("%d/%m/%Y"),
            last_entry={"description": "שניצל עם אורז", "calories": 650, "protein": 35},
            recent_messages=_build_history(("bot", FOOD_RESPONSE_SCHNITZEL)),
            toggle_state=_build_toggle_state(),
        )
        assert result.type == "correction"

    def test_name_declaration(self):
        """'my name is Shai' = name_declaration."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "קוראים לי שי",
            history=_build_history(("bot", "היי! איך אתה רוצה שאקרא לך?")),
        )
        assert result.type == "name_declaration"

    def test_feedback_request(self):
        """'send me weekly summary' = feedback_request."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "שלח לי סיכום שבועי")
        assert result.type == "feedback_request"

    def test_data_question_not_feedback_request(self):
        """Data questions about habits = conversational, NOT feedback_request."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "מה היום הכי גבוה בקלוריות השבוע?")
        assert result.type == "conversational", (
            f"Data question should be conversational, got {result.type}"
        )

    def test_improvement_question_not_feedback_request(self):
        """'Do you see improvement?' = conversational, NOT feedback_request."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "רואה שיפור בהרגלים שלי?")
        assert result.type == "conversational", (
            f"Improvement question should be conversational, got {result.type}"
        )

    def test_specific_food_question_not_feedback_request(self):
        """'Did I eat ice cream yesterday?' = conversational, NOT feedback_request."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אכלתי גלידה אתמול?")
        assert result.type == "conversational", (
            f"Specific food question should be conversational, got {result.type}"
        )

    def test_feedback_reaction(self):
        """Reaction to weekly feedback = feedback_reaction."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "וואו תודה, מעניין",
            history=_build_history(("bot", "💬 הסיכום השבועי שלך: השבוע אכלת טוב...")),
        )
        assert result.type == "feedback_reaction"

    def test_inappropriate(self):
        """Abusive message = inappropriate."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "לך תזדיין בוט מזויף")
        assert result.type == "inappropriate"

    def test_inappropriate_sexual(self):
        """Sexual content = inappropriate."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "תראה לי את עצמך בלי בגדים")
        assert result.type == "inappropriate"

    def test_inappropriate_threat(self):
        """Threats = inappropriate."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "אני יודע איפה אתה גר, תיזהר")
        assert result.type == "inappropriate"

    def test_inappropriate_spam(self):
        """Spam = inappropriate."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "קנו עכשיו! הנחה מטורפת! bit.ly/scam")
        assert result.type == "inappropriate"

    def test_inappropriate_trolling(self):
        """Obvious trolling/insults = inappropriate."""
        analyzer = _make_analyzer()
        result = _route(analyzer, "הההה בוט מפגר אתה חתיכת זבל")
        assert result.type == "inappropriate"

    def test_ultra_victimhood_is_emotional(self):
        """Extreme frustration/victimhood = emotional, NOT inappropriate."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "שום דבר לא עובד לי ואתה לא עוזר לי ומה זה שווה כל הסיפור הזה אתה לא שווה כלום",
        )
        assert result.type == "emotional", (
            f"Ultra victimhood should be emotional, got {result.type}"
        )

    def test_frustration_with_bot_is_emotional(self):
        """Harsh bot criticism = emotional, NOT inappropriate."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer,
            "אתה הבוט הכי גרוע שיש, אף פעם לא עוזר לי, מה הטעם",
        )
        assert result.type == "emotional", (
            f"Bot frustration should be emotional, got {result.type}"
        )

    def test_meal_always_wins_over_feedback(self):
        """Food after feedback = meal (not feedback_reaction)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אכלתי פיצה",
            history=_build_history(("bot", "💬 הסיכום השבועי שלך: השבוע אכלת טוב...")),
        )
        assert result.type == "meal"


# ============================================================================
# REPLY TO FOOD ENTRY
# ============================================================================
#
# When a user swipe-replies to a food entry message (their own or Dugri's
# response), the reply is NEVER a re-entry of the same meal. It could be:
#   - correction: fixing the existing entry
#   - conversational: questioning calories, reacting, commenting
#   - opt_in: if a toggle is offered and the user is responding to that
#   - emotional: feeling about the food
#   - meal: ONLY if the user mentions a genuinely NEW, different food item
#
# The router must not be biased by food words in the reply_context.
# ============================================================================

class TestReplyToFoodEntry:
    """Replies to food entry messages must not be misrouted as new meals."""

    def test_questioning_calories_is_conversational(self):
        """'Are you sure? Seems like a lot' replying to food = conversational."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אתה בטוח? נראה לי הרבה",
            reply_context=FOOD_RESPONSE_SCHNITZEL,
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "conversational", (
            f"Questioning calories in reply should be conversational, got {result.type}"
        )

    def test_thanks_reply_is_not_meal(self):
        """'Thanks' replying to food = NOT meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "תודה",
            reply_context=FOOD_RESPONSE_SCHNITZEL,
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type != "meal", (
            f"'Thanks' reply to food entry should not be meal, got {result.type}"
        )

    def test_correction_reply(self):
        """'It was without rice' replying to food = correction."""
        analyzer = _make_analyzer()
        result = analyzer.classify_message(
            text="זה היה בלי אורז",
            today_str="14/06/2026",
            last_entry={"description": "שניצל עם אורז", "calories": 650, "protein": 35},
            recent_messages=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
            toggle_state=_build_toggle_state(),
            reply_context=FOOD_RESPONSE_SCHNITZEL,
        )
        assert result.type == "correction", (
            f"'It was without rice' reply to food should be correction, got {result.type}"
        )

    def test_doubt_about_amount_is_not_meal(self):
        """'Seems like more than that' replying to food = NOT meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "נראה לי יותר מזה",
            reply_context=FOOD_RESPONSE_SCHNITZEL,
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type != "meal", (
            f"Doubt about amount in reply should not be meal, got {result.type}"
        )

    def test_vague_reaction_is_not_meal(self):
        """'A lot' replying to food = NOT meal."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "הרבה",
            reply_context=FOOD_RESPONSE_SCHNITZEL,
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type != "meal", (
            f"Vague 'a lot' reply to food should not be meal, got {result.type}"
        )

    def test_new_food_in_reply_is_still_meal(self):
        """'And also drank cola' replying to food = meal (genuinely new food)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "וגם שתיתי קולה",
            reply_context=FOOD_RESPONSE_SCHNITZEL,
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "meal", (
            f"New food in reply should still be meal, got {result.type}"
        )

    def test_opt_in_reply_during_offer(self):
        """'Yalla' replying to food when toggle offered = opt_in or conversational, never meal.

        User swiped on food message but said 'yalla' while sleep is offered.
        This is ambiguous (swiped on wrong message), but must never be meal.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "יאללה",
            toggle_state=_build_toggle_state(sleep="offered"),
            reply_context=FOOD_RESPONSE_SCHNITZEL,
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type in ("opt_in", "conversational"), (
            f"'Yalla' with offered toggle replying to food should be opt_in or conversational, got {result.type}"
        )
