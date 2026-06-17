"""
test_empathy_prepend.py - Unit tests for _prepend_empathy helper.

# ============================================================================
# SPEC: _prepend_empathy helper
# ============================================================================
#
# Prepends empathy reflection to habit confirmation text when emotional_context
# is True. Falls back to static pool (get_inline_empathy) when no LLM-generated
# reflection is available. Returns text unchanged when no emotion detected.
# ============================================================================
"""

import pytest
from unittest.mock import MagicMock
from models.analyzer_models import RouterClassification


class TestPrependEmpathy:
    """Test the _prepend_empathy helper method."""

    def _make_handler(self, emotional_support_service=None):
        """Create a minimal handler with the _prepend_empathy method."""
        from handlers.base import HealthHandlers
        handler = MagicMock(spec=HealthHandlers)
        handler.emotional_support_service = emotional_support_service
        handler._prepend_empathy = HealthHandlers._prepend_empathy.__get__(handler)
        return handler

    def test_no_emotion_returns_unchanged(self):
        """When emotional_context is False, text should be returned unchanged."""
        handler = self._make_handler()
        result = RouterClassification(type="sleep", emotional_context=False)
        text = "רשמתי שינה ב-23:00."
        assert handler._prepend_empathy(text, result) == text

    def test_emotion_with_reflection_prepends(self):
        """When emotional_context is True with reflection, prepend it."""
        handler = self._make_handler()
        result = RouterClassification(
            type="sleep",
            emotional_context=True,
            empathy_reflection="נשמע שזה מעיק עליך, אבל אני כאן איתך וממשיכים.",
        )
        text = "רשמתי שינה ב-01:00."
        output = handler._prepend_empathy(text, result)
        assert output == "נשמע שזה מעיק עליך, אבל אני כאן איתך וממשיכים.\n\nרשמתי שינה ב-01:00."

    def test_emotion_without_reflection_uses_fallback(self):
        """When emotional_context is True but no reflection, use static fallback."""
        emo_svc = MagicMock()
        emo_svc.get_inline_empathy.return_value = "שמעתי, ואנחנו ממשיכים ביחד."
        handler = self._make_handler(emotional_support_service=emo_svc)
        result = RouterClassification(
            type="workout",
            emotional_context=True,
            empathy_reflection=None,
        )
        text = "רשמתי אימון."
        output = handler._prepend_empathy(text, result)
        assert output == "שמעתי, ואנחנו ממשיכים ביחד.\n\nרשמתי אימון."
        emo_svc.get_inline_empathy.assert_called_once()

    def test_emotion_no_reflection_no_service_returns_unchanged(self):
        """When emotional but no reflection and no service, return unchanged."""
        handler = self._make_handler(emotional_support_service=None)
        result = RouterClassification(
            type="self_care",
            emotional_context=True,
            empathy_reflection=None,
        )
        text = "יפה. רשמתי 'משהו לעצמי' השבוע."
        assert handler._prepend_empathy(text, result) == text

    def test_meal_emotion_prepends(self):
        """Meal route should also get empathy prepended."""
        handler = self._make_handler()
        result = RouterClassification(
            type="meal",
            emotional_context=True,
            empathy_reflection="זה לא פשוט, אבל אנחנו ממשיכים לעקוב ביחד.",
        )
        text = "• גלידה\n  ~150 גרם | 300 קל׳ | 5 גרם חלבון"
        output = handler._prepend_empathy(text, result)
        assert output.startswith("זה לא פשוט, אבל אנחנו ממשיכים לעקוב ביחד.\n\n")
        assert "גלידה" in output
