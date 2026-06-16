"""
feedback_repository.py - גישה לקולקציית weekly_feedback במונגו.

שומר ושולף פידבקים שבועיים שנוצרו על ידי GPT.

תלוי ב: pymongo.
נצרך על ידי: services, handlers.
"""

from __future__ import annotations

from datetime import datetime, timezone


class WeeklyFeedbackRepository:
    def __init__(self, collection):
        self._collection = collection

    def save(
        self,
        telegram_user_id: int,
        date_str: str,
        feedback_text: str,
        week_summary: dict,
    ) -> None:
        self._collection.insert_one({
            "telegram_user_id": telegram_user_id,
            "date": date_str,
            "feedback_text": feedback_text,
            "week_summary": week_summary,
            "created_at": datetime.now(timezone.utc),
        })

    def get_recent(
        self, telegram_user_id: int, limit: int = 7,
    ) -> list[dict]:
        cursor = (
            self._collection
            .find({"telegram_user_id": telegram_user_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        return list(cursor)
