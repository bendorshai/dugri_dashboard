"""
sleep_repository.py - גישה לקולקציית sleep_logs.
"""

from __future__ import annotations

from bson import ObjectId

from models.sleep import SleepLog
from repositories.base import BaseRepository


class SleepRepository(BaseRepository[SleepLog]):
    def __init__(self, collection):
        super().__init__(collection, SleepLog)

    def add(self, log: SleepLog) -> SleepLog:
        return self.insert(log)

    def move(self, entry_id: str, new_date: str, new_sleep_time: str | None = None) -> None:
        fields: dict = {"date": new_date}
        if new_sleep_time is not None:
            fields["sleep_time"] = new_sleep_time
        self.update_by_id(ObjectId(entry_id), fields)

    def get_for_user_and_date(self, telegram_user_id: int, date: str) -> SleepLog | None:
        return self.find_one({"telegram_user_id": telegram_user_id, "date": date})

    def get_recent(self, telegram_user_id: int, limit: int = 7) -> list[SleepLog]:
        docs = (
            self._collection
            .find({"telegram_user_id": telegram_user_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [self._to_model(doc) for doc in docs]
