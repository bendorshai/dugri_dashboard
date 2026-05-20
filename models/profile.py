"""
profile.py — מודל הפרופיל של משתמש דוגרי.

הקובץ הזה מגדיר את UserProfile ותתי-המודלים שלו. הפרופיל נוצר באתר
ומתעדכן גם מהבוט. ה-_id במונגו הוא telegram_user_id.

תלוי ב: pydantic בלבד.
נצרך על ידי: repositories/user_repository, services, handlers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class EatingWindow(BaseModel):
    start: str = "08:00"
    end: str = "20:00"

    @field_validator("start", "end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError(f"Time must be HH:MM, got '{v}'")
        return v


class Targets(BaseModel):
    calories: int | None = None
    protein: int | None = None
    sleep_time: str | None = None
    workouts_per_week: int | None = None

    @field_validator("sleep_time")
    @classmethod
    def validate_sleep_time(cls, v: str | None) -> str | None:
        if v is not None and not _TIME_RE.match(v):
            raise ValueError(f"sleep_time must be HH:MM, got '{v}'")
        return v


class HabitState(BaseModel):
    state: Literal["offered", "active", "declined", "pending"] = "pending"
    last_prompted_at: datetime | None = None


class OnboardingHabits(BaseModel):
    nutrition: HabitState = Field(default_factory=HabitState)
    eating_window: HabitState = Field(default_factory=HabitState)
    sleep: HabitState = Field(default_factory=HabitState)
    workouts: HabitState = Field(default_factory=HabitState)
    self_care: HabitState = Field(default_factory=HabitState)


class Onboarding(BaseModel):
    name_collected: bool = False
    habits: OnboardingHabits = Field(default_factory=OnboardingHabits)


class PendingState(BaseModel):
    kind: str
    data: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserProfile(BaseModel):
    telegram_user_id: int
    email: str | None = None
    name: str | None = None
    gender: Literal["male", "female"] | None = None

    targets: Targets = Field(default_factory=Targets)
    eating_window: EatingWindow | None = None
    timezone: str = "Asia/Jerusalem"

    onboarding: Onboarding = Field(default_factory=Onboarding)
    active_habits: list[str] = Field(default_factory=list)

    pending_state: PendingState | None = None

    feedback_steering_prompt: str | None = None
    last_feedback_offered_at: datetime | None = None

    subscription_status: str = "trial_pending"
    trial_started_at: datetime | None = None

    signup_session_token: str | None = None
    signup_session_token_expires_at: datetime | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo_dict(self) -> dict:
        """Convert to MongoDB document. Maps telegram_user_id to _id."""
        d = self.model_dump(mode="json")
        d["_id"] = d.pop("telegram_user_id")
        return d

    @classmethod
    def from_mongo_dict(cls, doc: dict) -> UserProfile:
        """Create from MongoDB document. Maps _id back to telegram_user_id.

        Handles legacy flat-field profiles (target_calories, eating_window_start, etc.)
        by migrating them to the nested structure.
        """
        doc = dict(doc)
        if "_id" in doc:
            doc["telegram_user_id"] = doc.pop("_id")

        # Migrate legacy flat fields to nested structure
        if "target_calories" in doc or "target_protein" in doc:
            doc.setdefault("targets", {})
            if isinstance(doc["targets"], dict):
                if "target_calories" in doc:
                    doc["targets"].setdefault("calories", doc.pop("target_calories"))
                if "target_protein" in doc:
                    doc["targets"].setdefault("protein", doc.pop("target_protein"))

        if "eating_window_start" in doc or "eating_window_end" in doc:
            start = doc.pop("eating_window_start", "08:00")
            end = doc.pop("eating_window_end", "20:00")
            if "eating_window" not in doc or doc["eating_window"] is None:
                doc["eating_window"] = {"start": start, "end": end}

        # Remove any unknown legacy fields that would fail validation
        for legacy_key in ["chat_id", "onboarding_complete", "terms_accepted", "bot_key"]:
            doc.pop(legacy_key, None)

        return cls.model_validate(doc)
