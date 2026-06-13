"""
re_engagement_service.py - Re-engagement pipelines for inactive users.

Two pipelines:
- Pipeline A (Food Nudge): user is active but not logging food.
  Daily morning nudge, blocks sleep hooks. Resets when food is logged.
- Pipeline B (Complete Silence): user stops communicating.
  3-day escalation then permanent silence. Any message resets to normal.

Depends on: repositories/user_repository, repositories/food_repository,
            analyzer, models/profile, constants, user_clock, prompts.
Used by: scheduler, handlers/base.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import messages as M
import prompts as P
from constants import FOOD_NUDGE_WINDOW, RE_ENGAGEMENT_WINDOW
from models.profile import User, Toggles
from user_clock import UserClock

logger = logging.getLogger(__name__)


class SuppressionLevel(Enum):
    NONE = "none"
    BLOCK_SLEEP = "block_sleep"
    ALLOW_WEEKLY_ONLY = "allow_weekly"
    TOTAL = "total"


@dataclass
class ReEngagementAction:
    """Action to take for a re-engagement check."""
    new_stage: str
    message: str | None  # None = silent transition (no message to send)


class ReEngagementService:
    def __init__(self, user_repo, food_repo, analyzer):
        self._user_repo = user_repo
        self._food_repo = food_repo
        self._analyzer = analyzer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_suppression_level(self, profile: User) -> SuppressionLevel:
        """Return current suppression level based on re-engagement stage."""
        stage = profile.re_engagement_stage
        if stage == "silenced":
            return SuppressionLevel.TOTAL
        if stage in ("silence_day1", "silence_day2", "silence_day3"):
            return SuppressionLevel.ALLOW_WEEKLY_ONLY
        if stage == "food_nudge_pending":
            return SuppressionLevel.BLOCK_SLEEP
        return SuppressionLevel.NONE

    def check_re_engagement(
        self, profile: User, clock: UserClock,
    ) -> ReEngagementAction | None:
        """Determine what re-engagement action to take, if any.

        Returns None if no action needed. Otherwise returns an action
        describing what message to send and what stage to transition to.
        """
        if profile.last_user_message_at is None:
            return None  # New user, never messaged

        stage = profile.re_engagement_stage

        if stage == "silenced":
            return None  # Permanently silenced, nothing to do

        # -- Pipeline B: complete silence (overrides A) --
        action = self._check_silence_pipeline(profile, clock, stage)
        if action is not None:
            return action

        # -- Pipeline A: food nudge (user active, no food) --
        return self._check_food_nudge(profile, clock, stage)

    def transition_stage(self, tid: int, new_stage: str) -> None:
        """Update re_engagement_stage and re_engagement_last_sent_at."""
        self._user_repo.update_fields(tid, {
            "re_engagement_stage": new_stage,
            "re_engagement_last_sent_at": datetime.now(timezone.utc).isoformat(),
        })

    def handle_return(self, profile: User, tid: int) -> str | None:
        """Handle user returning from silence. Returns welcome message or None.

        - Resets stage to 'none'
        - Resets consecutive_unanswered on all active toggles
        - Generates GPT welcome-back message (only for silence stages)
        - Returns None for food_nudge_pending (user was actively chatting)
        """
        stage = profile.re_engagement_stage

        if stage not in ("silence_day1", "silence_day2", "silence_day3", "silenced"):
            # Pipeline A or already normal - just reset, no welcome
            self._user_repo.update_fields(tid, {"re_engagement_stage": "none"})
            return None

        # Reset stage + consecutive_unanswered for active toggles
        fields: dict = {"re_engagement_stage": "none"}
        for toggle_name in Toggles.model_fields:
            toggle = getattr(profile.toggles, toggle_name)
            if toggle.status == "active" and toggle.consecutive_unanswered > 0:
                fields[f"toggles.{toggle_name}.consecutive_unanswered"] = 0

        self._user_repo.update_fields(tid, fields)

        # Generate welcome-back message
        return self._generate_welcome_back(profile)

    # ------------------------------------------------------------------
    # Pipeline B: Complete Silence
    # ------------------------------------------------------------------

    def _check_silence_pipeline(
        self, profile: User, clock: UserClock, stage: str,
    ) -> ReEngagementAction | None:
        """Check if silence pipeline should fire."""
        days_silent = self._days_since_last_message(profile, clock)
        if days_silent is None or days_silent < 1:
            return None

        now = clock.now()
        start_h, end_h = RE_ENGAGEMENT_WINDOW

        # Entry into silence pipeline from none or food_nudge_pending
        if stage in ("none", "food_nudge_pending"):
            if not (start_h <= now.hour < end_h):
                return None
            if self._already_sent_today(profile, clock):
                return None
            return ReEngagementAction(
                new_stage="silence_day1",
                message=random.choice(M.SILENCE_DAY1),
            )

        # Progression within silence pipeline
        if stage == "silence_day1" and days_silent >= 2:
            if self._already_sent_today(profile, clock):
                return None
            return ReEngagementAction(
                new_stage="silence_day2",
                message=self._generate_smart_question(profile),
            )

        if stage == "silence_day2" and days_silent >= 3:
            if self._already_sent_today(profile, clock):
                return None
            return ReEngagementAction(
                new_stage="silence_day3",
                message=self._generate_context_message(profile),
            )

        if stage == "silence_day3" and days_silent >= 4:
            return ReEngagementAction(
                new_stage="silenced",
                message=None,  # Silent transition
            )

        return None

    # ------------------------------------------------------------------
    # Pipeline A: Food Nudge
    # ------------------------------------------------------------------

    def _check_food_nudge(
        self, profile: User, clock: UserClock, stage: str,
    ) -> ReEngagementAction | None:
        """Check if food nudge should fire."""
        tid = profile.telegram_user_id

        # If currently in food_nudge_pending, check if food was logged
        if stage == "food_nudge_pending":
            if self._has_food_today_or_yesterday(profile, clock):
                return ReEngagementAction(new_stage="none", message=None)
            return None  # Still pending, no new message

        # Only fire from "none" stage
        if stage != "none":
            return None

        # Check conditions for new food nudge
        now = clock.now()
        start_h, end_h = FOOD_NUDGE_WINDOW
        if not (start_h <= now.hour < end_h):
            return None

        if self._already_sent_today(profile, clock):
            return None

        # User must be active (messaged within 24h) but no food yesterday
        if not self._is_user_active(profile, clock):
            return None

        if self._has_food_yesterday(profile, clock):
            return None

        return ReEngagementAction(
            new_stage="food_nudge_pending",
            message=random.choice(M.FOOD_NUDGE),
        )

    # ------------------------------------------------------------------
    # GPT message generation
    # ------------------------------------------------------------------

    def _generate_smart_question(self, profile: User) -> str:
        """Generate personalized day-2 question via GPT."""
        context = self._build_user_context(profile)
        prompt = P.RE_ENGAGEMENT_SMART_QUESTION.format(**context)
        try:
            response = self._analyzer._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "generate"},
                ],
                temperature=0.7,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("Failed to generate smart question")
            return random.choice(M.SILENCE_DAY1)  # Fallback

    def _generate_context_message(self, profile: User) -> str:
        """Generate day-3 context/farewell message via GPT."""
        context = self._build_user_context_for_farewell(profile)
        prompt = P.RE_ENGAGEMENT_CONTEXT_MESSAGE.format(**context)
        try:
            response = self._analyzer._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "generate"},
                ],
                temperature=0.7,
                max_tokens=400,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("Failed to generate context message")
            return random.choice(M.SILENCE_DAY1)  # Fallback

    def _generate_welcome_back(self, profile: User) -> str:
        """Generate GPT welcome-back message listing active habits."""
        active_toggles = self._get_active_toggle_names(profile)
        prompt = P.RE_ENGAGEMENT_WELCOME_BACK.format(
            name=profile.name or "",
            active_toggles=", ".join(active_toggles) if active_toggles else "ארוחות",
        )
        try:
            response = self._analyzer._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "generate"},
                ],
                temperature=0.7,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("Failed to generate welcome back message")
            return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _days_since_last_message(self, profile: User, clock: UserClock) -> int | None:
        """Days since user's last message, using local dates."""
        if profile.last_user_message_at is None:
            return None
        last_local = clock.local_date(profile.last_user_message_at)
        today = clock.today()
        return (today - last_local).days

    def _already_sent_today(self, profile: User, clock: UserClock) -> bool:
        """Check if a re-engagement message was already sent today."""
        if profile.re_engagement_last_sent_at is None:
            return False
        return clock.is_same_local_day(profile.re_engagement_last_sent_at)

    def _is_user_active(self, profile: User, clock: UserClock) -> bool:
        """User is considered active if they messaged within the last 24h."""
        if profile.last_user_message_at is None:
            return False
        now_utc = datetime.now(timezone.utc)
        return (now_utc - profile.last_user_message_at) < timedelta(hours=24)

    def _has_food_yesterday(self, profile: User, clock: UserClock) -> bool:
        """Check if user logged any food entries yesterday (calendar day)."""
        yesterday = (clock.today() - timedelta(days=1)).strftime("%d/%m/%Y")
        entries = self._food_repo.get_by_user_and_dates(
            profile.telegram_user_id, [yesterday],
        )
        return len(entries) > 0

    def _has_food_today_or_yesterday(self, profile: User, clock: UserClock) -> bool:
        """Check if user logged food today or yesterday."""
        today = clock.today().strftime("%d/%m/%Y")
        yesterday = (clock.today() - timedelta(days=1)).strftime("%d/%m/%Y")
        entries = self._food_repo.get_by_user_and_dates(
            profile.telegram_user_id, [today, yesterday],
        )
        return len(entries) > 0

    def _get_active_toggle_names(self, profile: User) -> list[str]:
        """Get Hebrew names of active toggles."""
        toggle_names = {
            "sleep": "שינה",
            "workouts": "אימונים",
            "self_care": "משהו לעצמי",
            "eating_window": "חלון אכילה",
        }
        active = []
        for name, hebrew in toggle_names.items():
            toggle = getattr(profile.toggles, name)
            if toggle.status == "active":
                active.append(hebrew)
        return active

    def _build_user_context(self, profile: User) -> dict:
        """Build context dict for GPT smart question prompt."""
        active_toggles = self._get_active_toggle_names(profile)
        days_active = 0
        if profile.trial_started_at:
            days_active = (datetime.now(timezone.utc) - profile.trial_started_at).days

        patterns = [p.pattern for p in (profile.discovered_patterns or [])]

        # Count food days
        all_entries = self._food_repo.get_all_for_user(profile.telegram_user_id)
        food_days = len({e.date for e in all_entries}) if all_entries else 0

        return {
            "name": profile.name or "",
            "days_active": days_active,
            "active_toggles": ", ".join(active_toggles) if active_toggles else "ללא",
            "food_days_count": food_days,
            "patterns": ", ".join(patterns) if patterns else "לא זוהו דפוסים עדיין",
        }

    def _build_user_context_for_farewell(self, profile: User) -> dict:
        """Build context dict for GPT context/farewell message prompt."""
        ctx = self._build_user_context(profile)
        all_entries = self._food_repo.get_all_for_user(profile.telegram_user_id)
        ctx["total_meals"] = len(all_entries) if all_entries else 0
        ctx["habits_tracked"] = ctx["active_toggles"]
        return ctx
