# -*- coding: utf-8 -*-
"""
test_emotional_habit_classifier.py - LLM tests for emotional context detection
in the full classification pipeline.

# ============================================================================
# SPEC: Emotional empathy in the classification pipeline
# ============================================================================
#
# Emotional context is detected by the main classifier (Tier 1) and flows
# through to RouterClassification. When emotional_context=True for meal or
# habit messages, a dedicated empathy call generates warm validation text.
#
# When a user logs a habit/meal AND expresses emotion:
#   1. Main classifier sets emotional_context=True
#   2. Sub-classifier extracts data (no emotional fields)
#   3. Dedicated empathy call generates empathy_reflection at temp 0.9
#   4. RouterClassification carries both data and empathy
#
# When a user logs without emotion:
#   1. Main classifier sets emotional_context=False
#   2. Sub-classifier extracts data
#   3. No empathy call
#   4. empathy_reflection = None
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


def _classify(analyzer, text):
    """Classify through full pipeline (production code path)."""
    return analyzer.classify_message(text, "17/06/2026")


class TestEmotionalHabitPipeline:
    """Test full pipeline: emotional detection + data extraction + empathy."""

    def test_emotional_sleep_full_pipeline(self, analyzer):
        """Sleep + emotion = sleep type, emotional_context=True, empathy generated."""
        result = _classify(analyzer, "הלכתי לישון באחת בלילה ואני בדיכאון מזה")
        assert result.type == "sleep"
        assert result.sleep_time == "01:00"
        assert result.emotional_context is True
        assert result.empathy_reflection is not None
        assert len(result.empathy_reflection) > 0

    def test_normal_sleep_no_empathy(self, analyzer):
        """Sleep without emotion = sleep type, no empathy."""
        result = _classify(analyzer, "הלכתי לישון ב-23")
        assert result.type == "sleep"
        assert result.sleep_time == "23:00"
        assert result.emotional_context is False
        assert result.empathy_reflection is None

    def test_emotional_workout_full_pipeline(self, analyzer):
        """Workout + emotion = workout type, emotional_context=True, empathy generated."""
        result = _classify(analyzer, "התאמנתי אבל אין לי כוח לכלום")
        assert result.type == "workout"
        assert result.emotional_context is True
        assert result.empathy_reflection is not None

    def test_normal_workout_no_empathy(self, analyzer):
        """Workout without emotion = workout type, no empathy."""
        result = _classify(analyzer, "התאמנתי היום")
        assert result.type == "workout"
        assert result.emotional_context is False
        assert result.empathy_reflection is None

    def test_positive_emotion_workout(self, analyzer):
        """Positive emotions should also trigger empathy."""
        result = _classify(analyzer, "התאמנתי ואני מרגיש מלך!")
        assert result.type == "workout"
        assert result.emotional_context is True
        assert result.empathy_reflection is not None


class TestEmotionalMealPipeline:
    """Test full pipeline for meal + emotion."""

    def test_emotional_meal_full_pipeline(self, analyzer):
        """Meal + emotion = meal type, emotional_context=True, empathy + food data."""
        result = _classify(analyzer, "אכלתי גלידה כי אני עצוב")
        assert result.type == "meal"
        assert result.meal is not None
        assert len(result.meal.groups) > 0
        assert result.emotional_context is True
        assert result.empathy_reflection is not None

    def test_normal_meal_no_empathy(self, analyzer):
        """Meal without emotion = meal type, no empathy."""
        result = _classify(analyzer, "שניצל עם אורז")
        assert result.type == "meal"
        assert result.meal is not None
        assert result.emotional_context is False
        assert result.empathy_reflection is None

    def test_emotional_meal_still_extracts_food(self, analyzer):
        """Emotional meal should still extract food data correctly."""
        result = _classify(analyzer, "אכלתי פיצה ואני מרגיש נורא")
        assert result.type == "meal"
        assert result.meal is not None
        assert len(result.meal.groups) > 0
        items = result.meal.groups[0].items
        assert len(items) > 0
        assert items[0].calories > 0


class TestEmpathyReflectionQuality:
    """Test that empathy reflections are appropriate."""

    def test_empathy_is_hebrew(self, analyzer):
        result = _classify(analyzer, "הלכתי לישון באחת ואני בדיכאון")
        assert result.empathy_reflection is not None
        has_hebrew = any("\u0590" <= c <= "\u05FF" for c in result.empathy_reflection)
        assert has_hebrew

    def test_empathy_is_short(self, analyzer):
        result = _classify(analyzer, "התאמנתי אבל אין לי כוח לחיות")
        assert result.empathy_reflection is not None
        assert len(result.empathy_reflection) < 100
