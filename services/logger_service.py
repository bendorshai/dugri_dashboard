"""
logger_service.py - Extracts structured data from natural language messages.

Each method is a focused extraction prompt for a specific habit type.
Called as the second LLM call after the Router classifies the message type.
The Router classifies; the Logger extracts.

Depends on: analyzer (for LLM calls), existing extraction prompts.
Used by: handlers/base.py (dispatched for sleep, workout, self_care,
         correction, name_declaration, emotional, feedback_reaction).
"""

from __future__ import annotations

import logging

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
        """Generate empathy reflection for standalone emotional message."""
        # Use a lightweight prompt for empathy generation
        try:
            messages = [
                {"role": "system", "content": (
                    "אתה דוגרי. המשתמש מביע רגש. "
                    "כתוב משפט אחד קצר של אמפתיה - שיקוף של מה שהמשתמש אמר. "
                    "לא עצה, לא פתרון, רק שיקוף. בעברית, בגובה העיניים."
                )},
                {"role": "user", "content": text},
            ]
            response = self._analyzer.converse(messages, max_tokens=100)
            return EmotionalResponse(empathy_reflection=response)
        except Exception:
            logger.exception("Empathy generation failed")
            return EmotionalResponse(empathy_reflection="נשמע שקשה לך.")
