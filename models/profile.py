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


_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


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
    weight_goal: Literal["lose", "maintain", "gain"] | None = None

    @field_validator("sleep_time")
    @classmethod
    def validate_sleep_time(cls, v: str | None) -> str | None:
        if v is not None:
            if not _TIME_RE.match(v):
                raise ValueError(f"sleep_time must be H:MM or HH:MM, got '{v}'")
            parts = v.split(":")
            v = f"{int(parts[0]):02d}:{parts[1]}"
        return v


class Strike(BaseModel):
    """A user strike for malicious behavior. General-purpose - any service can add."""
    reason: str
    detail: str
    source: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiscoveredPattern(BaseModel):
    """A behavioral pattern discovered during weekly feedback."""
    pattern: str          # Hebrew description shown to user
    summary: str          # English key for dedup (e.g. "late_sleep_skips_breakfast")
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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

    Tracking statuses:
    - dormant: not yet offered or offered but not activated
    - active: user opted in, hook runs at its cadence
    - cancelled: user explicitly opted out, never offered again

    Goal statuses:
    - pending: goal not yet offered
    - set: goal value stored
    - declined: user said "don't ask again"
    - remind: user wants to be reminded later (goal_remind_at has the date)
    """
    # Tracking lifecycle
    status: Literal["dormant", "active", "cancelled"] = "dormant"
    revealed_at: datetime | None = None
    activated_at: datetime | None = None
    last_asked_at: datetime | None = None
    consecutive_unanswered: int = 0

    # Goal lifecycle
    goal_status: Literal["pending", "set", "declined", "remind", "remind_pending"] = "pending"
    goal_value: dict | None = None
    goal_remind_at: datetime | None = None
    goal_offered_at: datetime | None = None

    # Education
    edu_intro_shown: bool = False


class Toggles(BaseModel):
    """All habit toggles. weekly_summary is opt-out (born active); rest are opt-in (born dormant)."""
    sleep: ToggleState = Field(default_factory=ToggleState)
    eating_window: ToggleState = Field(default_factory=ToggleState)
    workouts: ToggleState = Field(default_factory=ToggleState)
    self_care: ToggleState = Field(default_factory=ToggleState)
    nutrition: ToggleState = Field(default_factory=ToggleState)
    weekly_summary: ToggleState = Field(default_factory=lambda: ToggleState(status="active"))


class Onboarding(BaseModel):
    name_collected: bool = False
    habits: OnboardingHabits = Field(default_factory=OnboardingHabits)


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
    toggles: Toggles = Field(default_factory=Toggles)

    recent_messages: list[dict] = Field(default_factory=list)

    dashboard_intro_shown: bool = False
    target_retry_done: bool = False
    eating_window_retry_done: bool = False

    feedback_steering_prompt: str | None = None
    last_feedback_offered_at: datetime | None = None
    discovered_patterns: list[DiscoveredPattern] = Field(default_factory=list)
    strikes: list[Strike] = Field(default_factory=list)

    subscription_status: str = "trial_pending"
    trial_started_at: datetime | None = None

    signup_session_token: str | None = None
    signup_session_token_expires_at: datetime | None = None

    # Dashboard fields
    consents: dict = Field(default_factory=dict)
    birth_year: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None

    # Token usage tracking: {"gpt-4o": {"prompt": N, "completion": M}, ...}
    tokens_used: dict[str, dict[str, int]] = Field(default_factory=dict)

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
        for legacy_key in ["chat_id", "onboarding_complete", "terms_accepted", "bot_key", "pending_state", "active_habits", "goals"]:
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
                habit_to_toggle = {
                    "sleep": "sleep",
                    "workouts": "workouts",
                    "self_care": "self_care",
                    "nutrition": "nutrition",
                    "eating_window": "eating_window",
                }
                for old_name, new_name in habit_to_toggle.items():
                    habit = habits.get(old_name, {})
                    if isinstance(habit, dict):
                        old_state = habit.get("state", "pending")
                        toggles[new_name] = {"status": state_map.get(old_state, "dormant")}
                toggles.setdefault("weekly_summary", {"status": "active"})
                doc["toggles"] = toggles

        # Rename target_data -> nutrition
        toggles = doc.get("toggles", {})
        if isinstance(toggles, dict) and "target_data" in toggles:
            toggles["nutrition"] = toggles.pop("target_data")
            doc["toggles"] = toggles

        # Migrate targets into toggle goal_values
        targets = doc.get("targets", {})
        if isinstance(targets, dict) and isinstance(toggles, dict):
            # Nutrition goals from targets.calories/protein
            nt = toggles.get("nutrition", {})
            if isinstance(nt, dict) and not nt.get("goal_value"):
                cal = targets.get("calories")
                prot = targets.get("protein")
                if cal or prot:
                    nt["goal_value"] = {}
                    if cal:
                        nt["goal_value"]["calories"] = cal
                    if prot:
                        nt["goal_value"]["protein"] = prot
                    nt["goal_status"] = "set"
                    toggles["nutrition"] = nt

            # Sleep goal from targets.sleep_time
            st = toggles.get("sleep", {})
            if isinstance(st, dict) and not st.get("goal_value"):
                sleep_time = targets.get("sleep_time")
                if sleep_time:
                    st["goal_value"] = {"sleep_time": sleep_time}
                    st["goal_status"] = "set"
                    toggles["sleep"] = st

            # Workouts goal from targets.workouts_per_week
            wt = toggles.get("workouts", {})
            if isinstance(wt, dict) and not wt.get("goal_value"):
                wpw = targets.get("workouts_per_week")
                if wpw:
                    wt["goal_value"] = {"weekly_target": wpw}
                    wt["goal_status"] = "set"
                    toggles["workouts"] = wt

            doc["toggles"] = toggles

        # Migrate eating_window into toggle goal_value
        ew = doc.get("eating_window")
        if ew and isinstance(toggles, dict):
            ewt = toggles.get("eating_window", {})
            if isinstance(ewt, dict) and not ewt.get("goal_value"):
                if isinstance(ew, dict):
                    ewt["goal_value"] = {"start": ew.get("start", "08:00"), "end": ew.get("end", "20:00")}
                    ewt["goal_status"] = "set"
                    toggles["eating_window"] = ewt
                    doc["toggles"] = toggles

        return cls.model_validate(doc)


# Backward-compat alias — will be removed after all imports are updated
UserProfile = User
