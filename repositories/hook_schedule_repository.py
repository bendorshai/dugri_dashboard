"""
hook_schedule_repository - Stores randomized fire times for hooks.

A single MongoDB document holds random send times for all hooks. All users
share the same times - this makes Dugri feel like a person who has a routine,
not a bot that fires at exact intervals.

Daily hooks (sleep) regenerate once per day. Weekly hooks (workouts,
self_care, weekly_summary) regenerate once per week.

Depends on: nothing (standalone).
Used by: scheduler.py (poller reads random times each tick).
"""

from __future__ import annotations

import random


class HookScheduleStore:
    """Manages a single MongoDB document with random fire times per hook."""

    DOC_ID = "hook_schedule"

    def __init__(self, collection):
        self._collection = collection

    def get_or_generate(
        self, hook_name: str, window: tuple[int, int], schedule_type: str, now,
    ) -> tuple[int, int]:
        """Return (hour, minute) for this hook. Generate if missing/expired."""
        doc = self._collection.find_one({"_id": self.DOC_ID})
        entry = doc.get(hook_name) if doc else None

        if entry and self._is_current(entry, schedule_type, now):
            return entry["hour"], entry["minute"]

        hour, minute = self._generate_random_time(window)
        period_key = self._period_key(schedule_type, now)
        self._collection.update_one(
            {"_id": self.DOC_ID},
            {"$set": {hook_name: {"hour": hour, "minute": minute, **period_key}}},
            upsert=True,
        )
        return hour, minute

    def _is_current(self, entry: dict, schedule_type: str, now) -> bool:
        """Check if the cached entry is still valid for the current period."""
        if schedule_type == "daily":
            return entry.get("date") == now.strftime("%Y-%m-%d")
        # weekly
        return entry.get("week") == now.strftime("%G-W%V")

    def _period_key(self, schedule_type: str, now) -> dict:
        """Return the period identifier to store alongside the random time."""
        if schedule_type == "daily":
            return {"date": now.strftime("%Y-%m-%d")}
        return {"week": now.strftime("%G-W%V")}

    @staticmethod
    def _generate_random_time(window: tuple[int, int]) -> tuple[int, int]:
        """Pick a random hour in [start, end) and random minute in [0, 59]."""
        start_hour, end_hour = window
        hour = random.randint(start_hour, end_hour - 1)
        minute = random.randint(0, 59)
        return hour, minute
