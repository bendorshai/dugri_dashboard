"""
workout_repository.py — גישה לקולקציית workout_logs.
"""

from __future__ import annotations

from bson import ObjectId

from models.workout import WorkoutLog
from repositories.base import BaseRepository


class WorkoutRepository(BaseRepository[WorkoutLog]):
    def __init__(self, collection):
        super().__init__(collection, WorkoutLog)

    def add(self, log: WorkoutLog) -> WorkoutLog:
        return self.insert(log)

    def move(self, entry_id: str, new_date: str) -> None:
        self.update_by_id(ObjectId(entry_id), {"date": new_date})

    def count_for_week(self, telegram_user_id: int, dates: list[str]) -> int:
        return self._collection.count_documents({
            "telegram_user_id": telegram_user_id,
            "date": {"$in": dates},
        })

    def get_recent(self, telegram_user_id: int, limit: int = 7) -> list[WorkoutLog]:
        docs = (
            self._collection
            .find({"telegram_user_id": telegram_user_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [self._to_model(doc) for doc in docs]
