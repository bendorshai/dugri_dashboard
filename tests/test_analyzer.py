from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Stub openai before importing
mock_openai_module = MagicMock()
sys.modules.setdefault("openai", mock_openai_module)

from analyzer import FoodAnalyzer, FoodItem, FoodAnalysisResult, MessageParseResult, CorrectionResult


@pytest.fixture
def analyzer():
    with patch("analyzer.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        fa = FoodAnalyzer(api_key="test-key")
        yield fa, mock_client


class TestFoodAnalyzerInit:
    def test_creates_openai_client(self):
        with patch("analyzer.OpenAI") as mock_cls:
            FoodAnalyzer(api_key="sk-test")
            mock_cls.assert_called_once_with(api_key="sk-test")


class TestAnalyzeFoodText:
    def test_system_prompt_contains_key_instructions(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = FoodAnalysisResult(
            items=[FoodItem(description="שניצל", calories=400, protein=30)],
            total_calories=400,
            total_protein=30,
        )
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.analyze_food_text("שניצל", "05/05/2026")

        call_args = mock_client.beta.chat.completions.parse.call_args
        system_msg = call_args[1]["messages"][0]["content"]
        assert "קלוריות" in system_msg
        assert "חלבון" in system_msg
        assert "תזונתי" in system_msg

    def test_returns_parsed_result(self, analyzer):
        fa, mock_client = analyzer
        expected = FoodAnalysisResult(
            items=[FoodItem(description="שניצל", calories=400, protein=30)],
            total_calories=400,
            total_protein=30,
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.analyze_food_text("שניצל", "05/05/2026")
        assert result.total_calories == 400
        assert result.total_protein == 30
        assert len(result.items) == 1

    def test_uses_structured_output(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = FoodAnalysisResult(
            items=[], total_calories=0, total_protein=0,
        )
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.analyze_food_text("test", "05/05/2026")

        call_args = mock_client.beta.chat.completions.parse.call_args
        assert call_args[1]["response_format"] == FoodAnalysisResult

    def test_handles_gpt_failure(self, analyzer):
        fa, mock_client = analyzer
        mock_client.beta.chat.completions.parse.side_effect = Exception("API error")

        result = fa.analyze_food_text("test", "05/05/2026")
        assert result is None

    def test_handles_none_parsed(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = None
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.analyze_food_text("test", "05/05/2026")
        assert result is None


class TestAnalyzeFoodPhoto:
    def test_sends_image_content(self, analyzer):
        fa, mock_client = analyzer
        expected = FoodAnalysisResult(
            items=[FoodItem(description="סלט", calories=150, protein=5)],
            total_calories=150,
            total_protein=5,
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.analyze_food_photo("base64data", "05/05/2026", caption="סלט")

        call_args = mock_client.beta.chat.completions.parse.call_args
        messages = call_args[1]["messages"]
        user_msg = messages[1]
        assert user_msg["role"] == "user"
        # Should contain image_url content block
        assert any(
            isinstance(c, dict) and c.get("type") == "image_url"
            for c in user_msg["content"]
        )

    def test_uses_gpt4o_for_vision(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = FoodAnalysisResult(
            items=[], total_calories=0, total_protein=0,
        )
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.analyze_food_photo("base64data", "05/05/2026")

        call_args = mock_client.beta.chat.completions.parse.call_args
        assert call_args[1]["model"] == "gpt-4o"


class TestWeeklyFeedback:
    def test_prompt_includes_history_and_past_feedbacks(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"feedback_text": "כל הכבוד!", "insight": "חיובי עובד", "insight_category": "positive"}'
        mock_client.chat.completions.create.return_value = mock_response

        fa.generate_weekly_feedback(
            week_csv="date,food,cal,prot\n05/05,שניצל,400,30",
            targets={"calories": 2000, "protein": 150},
            past_feedbacks=["יפה מאוד!"],
            user_insights=["מגיב טוב לחיובי"],
        )

        call_args = mock_client.chat.completions.create.call_args
        system_msg = call_args[1]["messages"][0]["content"]
        assert "שניצל" in call_args[1]["messages"][1]["content"]
        assert "יפה מאוד!" in call_args[1]["messages"][1]["content"]


class TestMealSuggestions:
    def test_prompt_includes_remaining_values(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "1. חזה עוף\n2. סלט\n3. ביצים"
        mock_client.chat.completions.create.return_value = mock_response

        fa.suggest_meals(
            remaining_calories=700,
            remaining_protein=100,
            today_entries="שניצל 400 cal",
        )

        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "700" in user_msg
        assert "100" in user_msg


class TestAnswerQuestion:
    def test_sends_question_with_context(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "התשובה"
        mock_client.chat.completions.create.return_value = mock_response

        result = fa.answer_question(
            question="כמה חלבון אכלתי?",
            week_csv="data",
            targets={"calories": 2000, "protein": 150},
        )

        assert result == "התשובה"
        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "כמה חלבון אכלתי?" in user_msg


class TestParseMessage:
    def test_returns_food_type(self, analyzer):
        fa, mock_client = analyzer
        food_result = FoodAnalysisResult(
            items=[FoodItem(description="שניצל", calories=400, protein=30)],
            total_calories=400, total_protein=30,
        )
        expected = MessageParseResult(type="food", food=food_result)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.parse_message("שניצל", "05/05/2026")
        assert result.type == "food"
        assert result.food.total_calories == 400

    def test_returns_correction_type(self, analyzer):
        fa, mock_client = analyzer
        correction = CorrectionResult(
            corrected_description="המבורגר 300 גרם",
            corrected_calories=600, corrected_protein=45,
        )
        expected = MessageParseResult(type="correction", correction=correction)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        last_entry = {"description": "המבורגר 150 גרם", "calories": 300, "protein": 25}
        result = fa.parse_message("ההמבורגר היה 300 גרם", "05/05/2026", last_entry)
        assert result.type == "correction"
        assert result.correction.corrected_calories == 600

    def test_includes_last_entry_in_prompt(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = MessageParseResult(type="unknown")
        mock_client.beta.chat.completions.parse.return_value = mock_response

        last_entry = {"description": "שניצל", "calories": 400, "protein": 30}
        fa.parse_message("תתקן", "05/05/2026", last_entry)

        call_args = mock_client.beta.chat.completions.parse.call_args
        system_msg = call_args[1]["messages"][0]["content"]
        assert "שניצל" in system_msg
        assert "400" in system_msg

    def test_handles_failure(self, analyzer):
        fa, mock_client = analyzer
        mock_client.beta.chat.completions.parse.side_effect = Exception("API error")

        result = fa.parse_message("test", "05/05/2026")
        assert result.type == "unknown"


class TestSuggestTargets:
    def test_sends_body_params(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"target_calories": 2000, "target_protein": 150}'
        mock_client.chat.completions.create.return_value = mock_response

        fa.suggest_targets(height_cm=175, weight_kg=80, age=30)

        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "175" in user_msg
        assert "80" in user_msg
        assert "30" in user_msg
