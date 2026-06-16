"""
self_care_repository.py - גישה לקולקציית self_care_logs.
"""

from __future__ import annotations

from bson import ObjectId

from models.self_care import SelfCareLog, compute_week_id
from repositories.base import BaseRepository


class SelfCareRepository(BaseRepository[SelfCareLog]):
    def __init__(self, collection):
        super().__init__(collection, SelfCareLog)

    def add(self, log: SelfCareLog) -> SelfCareLog:
        return self.insert(log)

    def get_for_week(self, telegram_user_id: int, week_id: str) -> list[SelfCareLog]:
        return self.find({"telegram_user_id": telegram_user_id, "week_id": week_id})

    def get_for_date(self, telegram_user_id: int, date: str) -> list[SelfCareLog]:
        return self.find({"telegram_user_id": telegram_user_id, "date": date})

    def move(self, entry_id: str, new_date: str) -> None:
        self.update_by_id(ObjectId(entry_id), {
            "date": new_date,
            "week_id": compute_week_id(new_date),
        })

    def get_recent(self, telegram_user_id: int, limit: int = 7) -> list[SelfCareLog]:
        docs = (
            self._collection
            .find({"telegram_user_id": telegram_user_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [self._to_model(doc) for doc in docs]
