from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

logger = logging.getLogger(__name__)

CACHE_TTL = 60  # seconds

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, fetch_fn):
    now = time.time()
    entry = _cache.get(key)
    if entry and now - entry[0] < CACHE_TTL:
        return entry[1]
    data = fetch_fn()
    _cache[key] = (now, data)
    return data


class AdminStorage:
    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self._users = self._db["users"]
        self._food = self._db["food_entries"]
        self._sleep = self._db["sleep_logs"]
        self._workouts = self._db["workout_logs"]
        self._self_care = self._db["self_care_logs"]

    # -- KPI Cards --

    def get_total_users(self) -> int:
        return _cached("total_users", lambda: self._users.count_documents(
            {"telegram_user_id": {"$ne": None}},
        ))

    def get_total_signups(self) -> int:
        return _cached("total_signups", lambda: self._users.count_documents({}))

    def get_active_this_week(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        def _fetch():
            pipeline = [
                {"$match": {"created_at": {"$gte": cutoff}}},
                {"$group": {"_id": "$telegram_user_id"}},
                {"$count": "n"},
            ]
            result = list(self._food.aggregate(pipeline))
            return result[0]["n"] if result else 0

        return _cached("active_week", _fetch)

    def get_signup_funnel(self) -> dict:
        def _fetch():
            total = self._users.count_documents({})
            linked = self._users.count_documents({"telegram_user_id": {"$ne": None}})

            # Get all linked users with their signup and trial timestamps
            linked_users = list(self._users.find(
                {"telegram_user_id": {"$ne": None}},
                {"telegram_user_id": 1, "created_at": 1, "trial_started_at": 1},
            ))

            activated_from_signup = 0
            activated_from_link = 0

            for user in linked_users:
                tid = user["telegram_user_id"]
                first_entry = self._food.find_one(
                    {"telegram_user_id": tid},
                    sort=[("created_at", 1)],
                )
                if not first_entry or not first_entry.get("created_at"):
                    continue

                entry_time = first_entry["created_at"]
                if isinstance(entry_time, str):
                    entry_time = datetime.fromisoformat(entry_time)

                # Activation from dashboard signup
                signup_time = user.get("created_at")
                if signup_time:
                    if isinstance(signup_time, str):
                        signup_time = datetime.fromisoformat(signup_time)
                    if (entry_time - signup_time).total_seconds() <= 86400:
                        activated_from_signup += 1

                # Activation from bot link
                link_time = user.get("trial_started_at")
                if link_time:
                    if isinstance(link_time, str):
                        link_time = datetime.fromisoformat(link_time)
                    if (entry_time - link_time).total_seconds() <= 86400:
                        activated_from_link += 1

            return {
                "total_signups": total,
                "linked_to_bot": linked,
                "activated_24h_from_signup": activated_from_signup,
                "activated_24h_from_link": activated_from_link,
            }

        return _cached("signup_funnel", _fetch)

    # -- Charts --

    def get_dau_30_days(self) -> list[dict]:
        def _fetch():
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            pipeline = [
                {"$match": {"created_at": {"$gte": cutoff}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "users": {"$addToSet": "$telegram_user_id"},
                }},
                {"$project": {"date": "$_id", "count": {"$size": "$users"}, "_id": 0}},
                {"$sort": {"date": 1}},
            ]
            result = list(self._food.aggregate(pipeline))

            # Fill gaps with zeros
            days = {}
            for i in range(30):
                d = (datetime.now(timezone.utc) - timedelta(days=29 - i)).strftime("%Y-%m-%d")
                days[d] = 0
            for r in result:
                if r["date"] in days:
                    days[r["date"]] = r["count"]
            return [{"date": d, "count": c} for d, c in days.items()]

        return _cached("dau_30", _fetch)

    def get_habit_adoption(self) -> dict[str, int]:
        habits = ["sleep", "eating_window", "workouts", "self_care", "weekly_summary"]

        def _fetch():
            result = {}
            for habit in habits:
                count = self._users.count_documents({
                    f"toggles.{habit}.status": "active",
                    "telegram_user_id": {"$ne": None},
                })
                result[habit] = count
            return result

        return _cached("habit_adoption", _fetch)

    def get_activity_hours(self) -> list[int]:
        def _fetch():
            # food_entries have a "time" field as "HH:MM"
            pipeline = [
                {"$match": {"time": {"$exists": True, "$ne": None}}},
                {"$project": {
                    "hour": {"$toInt": {"$arrayElemAt": [{"$split": ["$time", ":"]}, 0]}},
                }},
                {"$group": {"_id": "$hour", "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ]
            result = list(self._food.aggregate(pipeline))
            hours = [0] * 24
            for r in result:
                h = r["_id"]
                if 0 <= h < 24:
                    hours[h] = r["count"]
            return hours

        return _cached("activity_hours", _fetch)

    def get_churn_curve(self) -> list[dict]:
        def _fetch():
            # For each user, determine their signup date and which days (1-14) they logged food
            users = list(self._users.find(
                {"telegram_user_id": {"$ne": None}},
                {"telegram_user_id": 1, "created_at": 1},
            ))

            if not users:
                return [{"day": d, "pct": 0} for d in range(1, 15)]

            day_counts = {d: 0 for d in range(1, 15)}
            total_eligible = {d: 0 for d in range(1, 15)}
            now = datetime.now(timezone.utc)

            for user in users:
                signup = user.get("created_at")
                if not signup:
                    continue
                if isinstance(signup, str):
                    signup = datetime.fromisoformat(signup)

                tid = user["telegram_user_id"]
                entries = list(self._food.find(
                    {"telegram_user_id": tid},
                    {"created_at": 1},
                ))

                entry_days = set()
                for e in entries:
                    ct = e.get("created_at")
                    if not ct:
                        continue
                    if isinstance(ct, str):
                        ct = datetime.fromisoformat(ct)
                    day_offset = (ct - signup).days + 1
                    if 1 <= day_offset <= 14:
                        entry_days.add(day_offset)

                for d in range(1, 15):
                    days_since_signup = (now - signup).days + 1
                    if days_since_signup >= d:
                        total_eligible[d] += 1
                        if d in entry_days:
                            day_counts[d] += 1

            result = []
            for d in range(1, 15):
                pct = round(day_counts[d] / total_eligible[d] * 100, 1) if total_eligible[d] else 0
                result.append({"day": d, "pct": pct})
            return result

        return _cached("churn_curve", _fetch)

    # -- Hot Leads --

    def get_super_active_users(self) -> list[dict]:
        def _fetch():
            cutoff = datetime.now(timezone.utc) - timedelta(days=3)
            pipeline = [
                {"$match": {"created_at": {"$gte": cutoff}}},
                {"$group": {
                    "_id": "$telegram_user_id",
                    "entry_count": {"$sum": 1},
                    "last_active": {"$max": "$created_at"},
                }},
                {"$match": {"entry_count": {"$gte": 5}}},
                {"$sort": {"entry_count": -1}},
            ]
            active_tids = list(self._food.aggregate(pipeline))
            return self._enrich_leads(active_tids, "super_active")

        return _cached("leads_super_active", _fetch)

    def get_churning_users(self) -> list[dict]:
        def _fetch():
            cutoff_recent = datetime.now(timezone.utc) - timedelta(days=5)
            cutoff_old = datetime.now(timezone.utc) - timedelta(days=30)

            # Users who had entries before 5 days ago (active period)
            pipeline_active = [
                {"$match": {"created_at": {"$gte": cutoff_old, "$lt": cutoff_recent}}},
                {"$group": {
                    "_id": "$telegram_user_id",
                    "active_days": {"$addToSet": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"},
                    }},
                }},
                {"$match": {"$expr": {"$gte": [{"$size": "$active_days"}, 7]}}},
            ]
            formerly_active = {
                r["_id"] for r in self._food.aggregate(pipeline_active)
            }

            if not formerly_active:
                return []

            # Exclude those still active recently
            pipeline_recent = [
                {"$match": {
                    "created_at": {"$gte": cutoff_recent},
                    "telegram_user_id": {"$in": list(formerly_active)},
                }},
                {"$group": {"_id": "$telegram_user_id"}},
            ]
            still_active = {
                r["_id"] for r in self._food.aggregate(pipeline_recent)
            }

            churned_tids = formerly_active - still_active
            if not churned_tids:
                return []

            # Get last activity for churned users
            result = []
            for tid in churned_tids:
                last = self._food.find_one(
                    {"telegram_user_id": tid},
                    sort=[("created_at", -1)],
                )
                result.append({
                    "_id": tid,
                    "last_active": last["created_at"] if last else None,
                })
            return self._enrich_leads(result, "churning")

        return _cached("leads_churning", _fetch)

    def get_stuck_at_gate_users(self) -> list[dict]:
        def _fetch():
            # Users with no telegram_user_id (never linked)
            unlinked = list(self._users.find(
                {"telegram_user_id": None},
                {"_id": 1, "name": 1, "created_at": 1},
            ))

            # Users with telegram_user_id but zero food entries
            linked_users = list(self._users.find(
                {"telegram_user_id": {"$ne": None}},
                {"_id": 1, "name": 1, "telegram_user_id": 1, "created_at": 1},
            ))

            no_entries = []
            for user in linked_users:
                count = self._food.count_documents(
                    {"telegram_user_id": user["telegram_user_id"]},
                )
                if count == 0:
                    no_entries.append(user)

            result = []
            for u in unlinked:
                result.append({
                    "email": u["_id"],
                    "name": u.get("name"),
                    "telegram_user_id": None,
                    "category": "stuck_at_gate",
                    "sub_reason": "never_linked",
                    "signup_date": u.get("created_at"),
                    "last_active": None,
                })
            for u in no_entries:
                result.append({
                    "email": u["_id"],
                    "name": u.get("name"),
                    "telegram_user_id": u.get("telegram_user_id"),
                    "category": "stuck_at_gate",
                    "sub_reason": "linked_no_entries",
                    "signup_date": u.get("created_at"),
                    "last_active": None,
                })
            return result

        return _cached("leads_stuck", _fetch)

    def _enrich_leads(self, tid_records: list[dict], category: str) -> list[dict]:
        """Join telegram_user_id aggregation results with user info."""
        if not tid_records:
            return []

        tids = [r["_id"] for r in tid_records]
        users_by_tid = {}
        for user in self._users.find(
            {"telegram_user_id": {"$in": tids}},
            {"_id": 1, "name": 1, "telegram_user_id": 1, "created_at": 1},
        ):
            users_by_tid[user["telegram_user_id"]] = user

        result = []
        for r in tid_records:
            user = users_by_tid.get(r["_id"], {})
            result.append({
                "email": user.get("_id"),
                "name": user.get("name"),
                "telegram_user_id": r["_id"],
                "category": category,
                "signup_date": user.get("created_at"),
                "last_active": r.get("last_active"),
            })
        return result
