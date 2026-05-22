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


def _parse_dt(val) -> datetime | None:
    """Parse a datetime that may be BSON datetime or ISO string.

    Always returns a UTC-aware datetime so subtraction never fails
    on naive-vs-aware mismatch.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _created_at_gte(cutoff: datetime) -> dict:
    """Build a $match filter for created_at that handles both BSON datetime and ISO string."""
    naive = cutoff.replace(tzinfo=None) if cutoff.tzinfo else cutoff
    iso = cutoff.isoformat()
    return {"$or": [
        {"created_at": {"$gte": naive, "$type": "date"}},
        {"created_at": {"$gte": iso, "$type": "string"}},
    ]}


def _created_at_range(start: datetime, end: datetime) -> dict:
    """Build a $match filter for created_at range, handling both BSON datetime and ISO string."""
    naive_start = start.replace(tzinfo=None) if start.tzinfo else start
    naive_end = end.replace(tzinfo=None) if end.tzinfo else end
    iso_start = start.isoformat()
    iso_end = end.isoformat()
    return {"$or": [
        {"created_at": {"$gte": naive_start, "$lt": naive_end, "$type": "date"}},
        {"created_at": {"$gte": iso_start, "$lt": iso_end, "$type": "string"}},
    ]}


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
        def _fetch():
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            pipeline = [
                {"$match": _created_at_gte(cutoff)},
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

                entry_time = _parse_dt(first_entry["created_at"])
                if not entry_time:
                    continue

                signup_time = _parse_dt(user.get("created_at"))
                if signup_time:
                    if (entry_time - signup_time).total_seconds() <= 86400:
                        activated_from_signup += 1

                link_time = _parse_dt(user.get("trial_started_at"))
                if link_time:
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

            entries = list(self._food.find(
                _created_at_gte(cutoff),
                {"telegram_user_id": 1, "created_at": 1},
            ))

            from collections import defaultdict
            day_users: dict[str, set] = defaultdict(set)
            for e in entries:
                ct = _parse_dt(e.get("created_at"))
                if not ct:
                    continue
                date_str = ct.strftime("%Y-%m-%d")
                day_users[date_str].add(e["telegram_user_id"])

            # Fill 30-day range with zeros
            days = {}
            for i in range(30):
                d = (datetime.now(timezone.utc) - timedelta(days=29 - i)).strftime("%Y-%m-%d")
                days[d] = len(day_users.get(d, set()))
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
            # food_entries have a "time" field as "HH:MM" string
            # Use simple aggregation on string field
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
                signup = _parse_dt(user.get("created_at"))
                if not signup:
                    continue

                tid = user["telegram_user_id"]
                entries = list(self._food.find(
                    {"telegram_user_id": tid},
                    {"created_at": 1},
                ))

                entry_days = set()
                for e in entries:
                    ct = _parse_dt(e.get("created_at"))
                    if not ct:
                        continue
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

    def _get_7day_activity(self) -> dict[int, set[str]]:
        """Return {telegram_user_id: set of active date strings} for last 7 days."""
        def _fetch():
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            entries = list(self._food.find(
                _created_at_gte(cutoff),
                {"telegram_user_id": 1, "created_at": 1},
            ))
            from collections import defaultdict
            tid_days: dict[int, set[str]] = defaultdict(set)
            for e in entries:
                ct = _parse_dt(e.get("created_at"))
                if ct:
                    tid_days[e["telegram_user_id"]].add(ct.strftime("%Y-%m-%d"))
            return dict(tid_days)
        return _cached("7day_activity", _fetch)

    def get_super_active_users(self) -> list[dict]:
        def _fetch():
            cutoff = datetime.now(timezone.utc) - timedelta(days=3)

            entries = list(self._food.find(
                _created_at_gte(cutoff),
                {"telegram_user_id": 1, "created_at": 1},
            ))

            from collections import Counter
            tid_counts: Counter = Counter()
            tid_last: dict = {}
            for e in entries:
                tid = e["telegram_user_id"]
                tid_counts[tid] += 1
                ct = _parse_dt(e.get("created_at"))
                if ct and (tid not in tid_last or ct > tid_last[tid]):
                    tid_last[tid] = ct

            active_tids = [
                {"_id": tid, "last_active": tid_last.get(tid)}
                for tid, count in tid_counts.most_common()
                if count >= 5
            ]
            return self._enrich_leads(active_tids, "super_active")

        return _cached("leads_super_active", _fetch)

    def get_consistently_active_users(self) -> list[dict]:
        def _fetch():
            activity = self._get_7day_activity()
            super_active_tids = {
                lead["telegram_user_id"]
                for lead in self.get_super_active_users()
            }

            consistent_tids = []
            for tid, days in activity.items():
                if len(days) == 7 and tid not in super_active_tids:
                    last_day = max(days)
                    consistent_tids.append({"_id": tid, "last_active": last_day, "active_days": 7})

            return self._enrich_leads(consistent_tids, "consistently_active")

        return _cached("leads_consistent", _fetch)

    def get_inconsistently_active_users(self) -> list[dict]:
        def _fetch():
            activity = self._get_7day_activity()
            super_active_tids = {
                lead["telegram_user_id"]
                for lead in self.get_super_active_users()
            }
            consistent_tids = {
                lead["telegram_user_id"]
                for lead in self.get_consistently_active_users()
            }
            exclude = super_active_tids | consistent_tids

            inconsistent_tids = []
            for tid, days in activity.items():
                if 1 <= len(days) < 7 and tid not in exclude:
                    last_day = max(days)
                    inconsistent_tids.append({
                        "_id": tid,
                        "last_active": last_day,
                        "active_days": len(days),
                    })

            # Sort by active days descending
            inconsistent_tids.sort(key=lambda r: r["active_days"], reverse=True)
            return self._enrich_leads(inconsistent_tids, "inconsistently_active")

        return _cached("leads_inconsistent", _fetch)

    def get_stopped_users(self) -> list[dict]:
        def _fetch():
            cutoff_recent = datetime.now(timezone.utc) - timedelta(days=5)
            cutoff_old = datetime.now(timezone.utc) - timedelta(days=30)

            old_entries = list(self._food.find(
                _created_at_range(cutoff_old, cutoff_recent),
                {"telegram_user_id": 1, "created_at": 1},
            ))

            from collections import defaultdict
            tid_days: dict[int, set] = defaultdict(set)
            for e in old_entries:
                ct = _parse_dt(e.get("created_at"))
                if ct:
                    tid_days[e["telegram_user_id"]].add(ct.strftime("%Y-%m-%d"))

            formerly_active = {tid for tid, days in tid_days.items() if len(days) >= 7}
            if not formerly_active:
                return []

            gte_filter = _created_at_gte(cutoff_recent)
            gte_filter["telegram_user_id"] = {"$in": list(formerly_active)}
            recent_entries = list(self._food.find(
                gte_filter,
                {"telegram_user_id": 1},
            ))
            still_active = {e["telegram_user_id"] for e in recent_entries}

            stopped_tids = formerly_active - still_active
            if not stopped_tids:
                return []

            result = []
            for tid in stopped_tids:
                last = self._food.find_one(
                    {"telegram_user_id": tid},
                    sort=[("created_at", -1)],
                )
                result.append({
                    "_id": tid,
                    "last_active": last["created_at"] if last else None,
                })
            return self._enrich_leads(result, "stopped")

        return _cached("leads_stopped", _fetch)

    def get_stuck_at_gate_users(self) -> list[dict]:
        def _fetch():
            unlinked = list(self._users.find(
                {"telegram_user_id": None},
                {"_id": 1, "name": 1, "created_at": 1},
            ))

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
            lead = {
                "email": user.get("_id"),
                "name": user.get("name"),
                "telegram_user_id": r["_id"],
                "category": category,
                "signup_date": user.get("created_at"),
                "last_active": r.get("last_active"),
            }
            if "active_days" in r:
                lead["active_days"] = r["active_days"]
            result.append(lead)
        return result
