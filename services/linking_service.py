"""
linking_service.py — קישור חשבון טלגרם לפרופיל שנוצר באתר.

מטפל ב-/start <token>: מוצא את הפרופיל לפי טוקן באתר, מקשר את telegram_user_id,
יוצר פרופיל בוט, ומתחיל trial.

תלוי ב: repositories/user_repository, pymongo (לגישה ל-dashboard_users).
נצרך על ידי: handlers/start_handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from models.profile import UserProfile
from repositories.user_repository import UserRepository


@dataclass
class LinkResult:
    status: str  # "linked" | "already_linked" | "invalid"
    profile: UserProfile | None = None
    name: str | None = None


class LinkingService:
    def __init__(self, user_repo: UserRepository, dashboard_users_collection):
        self._user_repo = user_repo
        self._dashboard_users = dashboard_users_collection

    def link(self, telegram_user_id: int, token: str) -> LinkResult:
        """Attempt to link a Telegram user to a dashboard profile via signup token."""
        now_iso = datetime.now(timezone.utc).isoformat()
        dashboard_user = self._dashboard_users.find_one({
            "signup_session_token": token,
            "signup_session_token_expires_at": {"$gt": now_iso},
        })

        if dashboard_user is None:
            return LinkResult(status="invalid")

        if dashboard_user.get("telegram_user_id") is not None:
            existing_profile = self._user_repo.get(telegram_user_id)
            return LinkResult(status="already_linked", profile=existing_profile)

        email = dashboard_user["_id"]
        name = dashboard_user.get("name")

        # Update dashboard_users: link telegram_user_id, clear token
        self._dashboard_users.update_one(
            {"_id": email},
            {"$set": {
                "telegram_user_id": telegram_user_id,
                "signup_session_token": None,
                "signup_session_token_expires_at": None,
                "subscription_status": "trial_active",
                "trial_started_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

        # Create bare bot profile — goals are collected in-bot via onboarding
        profile = UserProfile(
            telegram_user_id=telegram_user_id,
            email=email,
            subscription_status="trial_active",
            trial_started_at=datetime.now(timezone.utc),
        )
        self._user_repo.save(profile)

        return LinkResult(status="linked", profile=profile, name=name)

    def get_profile_without_token(self, telegram_user_id: int) -> UserProfile | None:
        """Check if a user already has a bot profile (for /start without token)."""
        return self._user_repo.get(telegram_user_id)
