"""
feature_request_repository.py — לוגים של שאלות שדוגרי לא ידע לענות עליהן.

שומר בקשות פיצ'ר עם TTL של 90 יום.

תלוי ב: pymongo.
נצרך על ידי: services/message_router_service.
"""

from __future__ import annotations

from datetime import datetime, timezone


class FeatureRequestRepository:
    def __init__(self, collection):
        self._collection = collection
        self._collection.create_index(
            "timestamp",
            expireAfterSeconds=90 * 24 * 60 * 60,
        )

    def log(
        self,
        telegram_user_id: int,
        question_text: str,
        bot_response: str,
    ) -> None:
        self._collection.insert_one({
            "timestamp": datetime.now(timezone.utc),
            "telegram_user_id": telegram_user_id,
            "question_text": question_text,
            "bot_response": bot_response,
        })
