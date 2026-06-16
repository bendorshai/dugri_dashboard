"""
test_self_care_normalization - TDD tests for GPT-based activity name normalization.

Expected behavior:
- normalize_self_care_activity() calls GPT and returns a normalized noun-form activity name
- On GPT failure, returns None (never raises)
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from analyzer import FoodAnalyzer, NormalizedActivity


class TestNormalizeSelfCareActivity:
    def _make_analyzer(self):
        return FoodAnalyzer(api_key="test-key")

    @patch.object(FoodAnalyzer, "_parse")
    def test_normalize_returns_activity_name(self, mock_parse):
        """Successful GPT call returns normalized activity string."""
        mock_choice = MagicMock()
        mock_choice.message.parsed = NormalizedActivity(activity_name="הליכה לים")
        mock_parse.return_value = MagicMock(choices=[mock_choice])

        analyzer = self._make_analyzer()
        result = analyzer.normalize_self_care_activity("הלכתי לים עם המשפחה")

        assert result == "הליכה לים"
        mock_parse.assert_called_once()

    @patch.object(FoodAnalyzer, "_parse")
    def test_normalize_failure_returns_none(self, mock_parse):
        """GPT failure returns None, never raises."""
        mock_parse.side_effect = Exception("API error")

        analyzer = self._make_analyzer()
        result = analyzer.normalize_self_care_activity("הלכתי לים")

        assert result is None
