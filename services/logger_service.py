"""
logger_service.py - Extracts structured data from natural language messages.

Each method is a focused extraction prompt for a specific habit type.
Called as the second LLM call after the Router classifies the message type.
The Router classifies; the Logger extracts.

Depends on: analyzer (for LLM calls), existing extraction prompts.
Used by: handlers/base.py (dispatched for sleep, workout, self_care,
         correction, name_declaration, emotional, feedback_reaction,
         feature_request).
"""

from __future__ import annotations

import logging
from typing import Literal

from analyzer import FoodAnalyzer, HabitEntry
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SleepExtraction(BaseModel):
    sleep_time: str | None = None
    entries: list[HabitEntry] | None = None


class WorkoutExtraction(BaseModel):
    workout_note: str | None = None
    entries: list[HabitEntry] | None = None


class NameExtraction(BaseModel):
    declared_name: str | None = None


class EmotionalResponse(BaseModel):
    empathy_reflection: str


class LogConfirmationCheck(BaseModel):
    is_log_confirmation: bool
    habit_type: Literal["workout", "sleep", "self_care"] | None = None


class FeatureRequestClassification(BaseModel):
    request_type: Literal["bug_report", "feature_request", "habit_of_interest"]
    ack_text: str


class LoggerService:
    """Extracts structured data from messages after Router classification."""

    def __init__(self, analyzer: FoodAnalyzer):
        self._analyzer = analyzer

    def extract_sleep(self, text: str, today_str: str, day_name: str = "") -> SleepExtraction:
        """Extract sleep time(s) from natural text."""
        result = self._analyzer.extract_goal_value(text, "sleep_time")
        if result and result.get("sleep_time"):
            return SleepExtraction(sleep_time=result["sleep_time"])
        return SleepExtraction()

    def extract_workout(self, text: str, today_str: str, day_name: str = "") -> WorkoutExtraction:
        """Extract workout details from natural text."""
        # For workouts, the text itself is the note
        return WorkoutExtraction(workout_note=text)

    def extract_name(self, text: str) -> NameExtraction:
        """Extract declared name from text."""
        # Simple extraction - the text after "my name is" / "I'm" patterns
        # or just the raw text if responding to "what's your name?"
        name = text.strip()
        # Remove common prefixes
        for prefix in ["קוראים לי", "השם שלי", "אני"]:
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
        return NameExtraction(declared_name=name or text.strip())

    def generate_empathy(self, text: str) -> EmotionalResponse:
        """Generate empathy reflection for standalone emotional message.

        Uses temperature 0.9 for warm, varied responses.
        """
        try:
            response = self._analyzer._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": (
                        "אתה דוגרי. המשתמש מביע רגש. "
                        "כתוב משפט אמפתיה לפי הנוסחה: [שיקוף קצר של התחושה] + [הצהרת שותפות והתמדה]. "
                        "מקסימום 1-2 משפטים קצרים. בלי שאלות המשך. בעברית, בגובה העיניים."
                    )},
                    {"role": "user", "content": text},
                ],
                temperature=0.9,
                max_tokens=100,
            )
            return EmotionalResponse(empathy_reflection=response.choices[0].message.content or "")
        except Exception:
            logger.exception("Empathy generation failed")
            return EmotionalResponse(empathy_reflection="נשמע שקשה לך, אבל אנחנו ממשיכים ביחד.")

    def classify_feature_request(self, text: str) -> FeatureRequestClassification:
        """Classify feature request sub-type and generate Dugri-tone ack."""
        from prompts import FEATURE_REQUEST_LOGGER_PROMPT
        try:
            response = self._analyzer._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": FEATURE_REQUEST_LOGGER_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format=FeatureRequestClassification,
                temperature=0,
                max_tokens=150,
            )
            return response.choices[0].message.parsed
        except Exception:
            logger.exception("Feature request classification failed")
            return FeatureRequestClassification(
                request_type="feature_request",
                ack_text="קיבלתי, רשמתי את זה.",
            )

    def extract_habit_correction(
        self, text: str, habit_type: str, original_date: str,
        original_value: str, today_str: str,
    ):
        """Extract correction details for a non-food habit entry.

        Returns HabitCorrectionResult with what changed (date, time, note, or delete).
        """
        from models.analyzer_models import HabitCorrectionResult
        from prompts import HABIT_CORRECTION_PROMPT

        value_label = {
            "sleep": f"שעת שינה: {original_value}",
            "workout": f"סוג אימון: {original_value}" if original_value else "אימון",
            "self_care": f"פעילות: {original_value}",
        }.get(habit_type, original_value)

        user_text = (
            f"סוג הרגל: {habit_type}\n"
            f"תאריך מקורי: {original_date}\n"
            f"{value_label}\n"
            f"תיקון: {text}"
        )

        try:
            response = self._analyzer._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": HABIT_CORRECTION_PROMPT + f"\nהתאריך של היום: {today_str}\n"},
                    {"role": "user", "content": user_text},
                ],
                response_format=HabitCorrectionResult,
                temperature=0,
                max_tokens=100,
            )
            return response.choices[0].message.parsed
        except Exception:
            logger.exception("Habit correction extraction failed")
            return HabitCorrectionResult()

    def check_log_confirmation(self, bot_message: str, user_message: str) -> LogConfirmationCheck:
        """Check if the user is confirming a bot suggestion to log a specific activity.

        Called only when type=opt_in and toggle is dormant - a rare edge case
        where the router can't distinguish log confirmation from toggle opt-in.
        """
        try:
            response = self._analyzer._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": (
                        "הבוט שלח הודעה למשתמש, והמשתמש ענה.\n"
                        "האם הבוט הציע לרשום פעילות ספציפית שהמשתמש כבר תיאר "
                        "(למשל: 'רוצה לדווח על זה כהתאמן?') והמשתמש אישר?\n"
                        "אם כן: is_log_confirmation=true, habit_type=סוג ההרגל (workout/sleep/self_care).\n"
                        "אם לא (הצעת מעקב שוטף, שאלה כללית, וכו'): is_log_confirmation=false."
                    )},
                    {"role": "user", "content": f"הודעת בוט: {bot_message}\nתגובת משתמש: {user_message}"},
                ],
                response_format=LogConfirmationCheck,
                temperature=0,
                max_tokens=50,
            )
            return response.choices[0].message.parsed
        except Exception:
            logger.exception("Log confirmation check failed")
            return LogConfirmationCheck(is_log_confirmation=False)
