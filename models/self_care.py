"""
self_care.py - מודל תיעוד "משהו לעצמי".

תלוי ב: pydantic.
נצרך על ידי: repositories/self_care_repository, services/habit_service.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator


_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def compute_week_id(date_str: str) -> str:
    """Convert DD/MM/YYYY to ISO week format YYYY-WXX."""
    dt = datetime.strptime(date_str, "%d/%m/%Y")
    return dt.strftime("%G-W%V")


class SelfCareLog(BaseModel):
    id: str | None = None
    telegram_user_id: int
    date: str | None = None  # DD/MM/YYYY
    week_id: str | None = None  # e.g., "2026-W21" - auto-computed from date
    description: str
    user_message_id: int | None = None
    bot_message_id: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str | None) -> str | None:
        if v is not None and not _DATE_RE.match(v):
            raise ValueError(f"Date must be DD/MM/YYYY, got '{v}'")
        return v

    @model_validator(mode="after")
    def auto_compute_week_id(self) -> SelfCareLog:
        if self.date and not self.week_id:
            self.week_id = compute_week_id(self.date)
        return self

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
