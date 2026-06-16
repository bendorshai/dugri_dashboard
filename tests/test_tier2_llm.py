"""
test_tier2_llm.py - TDD tests for Tier 2 sub-classifiers.

# ============================================================================
# TIER 2 SPEC
# ============================================================================
#
# Each tier 2 sub-classifier runs after tier 1 routes to its category.
# Focused prompt, one classification per call.
#
# HABIT_LOGGER: sleep/workout/self_care/correction + extraction
# GOALS_TALK: accept/refuse/goal_value/cancel/hesitation + toggle_name
# OTHER: conversational/feedback_request/feedback_reaction/name_declaration/
#        gender_declaration/feature_request/emotional/inappropriate
# MEAL: uses existing analyze_food_text (no new sub-classifier needed)
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
    _make_analyzer, _build_toggle_state, _build_history,
    NUTRITION_OFFER, NUTRITION_SUGGESTION, BODY_STATS_ASK,
    SLEEP_OFFER, SLEEP_GOAL_ASK, WORKOUTS_OFFER, SELF_CARE_OFFER,
    GOAL_REMIND_ASK, FOOD_RESPONSE_SCHNITZEL,
)

pytestmark = pytest.mark.integration


# ============================================================================
# HABIT LOGGER TIER 2
# ============================================================================

class TestHabitLoggerTier2:
    """Sub-classify habit reports into sleep/workout/self_care/correction."""

    def test_sleep_report(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_habit_logger("הלכתי לישון ב-23")
        assert result.type == "sleep"
        assert result.sleep_time is not None
        assert "23" in result.sleep_time

    def test_workout_report(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_habit_logger("התאמנתי היום")
        assert result.type == "workout"
        assert result.workout_note is not None

    def test_workout_with_type(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_habit_logger("עשיתי יוגה בבוקר")
        assert result.type == "workout"
        assert "יוגה" in result.workout_note

    def test_self_care(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_habit_logger("הלכתי לים היום")
        assert result.type == "self_care"
        assert result.self_care_description is not None

    def test_correction(self):
        analyzer = _make_analyzer()
        last_entry = {"description": "שניצל עם אורז", "calories": 650, "protein": 35}
        result = analyzer.route_tier2_habit_logger("בלי אורז", last_entry=last_entry)
        assert result.type == "correction"

    def test_confirm_log_workout(self):
        """Bot asked to log workout, user agreed."""
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_habit_logger(
            "אוקיי",
            recent_messages=_build_history(
                ("user", "רצתי אתמול בים"),
                ("bot", "נשמע כיף! רוצה לתעד את זה כאימון?"),
            ),
        )
        assert result.type == "workout"


# ============================================================================
# GOALS TALK TIER 2
# ============================================================================

class TestGoalsTalkTier2:
    """Sub-classify goal responses into accept/refuse/goal_value/cancel/hesitation."""

    def test_accept_offer(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_goals_talk(
            "יאללה",
            recent_messages=_build_history(("bot", SLEEP_OFFER)),
            toggle_state=_build_toggle_state(sleep="offered"),
        )
        assert result.type == "accept"
        assert result.toggle_name == "sleep"

    def test_refuse_offer(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_goals_talk(
            "לא, עזוב",
            recent_messages=_build_history(("bot", WORKOUTS_OFFER)),
            toggle_state=_build_toggle_state(workouts="offered"),
        )
        assert result.type == "refuse"

    def test_hesitation(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_goals_talk(
            "לא בטוח",
            recent_messages=_build_history(("bot", SELF_CARE_OFFER)),
            toggle_state=_build_toggle_state(self_care="offered"),
        )
        assert result.type == "hesitation"

    def test_goal_value_calories(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_goals_talk(
            "2500 קלוריות ו-200 גרם חלבון",
            recent_messages=_build_history(("bot", NUTRITION_SUGGESTION)),
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
        )
        assert result.type == "goal_value"
        assert result.toggle_name == "nutrition"

    def test_accept_suggestion(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_goals_talk(
            "אוקיי",
            recent_messages=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "יאללה"),
                ("bot", BODY_STATS_ASK),
                ("user", "180, 85, בן 30"),
                ("bot", NUTRITION_SUGGESTION),
            ),
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
        )
        assert result.type == "accept"


# ============================================================================
# OTHER TIER 2
# ============================================================================

class TestOtherTier2:
    """Sub-classify into conversational/emotional/name/gender/etc."""

    def test_question_about_data(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other("כמה אכלתי השבוע?")
        assert result.type == "conversational"

    def test_general_chat(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other("מה דעתך על צום לסירוגין?")
        assert result.type == "conversational"

    def test_pure_emotion(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other("יום קשה היום")
        assert result.type == "emotional"

    def test_name_declaration(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other("קוראים לי שי")
        assert result.type == "name_declaration"

    def test_gender_declaration(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other(
            "אני בן",
            recent_messages=_build_history(("bot", "בן או בת?")),
        )
        assert result.type == "gender_declaration"
        assert result.declared_gender == "male"

    def test_feature_request(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other("אפשר להוסיף מעקב שתיית מים?")
        assert result.type == "feature_request"

    def test_feedback_request(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other("תן לי סיכום שבועי")
        assert result.type == "feedback_request"

    def test_inappropriate(self):
        analyzer = _make_analyzer()
        result = analyzer.route_tier2_other("לך תזדיין")
        assert result.type == "inappropriate"
