"""
error_repository.py - גישה לקולקציית error_logs במונגו.

שומר שגיאות עם TTL של 30 יום.

תלוי ב: pymongo.
נצרך על ידי: bot.py (error handler).
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone


class ErrorRepository:
    def __init__(self, collection):
        self._collection = collection
        self._collection.create_index(
            "timestamp",
            expireAfterSeconds=30 * 24 * 60 * 60,
        )

    def log(
        self,
        error: Exception,
        handler: str,
        telegram_user_id: int | None,
        message_text: str,
        update_id: int | None,
    ) -> None:
        self._collection.insert_one({
            "timestamp": datetime.now(timezone.utc),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exception(error),
            "handler": handler,
            "telegram_user_id": telegram_user_id,
            "message_text": message_text,
            "update_id": update_id,
        })
