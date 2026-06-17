# -*- coding: utf-8 -*-
"""
test_emotional_habit_classifier.py - LLM tests for emotional context detection in habit logging.

# ============================================================================
# SPEC: Emotional empathy in habit logging
# ============================================================================
#
# When a user logs a habit (sleep, workout, self_care, meal) AND expresses
# emotion in the same message, the classifier should:
#   1. Classify the habit type correctly (sleep/workout/self_care/meal)
#   2. Set emotional_context = True
#   3. Generate a one-sentence empathy_reflection in Hebrew, Dugri tone
#
# When a user logs a habit WITHOUT emotion:
#   1. Classify normally
#   2. emotional_context = False
#   3. empathy_reflection = None
#
# This is DIFFERENT from pure emotional messages (no habit data) which go
# through the "emotional" classification and get therapist referral.
#
# Empathy reflection style: [short reflection of feeling] + [partnership &
# persistence statement]. Max 1-2 sentences, no follow-up questions.
# Hebrew, Dugri tone (direct, at eye level).
# ============================================================================
"""

import pytest
from tests._lazy_optin_helpers import _make_analyzer

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def analyzer():
    return _make_analyzer()


class TestHabitLoggerEmotionalContext:
    """Test that classify_habit detects emotional context in habit messages."""

    def test_emotional_sleep(self, analyzer):
        """Sleep log with emotional content should set emotional_context=True."""
        result = analyzer.classify_habit("הלכתי לישון באחת בלילה ואני בדיכאון מזה")
        assert result.type == "sleep"
        assert result.sleep_time == "01:00"
        assert result.emotional_context is True
        assert result.empathy_reflection is not None
        assert len(result.empathy_reflection) > 0

    def test_normal_sleep(self, analyzer):
        """Sleep log without emotion should have emotional_context=False."""
        result = analyzer.classify_habit("הלכתי לישון ב-23")
        assert result.type == "sleep"
        assert result.sleep_time == "23:00"
        assert result.emotional_context is False

    def test_emotional_workout(self, analyzer):
        """Workout log with emotional content should set emotional_context=True."""
        result = analyzer.classify_habit("התאמנתי אבל אין לי כוח לכלום")
        assert result.type == "workout"
        assert result.emotional_context is True
        assert result.empathy_reflection is not None

    def test_normal_workout(self, analyzer):
        """Workout log without emotion should have emotional_context=False."""
        result = analyzer.classify_habit("התאמנתי היום")
        assert result.type == "workout"
        assert result.emotional_context is False

    def test_emotional_self_care(self, analyzer):
        """Self-care log with emotional content should set emotional_context=True."""
        result = analyzer.classify_habit("הלכתי לים אבל חזרתי עצוב")
        assert result.type == "self_care"
        assert result.emotional_context is True
        assert result.empathy_reflection is not None

    def test_positive_emotion(self, analyzer):
        """Positive emotions should also trigger emotional_context=True."""
        result = analyzer.classify_habit("התאמנתי ואני מרגיש מלך!")
        assert result.type == "workout"
        assert result.emotional_context is True
        assert result.empathy_reflection is not None


class TestMealEmotionalContext:
    """Test that analyze_food_text detects emotional context in meal messages."""

    def test_emotional_meal(self, analyzer):
        """Meal log with emotional content should set emotional_context=True."""
        result = analyzer.analyze_food_text("אכלתי גלידה כי אני עצוב", "16/06/2026")
        assert result is not None
        assert len(result.groups) > 0
        assert result.emotional_context is True
        assert result.empathy_reflection is not None

    def test_normal_meal(self, analyzer):
        """Meal log without emotion should have emotional_context=False."""
        result = analyzer.analyze_food_text("שניצל עם אורז", "16/06/2026")
        assert result is not None
        assert len(result.groups) > 0
        assert result.emotional_context is False

    def test_emotional_meal_still_extracts_food(self, analyzer):
        """Emotional meal should still extract food data correctly."""
        result = analyzer.analyze_food_text("אכלתי פיצה ואני מרגיש נורא", "16/06/2026")
        assert result is not None
        assert len(result.groups) > 0
        # Food should be extracted regardless of emotion
        items = result.groups[0].items
        assert len(items) > 0
        assert items[0].calories > 0


class TestEmpathyReflectionQuality:
    """Test that empathy reflections are appropriate."""

    def test_empathy_is_hebrew(self, analyzer):
        result = analyzer.classify_habit("הלכתי לישון באחת ואני בדיכאון")
        assert result.empathy_reflection is not None
        has_hebrew = any("\u0590" <= c <= "\u05FF" for c in result.empathy_reflection)
        assert has_hebrew

    def test_empathy_is_short(self, analyzer):
        result = analyzer.classify_habit("התאמנתי אבל אין לי כוח לחיות")
        assert result.empathy_reflection is not None
        assert len(result.empathy_reflection) < 100
