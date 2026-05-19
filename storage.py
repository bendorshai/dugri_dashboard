from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

logger = logging.getLogger(__name__)

SIGNUP_TOKEN_LIFETIME_HOURS = 24


class DashboardStorage:
    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self._users = self._db["dashboard_users"]
        logger.info("Dashboard MongoDB connected: %s / %s", uri.split("@")[-1], db_name)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_user(self, email: str) -> dict | None:
        return self._users.find_one({"_id": email})

    def create_user(
        self,
        email: str,
        name: str,
        photo_url: str | None = None,
        consents: dict | None = None,
    ) -> dict:
        now = self._now()
        doc = {
            "_id": email,
            "name": name,
            "photo_url": photo_url,
            "telegram_user_id": None,
            "signup_session_token": None,
            "signup_session_token_expires_at": None,
            "consents": consents or {},
            "trial_started_at": None,
            "subscription_status": "trial_pending",
            # Legacy fields kept for backward compat with existing users
            "birth_year": None,
            "height_cm": None,
            "weight_kg": None,
            "goals": {},
            "bot_key": "",
            "onboarding_complete": True,
            "terms_accepted": True,
            "created_at": now,
            "updated_at": now,
        }
        self._users.insert_one(doc)
        return doc

    def update_user_profile(self, email: str, data: dict) -> None:
        data["updated_at"] = self._now()
        self._users.update_one({"_id": email}, {"$set": data})

    def update_user_goals(self, email: str, goals: dict) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "goals": goals,
                "updated_at": self._now(),
            }},
        )

    def complete_onboarding(self, email: str) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "onboarding_complete": True,
                "updated_at": self._now(),
            }},
        )

    # -- Signup session token methods --

    def set_signup_session_token(
        self, email: str, token: str, expires_at: str,
    ) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "signup_session_token": token,
                "signup_session_token_expires_at": expires_at,
                "updated_at": self._now(),
            }},
        )

    def regenerate_signup_session_token(self, email: str) -> str:
        token = secrets.token_urlsafe(24)
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=SIGNUP_TOKEN_LIFETIME_HOURS)
        ).isoformat()
        self.set_signup_session_token(email, token, expires_at)
        return token

    def get_user_by_session_token(self, token: str) -> dict | None:
        now = self._now()
        return self._users.find_one({
            "signup_session_token": token,
            "signup_session_token_expires_at": {"$gt": now},
        })
