"""
test_analyzer.py - TDD for the FoodAnalyzer class.

Tests the OpenAI-backed analysis layer that powers all LLM interactions:
food text analysis, photo analysis, corrections, weekly feedback, meal
suggestions, question answering, target calculation, and message parsing.

All tests mock the OpenAI client - no real API calls. Validates that
correct prompts, models, and structured output formats are used.

# ============================================================================
# ANALYZER SPECIFICATION (Single Source of Truth)
#
# This comment defines what FoodAnalyzer is responsible for and how each
# method must behave. When behavior changes, UPDATE THIS COMMENT FIRST,
# then update/add tests, then fix code to pass.
#
# ============================================================================
#
# FOOD TEXT ANALYSIS (analyze_food_text)
# ---------------------------------------
# - System prompt must include Hebrew terms: קלוריות, חלבון, תזונתי
# - Uses structured output (TimedFoodAnalysisResult) for reliable parsing
# - Returns FoodAnalysisResult with calories and protein per item
# - Returns None on GPT failure (no exceptions propagated to caller)
#
# FOOD PHOTO ANALYSIS (analyze_food_photo)
# -----------------------------------------
# - Sends image_url content block in user message
# - Uses gpt-4o model (vision-capable)
# - Uses FoodPhotoResult structured output format
# - Returns photo_tips for image quality feedback
#
# WEEKLY FEEDBACK (generate_weekly_feedback)
# -------------------------------------------
# - Uses WeeklyFeedbackResult structured output format
# - Uses gpt-4o model for complex analysis
# - System prompt includes "כל המספרים כבר מחושבים" (all numbers pre-calculated)
# - Includes food items and past feedback in prompt context
# - Returns discovered_pattern and pattern_summary fields
# - Returns None on failure
#
# MEAL SUGGESTIONS (suggest_meals)
# ---------------------------------
# - Prompt includes remaining_calories, remaining_protein, and today_entries
#
# QUESTION ANSWERING (answer_question)
# -------------------------------------
# - Sends question with week_csv and targets context
#
# MESSAGE PARSING (parse_message / classify_message)
# ---------------------------------------------------
# - Returns MessageParseResult with type="food" + FoodAnalysisResult
#   or type="correction" + CorrectionResult
# - Includes last_entry data in system message for correction context
# - Returns type="unknown" on failure
#
# TARGET SUGGESTION (suggest_targets)
# ------------------------------------
# - Sends height_cm, weight_kg, age in user message
#
# CORRECTION ANALYSIS (analyze_correction)
# -----------------------------------------
# - Includes original_description and new_correction in user message
# - Includes correction_history for multi-round corrections
# - Uses CorrectionResult structured output format
# - Returns None on failure
#
#
# ============================================================================
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from analyzer import (
    FoodAnalyzer, FoodItem, FoodAnalysisResult, FoodPhotoResult,
    MessageParseResult, CorrectionFoodItem,
    CorrectionResult,
    WeeklyFeedbackResult, TimedFoodAnalysisResult,
)


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
            items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
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
            items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
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
        assert call_args[1]["response_format"] == TimedFoodAnalysisResult

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
        expected = FoodPhotoResult(
            items=[FoodItem(description="סלט", estimated_grams=200, calories=150, protein=5)],
            total_calories=150,
            total_protein=5,
            photo_tips=["צילום מצוין! 👍 המשך לצלם ככה"],
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
        mock_response.choices[0].message.parsed = FoodPhotoResult(
            items=[], total_calories=0, total_protein=0,
            photo_tips=["צלם בזווית 45°"],
        )
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.analyze_food_photo("base64data", "05/05/2026")

        call_args = mock_client.beta.chat.completions.parse.call_args
        assert call_args[1]["model"] == "gpt-4o"

    def test_uses_photo_result_format(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = FoodPhotoResult(
            items=[], total_calories=0, total_protein=0,
            photo_tips=["טיפ"],
        )
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.analyze_food_photo("base64data", "05/05/2026")

        call_args = mock_client.beta.chat.completions.parse.call_args
        assert call_args[1]["response_format"] == FoodPhotoResult

    def test_returns_photo_tips(self, analyzer):
        fa, mock_client = analyzer
        expected = FoodPhotoResult(
            items=[FoodItem(description="סלט", estimated_grams=200, calories=150, protein=5)],
            total_calories=150,
            total_protein=5,
            photo_tips=["צלחת שטוחה עדיפה על קערה עמוקה"],
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.analyze_food_photo("base64data", "05/05/2026")
        assert result.photo_tips == ["צלחת שטוחה עדיפה על קערה עמוקה"]


class TestWeeklyFeedback:
    _SAMPLE_MONTH_STATS = {
        "raw_entries": {
            "food": [
                {"date": "05/06/2026", "time": "08:00", "description": "ביצים",
                 "calories": 300, "protein": 25, "within_window": True},
                {"date": "05/06/2026", "time": "13:00", "description": "שניצל",
                 "calories": 700, "protein": 50, "within_window": True},
            ],
        },
        "summaries": {
            "food_weekly": [
                {"days_tracked": 1, "avg_calories": 1000, "avg_protein": 75},
            ],
            "focus_week_cal_pct": 50,
            "focus_week_prot_pct": 50,
        },
        "targets": {"calories": 2000, "protein": 150, "sleep_time": None, "workouts_per_week": None},
        "active_toggles": ["nutrition"],
        "eating_window": None,
    }

    def test_uses_structured_output(self, analyzer):
        fa, mock_client = analyzer
        expected = WeeklyFeedbackResult(
            feedback_text="כל הכבוד!",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.generate_weekly_feedback(
            month_stats=self._SAMPLE_MONTH_STATS,
            past_feedbacks=["יפה מאוד!"],
        )

        call_args = mock_client.beta.chat.completions.parse.call_args
        assert call_args[1]["response_format"] == WeeklyFeedbackResult
        assert "ביצים" in call_args[1]["messages"][1]["content"]
        assert "יפה מאוד!" in call_args[1]["messages"][1]["content"]
        assert result["feedback_text"] == "כל הכבוד!"

    def test_returns_none_on_failure(self, analyzer):
        fa, mock_client = analyzer
        mock_client.beta.chat.completions.parse.side_effect = Exception("API error")

        result = fa.generate_weekly_feedback(
            month_stats=self._SAMPLE_MONTH_STATS,
            past_feedbacks=[],
        )
        assert result is None

    def test_returns_none_when_parsed_is_none(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = None
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.generate_weekly_feedback(
            month_stats=self._SAMPLE_MONTH_STATS,
            past_feedbacks=[],
        )
        assert result is None

    def test_uses_gpt4o_model(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = WeeklyFeedbackResult(feedback_text="x")
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.generate_weekly_feedback(month_stats=self._SAMPLE_MONTH_STATS, past_feedbacks=[])

        call_args = mock_client.beta.chat.completions.parse.call_args
        assert call_args[1]["model"] == "gpt-4o"

    def test_uses_enhanced_prompt(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = WeeklyFeedbackResult(feedback_text="x")
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.generate_weekly_feedback(month_stats=self._SAMPLE_MONTH_STATS, past_feedbacks=[])

        call_args = mock_client.beta.chat.completions.parse.call_args
        system_content = call_args[1]["messages"][0]["content"]
        assert "כל המספרים כבר מחושבים" in system_content

    def test_returns_discovered_pattern(self, analyzer):
        fa, mock_client = analyzer
        expected = WeeklyFeedbackResult(
            feedback_text="x",
            discovered_pattern="כשאתה ישן מאוחר אתה מדלג",
            pattern_summary="late_sleep_skips_breakfast",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.generate_weekly_feedback(
            month_stats=self._SAMPLE_MONTH_STATS, past_feedbacks=[],
        )
        assert result["discovered_pattern"] == "כשאתה ישן מאוחר אתה מדלג"
        assert result["pattern_summary"] == "late_sleep_skips_breakfast"


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
            items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
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
            items=[CorrectionFoodItem(description="המבורגר 300 גרם", estimated_grams=300, calories=600, protein=45)],
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


class TestAnalyzeCorrection:
    def test_prompt_includes_original_and_new_correction(self, analyzer):
        fa, mock_client = analyzer
        expected = CorrectionResult(
            items=[
                CorrectionFoodItem(description="המבורגר 300 גרם", estimated_grams=300, calories=750, protein=45, change_type="modified"),
                CorrectionFoodItem(description="צ'יפס", estimated_grams=150, calories=150, protein=3),
                CorrectionFoodItem(description="סלט", estimated_grams=200, calories=50, protein=7),
            ],
            corrected_description="המבורגר 300 גרם, צ'יפס, סלט",
            corrected_calories=950,
            corrected_protein=55,
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.analyze_correction(
            original_description="המבורגר 100 גרם, צ'יפס, סלט",
            original_calories=650,
            original_protein=40,
            correction_history=[],
            new_correction="ההמבורגר הוא 300 גרם",
            today_str="11/05/2026",
        )

        call_args = mock_client.beta.chat.completions.parse.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "המבורגר 100 גרם" in user_msg
        assert "ההמבורגר הוא 300 גרם" in user_msg
        assert result.corrected_calories == 950

    def test_prompt_includes_correction_history(self, analyzer):
        fa, mock_client = analyzer
        expected = CorrectionResult(
            items=[
                CorrectionFoodItem(description="המבורגר 300 גרם", estimated_grams=300, calories=750, protein=45, change_type="modified"),
                CorrectionFoodItem(description="צ'יפס גדול", estimated_grams=250, calories=300, protein=4, change_type="modified"),
                CorrectionFoodItem(description="סלט", estimated_grams=200, calories=50, protein=6),
            ],
            corrected_description="המבורגר 300 גרם, צ'יפס גדול, סלט",
            corrected_calories=1100,
            corrected_protein=55,
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = expected
        mock_client.beta.chat.completions.parse.return_value = mock_response

        result = fa.analyze_correction(
            original_description="המבורגר 100 גרם, צ'יפס, סלט",
            original_calories=650,
            original_protein=40,
            correction_history=["ההמבורגר הוא 300 גרם"],
            new_correction="הצ'יפס היה מנה גדולה",
            today_str="11/05/2026",
        )

        call_args = mock_client.beta.chat.completions.parse.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "ההמבורגר הוא 300 גרם" in user_msg  # history
        assert "הצ'יפס היה מנה גדולה" in user_msg  # new correction
        assert result.corrected_calories == 1100

    def test_handles_failure(self, analyzer):
        fa, mock_client = analyzer
        mock_client.beta.chat.completions.parse.side_effect = Exception("API error")
        result = fa.analyze_correction(
            original_description="test",
            original_calories=100,
            original_protein=10,
            correction_history=[],
            new_correction="fix",
            today_str="11/05/2026",
        )
        assert result is None

    def test_uses_structured_output(self, analyzer):
        fa, mock_client = analyzer
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = CorrectionResult(
            items=[CorrectionFoodItem(description="test", estimated_grams=100, calories=100, protein=10)],
            corrected_description="test", corrected_calories=100, corrected_protein=10,
        )
        mock_client.beta.chat.completions.parse.return_value = mock_response

        fa.analyze_correction("test", 100, 10, [], "fix", "11/05/2026")

        call_args = mock_client.beta.chat.completions.parse.call_args
        assert call_args[1]["response_format"] == CorrectionResult
