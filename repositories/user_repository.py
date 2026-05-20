"""
user_repository.py — גישה לקולקציית user_profiles במונגו.

כל פרופיל מזוהה לפי telegram_user_id שהוא ה-_id של המסמך.

תלוי ב: repositories/base, models/profile.
נצרך על ידי: services, handlers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.profile import UserProfile
from repositories.base import BaseRepository


class UserRepository(BaseRepository[UserProfile]):
    def __init__(self, collection):
        super().__init__(collection, UserProfile)

    def get(self, telegram_user_id: int) -> UserProfile | None:
        return self.get_by_id(telegram_user_id)

    def get_by_signup_token(self, token: str) -> UserProfile | None:
        now = datetime.now(timezone.utc).isoformat()
        return self.find_one({
            "signup_session_token": token,
            "signup_session_token_expires_at": {"$gt": now},
        })

    def save(self, profile: UserProfile) -> None:
        """Upsert: create or fully replace the profile document."""
        profile.updated_at = datetime.now(timezone.utc)
        doc = profile.to_mongo_dict()
        self._collection.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True,
        )

    def update_fields(self, telegram_user_id: int, fields: dict) -> None:
        """Atomic partial update via $set."""
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.update_by_id(telegram_user_id, fields)
