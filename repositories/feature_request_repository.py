"""
feature_request_repository.py - לוגים של בקשות פיצ'ר, דיווחי באגים, והרגלים חסרים.

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
        request_type: str | None = None,
        message_id: int | None = None,
        chat_id: int | None = None,
        chat_history: list[dict] | None = None,
    ) -> None:
        doc = {
            "timestamp": datetime.now(timezone.utc),
            "telegram_user_id": telegram_user_id,
            "question_text": question_text,
            "bot_response": bot_response,
        }
        if request_type is not None:
            doc["request_type"] = request_type
        if message_id is not None:
            doc["message_id"] = message_id
        if chat_id is not None:
            doc["chat_id"] = chat_id
        if chat_history is not None:
            doc["chat_history"] = chat_history
        self._collection.insert_one(doc)
