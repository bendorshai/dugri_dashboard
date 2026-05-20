"""
self_care.py — מודל תיעוד "משהו לעצמי".

תלוי ב: pydantic.
נצרך על ידי: repositories/self_care_repository, services/habit_service.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SelfCareLog(BaseModel):
    id: str | None = None
    telegram_user_id: int
    week_id: str  # e.g., "2026-W21"
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo_dict(self) -> dict:
        d = self.model_dump(mode="json")
        entry_id = d.pop("id")
        if entry_id is not None:
            from bson import ObjectId
            d["_id"] = ObjectId(entry_id)
        return d

    @classmethod
    def from_mongo_dict(cls, doc: dict) -> SelfCareLog:
        doc = dict(doc)
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return cls.model_validate(doc)
