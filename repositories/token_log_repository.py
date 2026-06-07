"""
token_log_repository.py — daily per-model token usage aggregates.

Each document represents one (user, model, date) combination.
Uses $inc with upsert for atomic accumulation.

Collection: token_logs
Document shape: {telegram_user_id, model, date, prompt_tokens, completion_tokens}
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TokenLogRepository:
    def __init__(self, collection):
        self._collection = collection
        try:
            collection.create_index(
                [("telegram_user_id", 1), ("model", 1), ("date", 1)],
                unique=True,
            )
            collection.create_index("date")
        except Exception:
            logger.warning("Could not create token_logs indexes")

    def log(self, telegram_user_id: int, model: str, date: str,
            prompt_tokens: int, completion_tokens: int) -> None:
        """Atomically accumulate token usage for a (user, model, date) triple."""
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return
        self._collection.update_one(
            {
                "telegram_user_id": telegram_user_id,
                "model": model,
                "date": date,
            },
            {"$inc": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }},
            upsert=True,
        )

    def get_usage(self, start_date: str, end_date: str) -> list[dict]:
        """Aggregate token usage by date and model within a date range.

        Returns list of {date, model, prompt_tokens, completion_tokens}.
        """
        pipeline = [
            {"$match": {"date": {"$gte": start_date, "$lte": end_date}}},
            {"$group": {
                "_id": {"date": "$date", "model": "$model"},
                "prompt_tokens": {"$sum": "$prompt_tokens"},
                "completion_tokens": {"$sum": "$completion_tokens"},
            }},
            {"$sort": {"_id.date": 1, "_id.model": 1}},
        ]
        results = []
        for doc in self._collection.aggregate(pipeline):
            results.append({
                "date": doc["_id"]["date"],
                "model": doc["_id"]["model"],
                "prompt_tokens": doc["prompt_tokens"],
                "completion_tokens": doc["completion_tokens"],
            })
        return results

    def get_totals(self, start_date: str, end_date: str) -> dict[str, dict[str, int]]:
        """Sum tokens by model within a date range.

        Returns {model: {prompt_tokens, completion_tokens}}.
        """
        pipeline = [
            {"$match": {"date": {"$gte": start_date, "$lte": end_date}}},
            {"$group": {
                "_id": "$model",
                "prompt_tokens": {"$sum": "$prompt_tokens"},
                "completion_tokens": {"$sum": "$completion_tokens"},
            }},
        ]
        result = {}
        for doc in self._collection.aggregate(pipeline):
            result[doc["_id"]] = {
                "prompt_tokens": doc["prompt_tokens"],
                "completion_tokens": doc["completion_tokens"],
            }
        return result
