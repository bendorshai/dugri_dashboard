"""
toggle_service.py — Central service for habit toggle state management.

Handles all toggle state transitions (dormant/active/cancelled), gate logic,
reveal timing, exit door mechanics, unanswered tracking, and goal state helpers.

Depends on: repositories/user_repository, models/profile, constants.
Used by: handlers/base, scheduler, goal_service, onboarding_service.
"""

from __future__ import annotations

from datetime import datetime, timezone

from constants import (
    TOGGLE_GATE_DAYS,
    DASHBOARD_INTRO_DAY,
    EXIT_DOOR_UNANSWERED_THRESHOLD,
    WORKOUTS_ANCHOR_DAY,
    SELF_CARE_ANCHOR_DAY,
    HOOK_CONFIG,
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
        """User accepted - toggle becomes active."""
        now = datetime.now(timezone.utc).isoformat()
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.status": "active",
            f"toggles.{toggle_name}.activated_at": now,
            f"toggles.{toggle_name}.consecutive_unanswered": 0,
        })

    def cancel_toggle(self, telegram_user_id: int, toggle_name: str) -> None:
        """User cancelled - toggle is off forever (unless reset)."""
        self._user_repo.update_fields(telegram_user_id, {
            f"toggles.{toggle_name}.status": "cancelled",
        })

    # ------------------------------------------------------------------
    # Goal state helpers
    # ------------------------------------------------------------------

    def set_goal_value(self, tid: int, toggle_name: str, value: dict) -> None:
        """Store goal value and mark as set."""
        now = datetime.now(timezone.utc).isoformat()
        self._user_repo.update_fields(tid, {
            f"toggles.{toggle_name}.goal_value": value,
            f"toggles.{toggle_name}.goal_status": "set",
            f"toggles.{toggle_name}.goal_offered_at": now,
        })

    def set_goal_status(
        self, tid: int, toggle_name: str, status: str, remind_at: datetime | None = None,
    ) -> None:
        """Update goal status (and optionally remind_at)."""
        fields: dict = {f"toggles.{toggle_name}.goal_status": status}
        if remind_at is not None:
            fields[f"toggles.{toggle_name}.goal_remind_at"] = remind_at.isoformat()
        else:
            fields[f"toggles.{toggle_name}.goal_remind_at"] = None
        self._user_repo.update_fields(tid, fields)

    def set_goal_offered(self, tid: int, toggle_name: str) -> None:
        """Record that a goal was offered (timestamp only)."""
        now = datetime.now(timezone.utc).isoformat()
        self._user_repo.update_fields(tid, {
            f"toggles.{toggle_name}.goal_offered_at": now,
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
        """User answered the hook - reset unanswered counter."""
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

    def should_reveal_nutrition(self, profile: User) -> bool:
        """Should we reveal nutrition toggle? After first meal, dormant, not revealed."""
        toggle = profile.toggles.nutrition
        if toggle.status != "dormant" or toggle.revealed_at is not None:
            return False
        if not profile.onboarding.name_collected:
            return False
        return profile.trial_started_at is not None

    def should_reveal_sleep(self, profile: User) -> bool:
        """Should we reveal sleep toggle? Morning after first night."""
        toggle = profile.toggles.sleep
        if toggle.status != "dormant" or toggle.revealed_at is not None:
            return False
        if profile.trial_started_at is None:
            return False
        return self.get_day_number(profile) >= 1

    def should_reveal_eating_window(self, profile: User) -> bool:
        """Should we reveal eating window toggle? After 4-day gate."""
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
    # Dashboard intro
    # ------------------------------------------------------------------

    def should_show_dashboard_intro(self, profile: User, day_number: int) -> bool:
        """Should we show the dashboard intro hook? Day 16, not shown yet."""
        if profile.dashboard_intro_shown:
            return False
        return day_number >= DASHBOARD_INTRO_DAY

    # ------------------------------------------------------------------
    # Debug: predict next step
    # ------------------------------------------------------------------

    def predict_next_step(self, profile: User) -> str:
        """Return a human-readable prediction of Dugri's next toggle action."""
        day_number = self.get_day_number(profile)
        anchor_day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

        reveal_order = [
            ("nutrition", 0, None),
            ("sleep", 1, None),
            ("eating_window", TOGGLE_GATE_DAYS, None),
            ("workouts", TOGGLE_GATE_DAYS, WORKOUTS_ANCHOR_DAY),
            ("self_care", TOGGLE_GATE_DAYS, SELF_CARE_ANCHOR_DAY),
        ]

        for toggle_name, gate_days, anchor_day in reveal_order:
            toggle = getattr(profile.toggles, toggle_name)
            if toggle.status == "cancelled":
                continue

            if toggle.status == "dormant" and toggle.revealed_at is None:
                days_until = max(0, gate_days - day_number)
                if days_until > 0:
                    if anchor_day is not None:
                        return f"reveal {toggle_name} - in {days_until}d, {anchor_day_names[anchor_day]} only"
                    return f"reveal {toggle_name} - in {days_until}d"
                if anchor_day is not None:
                    return f"reveal {toggle_name} - next {anchor_day_names[anchor_day]}"
                # gate=0 means after next meal (nutrition)
                if gate_days == 0:
                    return f"reveal {toggle_name} - after next meal"
                return f"reveal {toggle_name} - ready now"

            if toggle.status == "dormant" and toggle.revealed_at is not None:
                return f"waiting for user to accept {toggle_name}"

            if toggle.status == "active":
                if toggle.goal_status == "pending" and toggle.goal_offered_at:
                    return f"waiting for user to set {toggle_name} goal"
                if toggle.goal_status == "pending" and not toggle.goal_offered_at:
                    return f"offer {toggle_name} goal - next hook"
                if toggle.goal_status == "remind_pending":
                    return f"waiting for user to decide on {toggle_name} goal reminder"
                if toggle.goal_status == "remind" and toggle.goal_remind_at:
                    remind_date = toggle.goal_remind_at.strftime("%Y-%m-%d")
                    return f"remind {toggle_name} goal - on {remind_date}"

        return "all toggles resolved"
