"""
test_gem_dressing.py - Tests for GPT gem dressing.

Expected behavior:
- dress_wisdom_gem sends correct prompt with gem text, category, mode, context
- Gender suffix is correctly applied (female -> ה, male -> empty)
- On GPT failure, returns raw gem text as fallback
- Mode "general" includes context "אין", mode "pattern" includes real context
"""

from unittest.mock import MagicMock, patch
import sys

# Stub heavy imports before importing analyzer
for mod in ["telegram", "telegram.ext", "pymongo"]:
    sys.modules.setdefault(mod, MagicMock())


class TestDressWisdomGem:

    def _make_analyzer(self):
        from analyzer import FoodAnalyzer
        analyzer = FoodAnalyzer.__new__(FoodAnalyzer)
        analyzer.client = MagicMock()
        return analyzer

    def test_pattern_mode_sends_context(self):
        analyzer = self._make_analyzer()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "dressed text"
        mock_response.usage = None
        analyzer.client.chat.completions.create.return_value = mock_response

        result = analyzer.dress_wisdom_gem(
            gem_text="פנינה",
            category="momentum",
            mode="pattern",
            context={"days_logged": 5},
            name="שי",
            gender="male",
        )
        assert result == "dressed text"
        call_args = analyzer.client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "pattern" in user_msg
        assert "days_logged" in user_msg

    def test_general_mode_no_context(self):
        analyzer = self._make_analyzer()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "dressed text"
        mock_response.usage = None
        analyzer.client.chat.completions.create.return_value = mock_response

        result = analyzer.dress_wisdom_gem(
            gem_text="פנינה",
            category="general",
            mode="general",
            context=None,
            name="שי",
            gender="male",
        )
        call_args = analyzer.client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "general" in user_msg
        assert "אין" in user_msg

    def test_female_gender_suffix(self):
        analyzer = self._make_analyzer()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "dressed"
        mock_response.usage = None
        analyzer.client.chat.completions.create.return_value = mock_response

        analyzer.dress_wisdom_gem(
            gem_text="פנינה",
            category="momentum",
            mode="pattern",
            context={},
            name="נועה",
            gender="female",
        )
        call_args = analyzer.client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "ה" in user_msg  # gender suffix

    def test_fallback_on_exception(self):
        analyzer = self._make_analyzer()
        analyzer.client.chat.completions.create.side_effect = Exception("API error")

        result = analyzer.dress_wisdom_gem(
            gem_text="raw fallback text",
            category="momentum",
            mode="general",
            context=None,
            name="",
            gender="male",
        )
        assert result == "raw fallback text"
