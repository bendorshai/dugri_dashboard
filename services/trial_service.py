"""
trial_service.py — ניהול תקופת ניסיון 21 יום.

בודק ומנהל את מצב תקופת הניסיון. נשען על UserRepository.

תלוי ב: repositories/user_repository.
נצרך על ידי: handlers/base.py, scheduler.
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.profile import UserProfile
from repositories.user_repository import UserRepository


TRIAL_DAYS = 21


class TrialService:
    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo

    def check_and_expire(self, profile: UserProfile, now: datetime) -> bool:
        """If trial has expired, flip to trial_ended. Returns True if expired now."""
        if profile.subscription_status != "trial_active":
            return False
        if profile.trial_started_at is None:
            return False

        days_elapsed = (now - profile.trial_started_at).days
        if days_elapsed >= TRIAL_DAYS:
            self._user_repo.update_fields(profile.telegram_user_id, {
                "subscription_status": "trial_ended",
            })
            return True
        return False

    def is_blocked(self, profile: UserProfile) -> bool:
        """True if trial ended and user hasn't paid."""
        return profile.subscription_status == "trial_ended"

    def get_blocked_message(self) -> str:
        return (
            "התקופת ניסיון שלך עם דוגרי הסתיימה.\n"
            "בא לך להמשיך? 47 ₪ בחודש — אפשר לבטל בלחיצה.\n\n"
            "https://dugri.co.il/subscribe"
        )

    def get_expiry_message(self) -> str:
        return (
            "21 הימים שלך עם דוגרי הסתיימו.\n"
            "בא לך להמשיך? 47 ₪ בחודש — אפשר לבטל בלחיצה.\n\n"
            "https://dugri.co.il/subscribe"
        )
