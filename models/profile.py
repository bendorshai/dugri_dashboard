"""
profile.py — מודל המשתמש המאוחד של דוגרי.

הקובץ הזה מגדיר את User ותתי-המודלים שלו. המשתמש נוצר באתר (PK=email)
ומתעדכן מהבוט כשמקשרים telegram_user_id.

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
    """Legacy habit state — kept for backward compatibility during migration."""
    state: Literal["offered", "active", "declined", "pending"] = "pending"
    last_prompted_at: datetime | None = None


class OnboardingHabits(BaseModel):
    """Legacy onboarding habits — kept for backward compatibility during migration."""
    nutrition: HabitState = Field(default_factory=HabitState)
    eating_window: HabitState = Field(default_factory=HabitState)
    sleep: HabitState = Field(default_factory=HabitState)
    workouts: HabitState = Field(default_factory=HabitState)
    self_care: HabitState = Field(default_factory=HabitState)


class ToggleState(BaseModel):
    """State of a single habit toggle in the toggle system.

    Three statuses:
    - dormant: not yet offered or offered but not activated
    - active: user opted in, hook runs at its cadence
    - cancelled: user explicitly opted out, never offered again
    """
    status: Literal["dormant", "active", "cancelled"] = "dormant"
    revealed_at: datetime | None = None
    activated_at: datetime | None = None
    last_asked_at: datetime | None = None
    consecutive_unanswered: int = 0


class Toggles(BaseModel):
    """All habit toggles. weekly_summary is opt-out (born active); rest are opt-in (born dormant)."""
    sleep: ToggleState = Field(default_factory=ToggleState)
    eating_window: ToggleState = Field(default_factory=ToggleState)
    workouts: ToggleState = Field(default_factory=ToggleState)
    self_care: ToggleState = Field(default_factory=ToggleState)
    target_data: ToggleState = Field(default_factory=ToggleState)
    weekly_summary: ToggleState = Field(default_factory=lambda: ToggleState(status="active"))


class Onboarding(BaseModel):
    name_collected: bool = False
    habits: OnboardingHabits = Field(default_factory=OnboardingHabits)


class PendingState(BaseModel):
    kind: str
    data: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class User(BaseModel):
    email: str
    telegram_user_id: int | None = None
    name: str | None = None
    gender: Literal["male", "female"] | None = None
    photo_url: str | None = None

    targets: Targets = Field(default_factory=Targets)
    eating_window: EatingWindow | None = None
    timezone: str = "Asia/Jerusalem"

    onboarding: Onboarding = Field(default_factory=Onboarding)
    active_habits: list[str] = Field(default_factory=list)
    toggles: Toggles = Field(default_factory=Toggles)

    pending_state: PendingState | None = None

    dashboard_intro_shown: bool = False
    target_retry_done: bool = False
    eating_window_retry_done: bool = False

    feedback_steering_prompt: str | None = None
    last_feedback_offered_at: datetime | None = None

    subscription_status: str = "trial_pending"
    trial_started_at: datetime | None = None

    signup_session_token: str | None = None
    signup_session_token_expires_at: datetime | None = None

    # Dashboard fields
    consents: dict = Field(default_factory=dict)
    goals: dict = Field(default_factory=dict)
    birth_year: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo_dict(self) -> dict:
        """Convert to MongoDB document. Maps email to _id."""
        d = self.model_dump(mode="json")
        d["_id"] = d.pop("email")
        return d

    @classmethod
    def from_mongo_dict(cls, doc: dict) -> User:
        """Create from MongoDB document. Maps _id back to email.

        Handles legacy flat-field profiles (target_calories, eating_window_start, etc.)
        by migrating them to the nested structure.
        """
        doc = dict(doc)
        if "_id" in doc:
            doc["email"] = doc.pop("_id")

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

        # Migrate old onboarding.habits to toggles (only if toggles not already set)
        if "toggles" not in doc:
            onboarding = doc.get("onboarding", {})
            habits = onboarding.get("habits", {}) if isinstance(onboarding, dict) else {}
            if habits:
                state_map = {
                    "pending": "dormant",
                    "offered": "dormant",
                    "active": "active",
                    "declined": "cancelled",
                }
                toggles: dict = {}
                # Map old habit names to new toggle names
                habit_to_toggle = {
                    "sleep": "sleep",
                    "workouts": "workouts",
                    "self_care": "self_care",
                    "nutrition": "target_data",
                    "eating_window": "eating_window",
                }
                for old_name, new_name in habit_to_toggle.items():
                    habit = habits.get(old_name, {})
                    if isinstance(habit, dict):
                        old_state = habit.get("state", "pending")
                        toggles[new_name] = {"status": state_map.get(old_state, "dormant")}
                # weekly_summary defaults to active (opt-out)
                toggles.setdefault("weekly_summary", {"status": "active"})
                doc["toggles"] = toggles

        return cls.model_validate(doc)


# Backward-compat alias — will be removed after all imports are updated
UserProfile = User
