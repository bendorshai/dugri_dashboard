"""
sleep.py — מודל תיעוד שעת שינה.

תלוי ב: pydantic.
נצרך על ידי: repositories/sleep_repository, services/habit_service.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


class SleepLog(BaseModel):
    id: str | None = None
    telegram_user_id: int
    date: str
    sleep_time: str
    user_message_id: int | None = None
    bot_message_id: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not _DATE_RE.match(v):
            raise ValueError(f"Date must be DD/MM/YYYY, got '{v}'")
        return v

    @field_validator("sleep_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError(f"sleep_time must be H:MM or HH:MM, got '{v}'")
        parts = v.split(":")
        return f"{int(parts[0]):02d}:{parts[1]}"

    def to_mongo_dict(self) -> dict:
        d = self.model_dump(mode="json")
        entry_id = d.pop("id")
        if entry_id is not None:
            from bson import ObjectId
            d["_id"] = ObjectId(entry_id)
        return d

    @classmethod
    def from_mongo_dict(cls, doc: dict) -> SleepLog:
        doc = dict(doc)
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return cls.model_validate(doc)
