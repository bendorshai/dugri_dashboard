"""
trial_service.py - Trial period management.

Configurable trial duration loaded from config/trial_periods.yaml.
Trial ends at 19:00 local time on the Nth day after trial_started_at.

Depends on: repositories/user_repository, user_clock, config/trial_periods.yaml.
Used by: handlers/base.py, scheduler.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytz
import yaml

from models.profile import UserProfile
from repositories.user_repository import UserRepository
from user_clock import UserClock

logger = logging.getLogger(__name__)

TRIAL_EXPIRY_HOUR = 19  # Local time hour when trial expires
DEFAULT_TRIAL_DAYS = 12
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "trial_periods.yaml"


class TrialService:
    def __init__(
        self,
        user_repo: UserRepository,
        landing_page_url: str = "https://www.dugri.life",
        config_path: Path | None = None,
    ):
        self._user_repo = user_repo
        self._landing_page_url = landing_page_url
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._cohorts = self._load_cohorts()

    def _load_cohorts(self) -> list[dict]:
        try:
            text = self._config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            return data.get("cohorts", [{"trial_days": DEFAULT_TRIAL_DAYS}])
        except Exception:
            logger.warning("Failed to load trial config from %s, using default", self._config_path)
            return [{"trial_days": DEFAULT_TRIAL_DAYS}]

    def get_trial_days(self, profile: UserProfile) -> int:
        """Return the number of trial days for this user based on their signup date."""
        signup_date = None
        if profile.trial_started_at is not None:
            signup_date = profile.trial_started_at.date() if hasattr(profile.trial_started_at, 'date') else None

        for cohort in self._cohorts:
            start = cohort.get("start_date")
            end = cohort.get("end_date")
            if start is None and end is None:
                # Default fallback cohort
                return cohort.get("trial_days", DEFAULT_TRIAL_DAYS)
            if signup_date is not None:
                from datetime import date as date_type
                cohort_start = date_type.fromisoformat(start) if start else None
                cohort_end = date_type.fromisoformat(end) if end else None
                if cohort_start and signup_date < cohort_start:
                    continue
                if cohort_end and signup_date >= cohort_end:
                    continue
                return cohort.get("trial_days", DEFAULT_TRIAL_DAYS)

        return DEFAULT_TRIAL_DAYS

    def trial_expiry_dt(self, profile: UserProfile, clock: UserClock) -> datetime | None:
        """Compute the exact UTC datetime when the trial expires.

        Rule: add trial_days to trial_started_at in local time.
        If the resulting local time is >= 19:00, expiry is next day at 19:00.
        If before 19:00, expiry is same day at 19:00.
        """
        if profile.trial_started_at is None:
            return None

        trial_days = self.get_trial_days(profile)
        local_start = clock.to_local(profile.trial_started_at)
        raw_expiry_local = local_start + timedelta(days=trial_days)

        expiry_date = raw_expiry_local.date()
        if raw_expiry_local.hour >= TRIAL_EXPIRY_HOUR:
            expiry_date += timedelta(days=1)

        tz = local_start.tzinfo
        expiry_local = tz.localize(datetime.combine(expiry_date, time(TRIAL_EXPIRY_HOUR, 0, 0)))
        return expiry_local.astimezone(timezone.utc)

    def check_and_expire(self, profile: UserProfile, now: datetime) -> bool:
        """If trial has expired, flip to trial_ended. Returns True if just expired.

        Args:
            profile: User profile.
            now: Current time as UTC-aware datetime.
        """
        if profile.subscription_status != "trial_active":
            return False
        if profile.trial_started_at is None:
            return False

        clock = UserClock(profile.timezone, _now_override=now)
        expiry = self.trial_expiry_dt(profile, clock)
        if expiry is None:
            return False

        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        if now_utc >= expiry:
            updates = {"subscription_status": "trial_ended"}
            if not getattr(profile, 'trial_expiry_at', None):
                updates["trial_expiry_at"] = expiry.isoformat()
            self._user_repo.update_fields(profile.telegram_user_id, updates)
            return True
        return False

    def is_blocked(self, profile: UserProfile) -> bool:
        """True if trial ended and user hasn't paid."""
        return profile.subscription_status == "trial_ended"
