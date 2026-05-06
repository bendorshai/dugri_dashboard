from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from pymongo import MongoClient, DESCENDING

logger = logging.getLogger(__name__)

ERROR_LOG_TTL_DAYS = 30


class MongoStorage:
    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self._profiles = self._db["user_profiles"]
        self._feedback = self._db["weekly_feedback"]
        self._insights = self._db["gpt_insights"]
        self._errors = self._db["error_logs"]
        self._ensure_error_indexes()
        logger.info("MongoDB connected: %s / %s", uri.split("@")[-1], db_name)

    def _ensure_error_indexes(self) -> None:
        try:
            self._errors.create_index(
                "timestamp", expireAfterSeconds=ERROR_LOG_TTL_DAYS * 86400,
            )
        except Exception:
            logger.debug("Error log TTL index already exists or could not be created")

    # ------------------------------------------------------------------
    # User profiles
    # ------------------------------------------------------------------

    def get_user_profile(self, chat_id: int) -> dict | None:
        return self._profiles.find_one({"_id": chat_id})

    def save_user_profile(self, chat_id: int, data: dict) -> None:
        data["updated_at"] = datetime.now(timezone.utc)
        self._profiles.update_one(
            {"_id": chat_id},
            {"$set": data, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    # ------------------------------------------------------------------
    # Weekly feedback
    # ------------------------------------------------------------------

    def save_weekly_feedback(
        self,
        chat_id: int,
        date_str: str,
        feedback_text: str,
        week_summary: dict,
    ) -> None:
        self._feedback.insert_one({
            "chat_id": chat_id,
            "date": date_str,
            "feedback_text": feedback_text,
            "week_summary": week_summary,
            "created_at": datetime.now(timezone.utc),
        })

    def get_recent_feedbacks(self, chat_id: int, limit: int = 7) -> list[dict]:
        return list(
            self._feedback.find({"chat_id": chat_id})
            .sort("created_at", DESCENDING)
            .limit(limit)
        )

    # ------------------------------------------------------------------
    # GPT insights
    # ------------------------------------------------------------------

    def save_gpt_insight(
        self,
        chat_id: int,
        insight_type: str,
        insight_text: str,
        context: dict,
    ) -> None:
        self._insights.insert_one({
            "chat_id": chat_id,
            "insight_type": insight_type,
            "insight_text": insight_text,
            "context": context,
            "created_at": datetime.now(timezone.utc),
        })

    def get_recent_insights(self, chat_id: int, limit: int = 10) -> list[dict]:
        return list(
            self._insights.find({"chat_id": chat_id})
            .sort("created_at", DESCENDING)
            .limit(limit)
        )

    # ------------------------------------------------------------------
    # Error logging
    # ------------------------------------------------------------------

    def log_error(
        self,
        error: BaseException | None = None,
        *,
        handler: str = "",
        chat_id: int | None = None,
        message_text: str = "",
        update_id: int | None = None,
    ) -> None:
        doc = {
            "timestamp": datetime.now(timezone.utc),
            "error_type": type(error).__name__ if error else "Unknown",
            "error_message": str(error) if error else "",
            "traceback": traceback.format_exception(error) if error else [],
            "handler": handler,
            "chat_id": chat_id,
            "message_text": message_text[:500] if message_text else "",
            "update_id": update_id,
        }
        try:
            self._errors.insert_one(doc)
        except Exception:
            logger.exception("Failed to log error to MongoDB")
