"""
user_repository.py — גישה לקולקציית users במונגו.

כל משתמש מזוהה לפי email שהוא ה-_id של המסמך.
הבוט מחפש לפי telegram_user_id (אינדקס ייחודי).

תלוי ב: repositories/base, models/profile.
נצרך על ידי: services, handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from models.profile import User
from repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository[User]):
    def __init__(self, collection):
        super().__init__(collection, User)
        try:
            collection.create_index("telegram_user_id", unique=True, sparse=True)
        except Exception:
            logger.warning("Could not create telegram_user_id index (disk space?)")

    def get(self, telegram_user_id: int) -> User | None:
        """Bot's primary lookup — queries by telegram_user_id field."""
        return self.find_one({"telegram_user_id": telegram_user_id})

    def get_by_email(self, email: str) -> User | None:
        """Dashboard lookup — queries by _id (email)."""
        return self.get_by_id(email)

    def get_by_signup_token(self, token: str) -> User | None:
        now = datetime.now(timezone.utc).isoformat()
        return self.find_one({
            "signup_session_token": token,
            "signup_session_token_expires_at": {"$gt": now},
        })

    def save(self, user: User) -> None:
        """Upsert: create or fully replace the user document."""
        user.updated_at = datetime.now(timezone.utc)
        doc = user.to_mongo_dict()
        self._collection.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True,
        )

    def update_fields(self, telegram_user_id: int, fields: dict) -> None:
        """Atomic partial update by telegram_user_id (bot callers)."""
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._collection.update_one(
            {"telegram_user_id": telegram_user_id}, {"$set": fields},
        )

    def update_fields_by_email(self, email: str, fields: dict) -> None:
        """Atomic partial update by email / _id (dashboard callers)."""
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.update_by_id(email, fields)

    def push_to_list(self, telegram_user_id: int, field: str, item: dict) -> None:
        """Atomically append an item to a list field."""
        self._collection.update_one(
            {"telegram_user_id": telegram_user_id},
            {
                "$push": {field: item},
                "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
            },
        )

    def push_messages(self, telegram_user_id: int, messages: list[dict], max_messages: int = 8) -> None:
        """Atomically append messages and trim to last max_messages."""
        self._collection.update_one(
            {"telegram_user_id": telegram_user_id},
            {
                "$push": {
                    "recent_messages": {
                        "$each": messages,
                        "$slice": -max_messages,
                    }
                },
                "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
            },
        )

    def get_recent_messages(self, telegram_user_id: int, limit: int = 8) -> list[dict]:
        """Fetch recent_messages array for a user."""
        doc = self._collection.find_one(
            {"telegram_user_id": telegram_user_id},
            {"recent_messages": 1},
        )
        if doc is None:
            return []
        return (doc.get("recent_messages") or [])[-limit:]
