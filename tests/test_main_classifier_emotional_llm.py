# -*- coding: utf-8 -*-
"""
test_main_classifier_emotional_llm.py - LLM tests for emotional_context detection
in the main classifier (Tier 1).

# ============================================================================
# SPEC: Main classifier emotional awareness
# ============================================================================
#
# The main classifier (Tier 1) detects emotional content alongside type
# classification. It returns emotional_context: bool as part of its output.
#
# Rules:
#   1. emotional_context does NOT affect type classification.
#      Meal still wins when specific food is named.
#      Habit logging still wins when habit action is described.
#   2. emotional_context=True when user expresses emotion (sadness, anger,
#      frustration, guilt, joy, pride, anxiety, despair).
#   3. emotional_context=False for neutral messages, data questions,
#      greetings, and factual statements.
#
# ============================================================================
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import _make_analyzer

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def analyzer():
    return _make_analyzer()


class TestEmotionalContextWithMeal:
    """Emotional detection should not disturb meal classification."""

    def test_sad_meal_is_meal_with_emotion(self, analyzer):
        """Specific food + sadness = meal, emotional_context=True."""
        result = analyzer.main_classifier("אכלתי גלידה כי אני עצוב", "17/06/2026")
        assert result.type == "meal"
        assert result.emotional_context is True

    def test_neutral_meal_no_emotion(self, analyzer):
        """Neutral food description = meal, emotional_context=False."""
        result = analyzer.main_classifier("שניצל עם אורז", "17/06/2026")
        assert result.type == "meal"
        assert result.emotional_context is False

    def test_angry_meal(self, analyzer):
        """Food + anger = meal, emotional_context=True."""
        result = analyzer.main_classifier(
            "אני כועס על עצמי שאכלתי גלידה עכשיו", "17/06/2026"
        )
        assert result.type == "meal"
        assert result.emotional_context is True

    def test_bummed_about_coffee(self, analyzer):
        """Drink + frustration = meal, emotional_context=True."""
        result = analyzer.main_classifier(
            "מבואס ששתיתי קפה עם חלב", "17/06/2026"
        )
        assert result.type == "meal"
        assert result.emotional_context is True

    def test_plain_coffee_no_emotion(self, analyzer):
        """Neutral drink = meal, emotional_context=False."""
        result = analyzer.main_classifier("קפה שחור", "17/06/2026")
        assert result.type == "meal"
        assert result.emotional_context is False


class TestEmotionalContextWithHabit:
    """Emotional detection should not disturb habit classification."""

    def test_depressed_sleep(self, analyzer):
        """Sleep + depression = habit_logger, emotional_context=True."""
        result = analyzer.main_classifier(
            "הלכתי לישון באחת ואני בדיכאון", "17/06/2026"
        )
        assert result.type == "habit_logger"
        assert result.emotional_context is True

    def test_neutral_sleep(self, analyzer):
        """Neutral sleep = habit_logger, emotional_context=False."""
        result = analyzer.main_classifier("הלכתי לישון ב-23", "17/06/2026")
        assert result.type == "habit_logger"
        assert result.emotional_context is False

    def test_proud_workout(self, analyzer):
        """Workout + pride = habit_logger, emotional_context=True."""
        result = analyzer.main_classifier(
            "התאמנתי ואני מרגיש מלך!", "17/06/2026"
        )
        assert result.type == "habit_logger"
        assert result.emotional_context is True

    def test_neutral_workout(self, analyzer):
        """Neutral workout = habit_logger, emotional_context=False."""
        result = analyzer.main_classifier("התאמנתי היום", "17/06/2026")
        assert result.type == "habit_logger"
        assert result.emotional_context is False

    def test_exhausted_workout(self, analyzer):
        """Workout + exhaustion = habit_logger, emotional_context=True."""
        result = analyzer.main_classifier(
            "התאמנתי אבל אין לי כוח", "17/06/2026"
        )
        assert result.type == "habit_logger"
        assert result.emotional_context is True


class TestEmotionalContextPureEmotion:
    """Pure emotional messages should have emotional_context=True."""

    def test_pure_emotion(self, analyzer):
        """'I feel bad' = conversation_or_..., emotional_context=True."""
        result = analyzer.main_classifier("אני מרגיש רע", "17/06/2026")
        assert result.type == "conversation_or_question_or_feedback_or_feature_request_or_emotion_or_anything_else"
        assert result.emotional_context is True

    def test_vague_eating_with_emotion(self, analyzer):
        """Vague eating + emotion (no specific food) = conversation_or_..., emotional_context=True."""
        result = analyzer.main_classifier(
            "אכלתי המון כי אני עצוב", "17/06/2026"
        )
        assert result.type == "conversation_or_question_or_feedback_or_feature_request_or_emotion_or_anything_else"
        assert result.emotional_context is True

    def test_anxiety(self, analyzer):
        """Anxiety expression = conversation_or_..., emotional_context=True."""
        result = analyzer.main_classifier("יש לי חרדות", "17/06/2026")
        assert result.type == "conversation_or_question_or_feedback_or_feature_request_or_emotion_or_anything_else"
        assert result.emotional_context is True


class TestNoEmotionalContext:
    """Neutral messages should have emotional_context=False."""

    def test_data_question(self, analyzer):
        """Data question = no emotion."""
        result = analyzer.main_classifier("מה אכלתי אתמול?", "17/06/2026")
        assert result.emotional_context is False

    def test_greeting(self, analyzer):
        """Greeting = no emotion."""
        result = analyzer.main_classifier("בוקר טוב", "17/06/2026")
        assert result.emotional_context is False

    def test_goal_negotiation(self, analyzer):
        """Goal negotiation = no emotion."""
        result = analyzer.main_classifier("2000 נשמע הרבה", "17/06/2026")
        assert result.emotional_context is False
