"""
inappropriate_log_repository.py - Permanent log of inappropriate messages.

No TTL - these records are kept forever for audit purposes.

Depends on: pymongo.
Used by: services/inappropriate_service.py.
"""

from __future__ import annotations

from datetime import datetime, timezone


class InappropriateLogRepository:
    def __init__(self, collection):
        self._collection = collection
        self._collection.create_index("telegram_user_id")

    def log(self, telegram_user_id: int, message_text: str) -> None:
        self._collection.insert_one({
            "telegram_user_id": telegram_user_id,
            "message_text": message_text,
            "created_at": datetime.now(timezone.utc),
        })

    def get_by_user(self, telegram_user_id: int) -> list[dict]:
        return list(
            self._collection.find(
                {"telegram_user_id": telegram_user_id},
                {"_id": 0, "message_text": 1, "created_at": 1},
            ).sort("created_at", 1)
        )
