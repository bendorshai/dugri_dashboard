"""
food_repository.py — גישה לקולקציית food_entries במונגו.

מחליף את כל הגישה ל-Google Sheets. כל רשומת אוכל מזוהה לפי ObjectId.

תלוי ב: repositories/base, models/food.
נצרך על ידי: services/eating_day_service, handlers.
"""

from __future__ import annotations

from bson import ObjectId

from models.food import FoodEntry
from repositories.base import BaseRepository


class FoodRepository(BaseRepository[FoodEntry]):
    def __init__(self, collection):
        super().__init__(collection, FoodEntry)

    def add(self, entry: FoodEntry) -> FoodEntry:
        """Insert a new food entry. Returns the entry with its generated _id."""
        return self.insert(entry)

    def get(self, entry_id: str) -> FoodEntry | None:
        return self.get_by_id(ObjectId(entry_id))

    def update(self, entry_id: str, fields: dict) -> None:
        self.update_by_id(ObjectId(entry_id), fields)

    def delete(self, entry_id: str) -> None:
        self.delete_by_id(ObjectId(entry_id))

    def get_by_user_and_dates(
        self, telegram_user_id: int, dates: list[str],
    ) -> list[FoodEntry]:
        return self.find({
            "telegram_user_id": telegram_user_id,
            "date": {"$in": dates},
        })

    def get_all_for_user(self, telegram_user_id: int) -> list[FoodEntry]:
        return self.find({"telegram_user_id": telegram_user_id})
