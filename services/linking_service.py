"""
linking_service.py — קישור חשבון טלגרם לפרופיל שנוצר באתר.

מטפל ב-/start <token>: מוצא את המשתמש לפי טוקן, מקשר את telegram_user_id,
ומתחיל trial.

תלוי ב: repositories/user_repository.
נצרך על ידי: handlers/start_handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from models.profile import User
from repositories.user_repository import UserRepository


@dataclass
class LinkResult:
    status: str  # "linked" | "already_linked" | "invalid"
    profile: User | None = None
    name: str | None = None


class LinkingService:
    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo

    def link(self, telegram_user_id: int, token: str) -> LinkResult:
        """Attempt to link a Telegram user to a dashboard profile via signup token."""
        user = self._user_repo.get_by_signup_token(token)

        if user is None:
            return LinkResult(status="invalid")

        if user.telegram_user_id is not None:
            return LinkResult(status="already_linked", profile=user)

        # Update the user doc: set telegram_user_id, clear token, start trial
        self._user_repo.update_fields_by_email(user.email, {
            "telegram_user_id": telegram_user_id,
            "signup_session_token": None,
            "signup_session_token_expires_at": None,
            "subscription_status": "trial_active",
            "trial_started_at": datetime.now(timezone.utc).isoformat(),
        })

        updated = self._user_repo.get(telegram_user_id)
        return LinkResult(status="linked", profile=updated, name=updated.name)

    def get_profile_without_token(self, telegram_user_id: int) -> User | None:
        """Check if a user already has a linked profile (for /start without token)."""
        return self._user_repo.get(telegram_user_id)
