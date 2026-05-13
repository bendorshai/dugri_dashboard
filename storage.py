from __future__ import annotations

import logging
from datetime import datetime, timezone

from pymongo import MongoClient

logger = logging.getLogger(__name__)


class DashboardStorage:
    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self._users = self._db["dashboard_users"]
        logger.info("Dashboard MongoDB connected: %s / %s", uri.split("@")[-1], db_name)

    def get_user(self, email: str) -> dict | None:
        return self._users.find_one({"_id": email})

    def create_user(self, email: str, name: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "_id": email,
            "name": name,
            "birth_year": None,
            "height_cm": None,
            "weight_kg": None,
            "goals": {},
            "bot_key": "",
            "onboarding_complete": False,
            "terms_accepted": False,
            "created_at": now,
            "updated_at": now,
        }
        self._users.insert_one(doc)
        return doc

    def update_user_profile(self, email: str, data: dict) -> None:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._users.update_one({"_id": email}, {"$set": data})

    def update_user_goals(self, email: str, goals: dict) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "goals": goals,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    def complete_onboarding(self, email: str) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "onboarding_complete": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
