"""
food.py — מודל רשומת אוכל של דוגרי.

כל ארוחה שהמשתמש מתעד הופכת ל-FoodEntry אחד שנשמר ב-food_entries במונגו.
מחליף את הרשומות ב-Google Sheets.

תלוי ב: pydantic בלבד.
נצרך על ידי: repositories/food_repository, services/eating_day_service, handlers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class FoodEntry(BaseModel):
    id: str | None = None
    telegram_user_id: int
    date: str
    time: str
    description: str
    calories: int
    protein: int
    within_window: bool = True
    correction_history: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if not _DATE_RE.match(v):
            raise ValueError(f"Date must be DD/MM/YYYY, got '{v}'")
        return v

    @field_validator("time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError(f"Time must be HH:MM, got '{v}'")
        return v

    def to_mongo_dict(self) -> dict:
        """Convert to MongoDB document. Drops id if None, maps id to _id."""
        d = self.model_dump(mode="json")
        entry_id = d.pop("id")
        if entry_id is not None:
            from bson import ObjectId
            d["_id"] = ObjectId(entry_id)
        return d

    @classmethod
    def from_mongo_dict(cls, doc: dict) -> FoodEntry:
        """Create from MongoDB document. Maps _id to id as hex string."""
        doc = dict(doc)
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return cls.model_validate(doc)
