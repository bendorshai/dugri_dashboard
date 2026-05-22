"""
toggle_service.py — Central service for habit toggle state management.

Handles all toggle state transitions (dormant/active/cancelled), gate logic,
reveal timing, exit door mechanics, and unanswered tracking.

Depends on: repositories/user_repository, models/profile, constants.
Used by: handlers/base, scheduler, onboarding_service.
"""

from __future__ import annotations

from datetime import datetime, timezone

from constants import (
    TOGGLE_GATE_DAYS,
    TARGET_RETRY_DAY,
    EATING_WINDOW_RETRY_DAYS,
    DASHBOARD_INTRO_DAY,
    EXIT_DOOR_UNANSWERED_THRESHOLD,
    WORKOUTS_ANCHOR_DAY,
    SELF_CARE_ANCHOR_DAY,
)
from models.profile import User, ToggleState, Toggles
from repositories.user_repository import UserRepository

VALID_TOGGLE_NAMES = set(Toggles.model_fields.keys())


class ToggleService:
    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_toggle(self, profile: User, toggle_name: str) -> ToggleState:
        if toggle_name not in VALID_TOGGLE_NAMES:
            raise ValueError(f"Invalid toggle name: {toggle_name}")
        return getattr(profile.toggles, toggle_name)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def reveal_toggle(self, telegram_user_id: int, toggle_name: str) -> None:
        """Mark toggle as revealed (first-time offer). Status stays dormant."""
        now = datetime.now(timezone.utc).isoformat()
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.revealed_at": now,
        })

    def activate_toggle(self, telegram_user_id: int, toggle_name: str) -> None:
        """User accepted — toggle becomes active."""
        now = datetime.now(timezone.utc).isoformat()
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.status": "active",
            f"toggles.{toggle_name}.activated_at": now,
            f"toggles.{toggle_name}.consecutive_unanswered": 0,
        })

    def cancel_toggle(self, telegram_user_id: int, toggle_name: str) -> None:
        """User cancelled — toggle is off forever (unless re-activated manually)."""
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.status": "cancelled",
        })

    # ------------------------------------------------------------------
    # Hook tracking
    # ------------------------------------------------------------------

    def record_asked(self, telegram_user_id: int, toggle_name: str) -> None:
        """Record that a hook question was sent."""
        now = datetime.now(timezone.utc).isoformat()
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.last_asked_at": now,
        })

    def record_answered(self, telegram_user_id: int, toggle_name: str) -> None:
        """User answered the hook — reset unanswered counter."""
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.consecutive_unanswered": 0,
        })

    def increment_unanswered(
        self, telegram_user_id: int, profile: User, toggle_name: str,
    ) -> int:
        """Increment consecutive_unanswered and return the new count."""
        current = self.get_toggle(profile, toggle_name).consecutive_unanswered
        new_count = current + 1
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.consecutive_unanswered": new_count,
        })
        return new_count

    def should_show_exit_door(self, profile: User, toggle_name: str) -> bool:
        """Should we show the exit door message? Only on active toggles at threshold."""
        toggle = self.get_toggle(profile, toggle_name)
        if toggle.status != "active":
            return False
        return toggle.consecutive_unanswered >= EXIT_DOOR_UNANSWERED_THRESHOLD

    # ------------------------------------------------------------------
    # Gate & reveal logic
    # ------------------------------------------------------------------

    def get_day_number(self, profile: User) -> int:
        """Days since trial started. 0 if trial not started."""
        if profile.trial_started_at is None:
            return 0
        delta = datetime.now(timezone.utc) - profile.trial_started_at
        return delta.days

    def is_past_gate(self, profile: User) -> bool:
        """Has the user passed the 4-day gate?"""
        return self.get_day_number(profile) >= TOGGLE_GATE_DAYS

    def should_reveal_sleep(self, profile: User) -> bool:
        """Should we reveal sleep toggle? Morning after first night."""
        toggle = profile.toggles.sleep
        if toggle.status != "dormant" or toggle.revealed_at is not None:
            return False
        if profile.trial_started_at is None:
            return False
        # At least 1 day since trial started (meaning they've had a first night)
        return self.get_day_number(profile) >= 1

    def should_reveal_eating_window(self, profile: User) -> bool:
        """Should we reveal eating window toggle? After 4-day gate, evening."""
        toggle = profile.toggles.eating_window
        if toggle.status != "dormant" or toggle.revealed_at is not None:
            return False
        return self.is_past_gate(profile)

    def should_reveal_workouts(self, profile: User, weekday: int) -> bool:
        """Should we reveal workouts toggle? First Thursday after 4-day gate."""
        toggle = profile.toggles.workouts
        if toggle.status != "dormant" or toggle.revealed_at is not None:
            return False
        if weekday != WORKOUTS_ANCHOR_DAY:
            return False
        return self.is_past_gate(profile)

    def should_reveal_self_care(self, profile: User, weekday: int) -> bool:
        """Should we reveal self-care toggle? First Friday after 4-day gate."""
        toggle = profile.toggles.self_care
        if toggle.status != "dormant" or toggle.revealed_at is not None:
            return False
        if weekday != SELF_CARE_ANCHOR_DAY:
            return False
        return self.is_past_gate(profile)

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    def should_retry_target(self, profile: User, day_number: int) -> bool:
        """Should we retry the target offer? Day 9, dormant, not yet retried."""
        if profile.target_retry_done:
            return False
        toggle = profile.toggles.target_data
        if toggle.status != "dormant":
            return False
        return day_number >= TARGET_RETRY_DAY

    def should_retry_eating_window(self, profile: User) -> bool:
        """Should we retry eating window? 11 days after refusal, dormant."""
        if profile.eating_window_retry_done:
            return False
        toggle = profile.toggles.eating_window
        if toggle.status != "dormant":
            return False
        if toggle.revealed_at is None:
            return False
        days_since_reveal = (datetime.now(timezone.utc) - toggle.revealed_at).days
        return days_since_reveal >= EATING_WINDOW_RETRY_DAYS

    # ------------------------------------------------------------------
    # Dashboard intro
    # ------------------------------------------------------------------

    def should_show_dashboard_intro(self, profile: User, day_number: int) -> bool:
        """Should we show the dashboard intro hook? Day 16, not shown yet."""
        if profile.dashboard_intro_shown:
            return False
        return day_number >= DASHBOARD_INTRO_DAY
