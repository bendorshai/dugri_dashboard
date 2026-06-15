"""
analyzer_models.py - Pydantic models for GPT response parsing.

Used by FoodAnalyzer and imported throughout the codebase.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FoodItem(BaseModel):
    description: str
    estimated_grams: int
    calories: int
    protein: int


class FoodAnalysisResult(BaseModel):
    items: list[FoodItem]
    total_calories: int
    total_protein: int


class TimedFoodGroup(BaseModel):
    temporal_label: str
    date: str
    time: str
    items: list[FoodItem]
    total_calories: int
    total_protein: int


class TimedFoodAnalysisResult(BaseModel):
    groups: list[TimedFoodGroup]


class FoodPhotoResult(BaseModel):
    items: list[FoodItem]
    total_calories: int
    total_protein: int
    photo_tips: list[str]
    unidentified_items: list[str] = Field(default_factory=list)


class CorrectionFoodItem(FoodItem):
    change_type: Literal["unchanged", "modified", "added", "removed"] = "unchanged"


class CorrectionResult(BaseModel):
    items: list[CorrectionFoodItem]
    corrected_description: str
    corrected_calories: int
    corrected_protein: int


class MessageParseResult(BaseModel):
    type: Literal["food", "correction", "unknown"]
    food: FoodAnalysisResult | None = None
    correction: CorrectionResult | None = None



class WeeklyFeedbackResult(BaseModel):
    feedback_text: str
    discovered_pattern: str | None = None
    pattern_summary: str | None = None


class NormalizedActivity(BaseModel):
    """GPT output for self-care activity normalization."""
    activity_name: str


class HabitEntry(BaseModel):
    """A single habit log entry with temporal context."""
    habit_type: Literal["sleep", "workout", "self_care"]
    temporal_label: str
    date: str
    sleep_time: str | None = None
    workout_note: str | None = None
    self_care_description: str | None = None


class RouterClassification(BaseModel):
    """Slim Router output - classifies message type and extracts meal data inline."""
    type: Literal[
        "meal", "opt_in", "correction",
        "name_declaration", "gender_declaration", "sleep", "workout", "self_care", "emotional",
        "feedback_request", "feedback_reaction", "feature_request", "conversational",
        "inappropriate",
    ]
    meal: TimedFoodAnalysisResult | None = None
    toggle_name: str | None = None
    declared_gender: Literal["male", "female", "other"] | None = None
    workout_note: str | None = None
