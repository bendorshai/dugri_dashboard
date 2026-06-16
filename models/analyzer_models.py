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
    corrected_date: str | None = None   # DD/MM/YYYY, None = no change
    corrected_time: str | None = None   # HH:MM, None = no change


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


class HabitCorrectionResult(BaseModel):
    """Correction result for non-food habits (sleep, workout, self_care)."""
    corrected_date: str | None = None      # DD/MM/YYYY
    corrected_time: str | None = None      # HH:MM (for sleep_time)
    corrected_note: str | None = None      # workout note / self_care description
    delete: bool = False                   # user wants to delete entirely
    reclassify_to: Literal["sleep", "workout", "self_care"] | None = None  # change habit type


class Tier1Classification(BaseModel):
    """Tier 1 Intent Router - broad category classification only.

    Purely contextual (no toggle state). Four categories, no extraction.
    """
    type: Literal["meal", "habit_logger", "goals_talk", "other"]


class HabitLoggerClassification(BaseModel):
    """Tier 2 Habit Logger sub-classifier output."""
    type: Literal["sleep", "workout", "self_care", "correction"]
    sleep_time: str | None = None
    workout_note: str | None = None
    self_care_description: str | None = None


class GoalValues(BaseModel):
    """Extracted goal values."""
    calories: int | None = None
    protein: int | None = None
    sleep_time: str | None = None
    workout_count: int | None = None


class GoalsTalkClassification(BaseModel):
    """Tier 2 Goals Talk sub-classifier output."""
    type: Literal["accept", "refuse", "goal_value", "cancel", "hesitation"]
    toggle_name: str | None = None
    goal_values: GoalValues | None = None


class OtherClassification(BaseModel):
    """Tier 2 Other sub-classifier output."""
    type: Literal[
        "conversational", "feedback_request", "feedback_reaction",
        "name_declaration", "gender_declaration", "feature_request",
        "emotional", "inappropriate",
    ]
    declared_gender: Literal["male", "female", "other"] | None = None
