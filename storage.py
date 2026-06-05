from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone

from pymongo import MongoClient

logger = logging.getLogger(__name__)

SIGNUP_TOKEN_LIFETIME_HOURS = 24


class DashboardStorage:
    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self._users = self._db["users"]
        logger.info("Dashboard MongoDB connected: %s / %s", uri.split("@")[-1], db_name)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_user(self, email: str) -> dict | None:
        return self._users.find_one({"_id": email})

    def create_user(
        self,
        email: str,
        name: str,
        photo_url: str | None = None,
        consents: dict | None = None,
    ) -> dict:
        now = self._now()
        doc = {
            "_id": email,
            "name": name,
            "photo_url": photo_url,
            "telegram_user_id": None,
            "signup_session_token": None,
            "signup_session_token_expires_at": None,
            "consents": consents or {},
            "trial_started_at": None,
            "subscription_status": "trial_pending",
            # Profile fields
            "birth_year": None,
            "height_cm": None,
            "weight_kg": None,
            "goals": {},
            # Bot fields — defaults until bot onboarding populates them
            "gender": None,
            "targets": {"calories": None, "protein": None, "sleep_time": None, "workouts_per_week": None},
            "eating_window": None,
            "timezone": "Asia/Jerusalem",
            "onboarding": {"name_collected": False, "habits": {}},
            "active_habits": [],
            "pending_state": None,
            "feedback_steering_prompt": None,
            "last_feedback_offered_at": None,
            # Toggle system (opt-in toggles dormant, weekly_summary active by default)
            "toggles": {
                "sleep": {"status": "dormant"},
                "eating_window": {"status": "dormant"},
                "workouts": {"status": "dormant"},
                "self_care": {"status": "dormant"},
                "nutrition": {"status": "dormant"},
                "weekly_summary": {"status": "active"},
            },
            "dashboard_intro_shown": False,
            "target_retry_done": False,
            "eating_window_retry_done": False,
            "created_at": now,
            "updated_at": now,
        }
        self._users.insert_one(doc)
        return doc

    def update_user_profile(self, email: str, data: dict) -> None:
        data["updated_at"] = self._now()
        self._users.update_one({"_id": email}, {"$set": data})

    def update_user_goals(self, email: str, goals: dict) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "goals": goals,
                "updated_at": self._now(),
            }},
        )

    def complete_onboarding(self, email: str) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "onboarding_complete": True,
                "updated_at": self._now(),
            }},
        )

    # -- Signup session token methods --

    def set_signup_session_token(
        self, email: str, token: str, expires_at: str,
    ) -> None:
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "signup_session_token": token,
                "signup_session_token_expires_at": expires_at,
                "updated_at": self._now(),
            }},
        )

    def regenerate_signup_session_token(self, email: str) -> str:
        token = secrets.token_urlsafe(24)
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=SIGNUP_TOKEN_LIFETIME_HOURS)
        ).isoformat()
        self.set_signup_session_token(email, token, expires_at)
        return token

    def get_user_by_session_token(self, token: str) -> dict | None:
        now = self._now()
        return self._users.find_one({
            "signup_session_token": token,
            "signup_session_token_expires_at": {"$gt": now},
        })

    # -- Toggle management --

    def update_user_toggles(self, email: str, toggles: dict) -> None:
        """Update toggle states from dashboard."""
        self._users.update_one(
            {"_id": email},
            {"$set": {
                "toggles": toggles,
                "updated_at": self._now(),
            }},
        )

    # -- Unified targets --

    def update_user_targets(self, email: str, calories: int | None, protein: int | None) -> dict:
        """Update calorie and protein targets. Returns the old targets dict."""
        user = self._users.find_one({"_id": email})
        old_targets = user.get("targets", {}) if user else {}

        self._users.update_one(
            {"_id": email},
            {"$set": {
                "targets.calories": calories,
                "targets.protein": protein,
                "updated_at": self._now(),
            }},
        )
        return old_targets

    # -- Activity history --

    def get_activity_history(
        self, email: str, start_date: date, end_date: date,
    ) -> dict:
        """Get all activity data (food, workouts, sleep, self-care) for a date range.

        Returns dict with keys: food, workouts, sleep, self_care, targets.
        """
        user = self._users.find_one({"_id": email})
        if not user or not user.get("telegram_user_id"):
            return {"food": [], "workouts": [], "sleep": [], "self_care": [], "targets": {}}

        tid = user["telegram_user_id"]
        targets = user.get("targets", {})

        # Generate DD/MM/YYYY date strings for the range
        date_strings = []
        current = start_date
        while current <= end_date:
            date_strings.append(current.strftime("%d/%m/%Y"))
            current += timedelta(days=1)

        # Generate ISO week IDs for self-care (YYYY-Www)
        week_ids = set()
        current = start_date
        while current <= end_date:
            iso_year, iso_week, _ = current.isocalendar()
            week_ids.add(f"{iso_year}-W{iso_week:02d}")
            current += timedelta(days=1)

        food = list(self._db["food_entries"].find(
            {"telegram_user_id": tid, "date": {"$in": date_strings}},
        ))
        workouts = list(self._db["workout_logs"].find(
            {"telegram_user_id": tid, "date": {"$in": date_strings}},
        ))
        sleep = list(self._db["sleep_logs"].find(
            {"telegram_user_id": tid, "date": {"$in": date_strings}},
        ))
        self_care = list(self._db["self_care_logs"].find(
            {"telegram_user_id": tid, "week_id": {"$in": list(week_ids)}},
        ))

        return {
            "food": food,
            "workouts": workouts,
            "sleep": sleep,
            "self_care": self_care,
            "targets": targets,
        }

    # -- Trend data --

    def get_trend_data(self, email: str, days: int = 30) -> dict:
        """Get daily trend data for multiple metrics.

        Args:
            days: Number of days to look back. 0 means all history.

        Returns {"days": [{"date", "calories", "protein", "workouts"}, ...], "targets": dict}
        sorted chronologically (oldest first).
        """
        empty = {"days": [], "targets": {}}
        user = self._users.find_one({"_id": email})
        if not user or not user.get("telegram_user_id"):
            return empty

        tid = user["telegram_user_id"]
        targets = user.get("targets", {})

        base_query = {"telegram_user_id": tid}

        if days > 0:
            # Fixed date range
            today = date.today()
            start = today - timedelta(days=days - 1)
            date_strings = []
            current = start
            while current <= today:
                date_strings.append(current.strftime("%d/%m/%Y"))
                current += timedelta(days=1)
            date_filter = {"date": {"$in": date_strings}}
        else:
            date_strings = None
            date_filter = {}

        food = list(self._db["food_entries"].find({**base_query, **date_filter}))
        workouts = list(self._db["workout_logs"].find({**base_query, **date_filter}))
        sleep = list(self._db["sleep_logs"].find({**base_query, **date_filter}))

        # Self-care uses week_id, not date - build week filter
        if days > 0:
            week_ids = set()
            current = start
            while current <= today:
                iso_year, iso_week, _ = current.isocalendar()
                week_ids.add(f"{iso_year}-W{iso_week:02d}")
                current += timedelta(days=1)
            sc_filter = {"telegram_user_id": tid, "week_id": {"$in": list(week_ids)}}
        else:
            sc_filter = {"telegram_user_id": tid}
        self_care = list(self._db["self_care_logs"].find(sc_filter))

        # Aggregate food by date
        cal_by_date: dict[str, int] = {}
        prot_by_date: dict[str, int] = {}
        for entry in food:
            d = entry["date"]
            cal_by_date[d] = cal_by_date.get(d, 0) + entry.get("calories", 0)
            prot_by_date[d] = prot_by_date.get(d, 0) + entry.get("protein", 0)

        # Count workouts by date
        wo_by_date: dict[str, int] = {}
        for entry in workouts:
            d = entry["date"]
            wo_by_date[d] = wo_by_date.get(d, 0) + 1

        # Sleep logged per date (1 if logged, 0 if not)
        sleep_by_date: dict[str, int] = {}
        for entry in sleep:
            sleep_by_date[entry["date"]] = 1

        # Self-care count per week_id
        sc_by_week: dict[str, int] = {}
        for entry in self_care:
            wid = entry.get("week_id", "")
            sc_by_week[wid] = sc_by_week.get(wid, 0) + 1

        if days > 0:
            all_dates = date_strings
        else:
            all_date_set = (
                set(cal_by_date) | set(prot_by_date)
                | set(wo_by_date) | set(sleep_by_date)
            )
            all_dates = sorted(all_date_set, key=lambda d: d.split("/")[::-1])

        def _week_id_for_date_str(ds: str) -> str:
            parts = ds.split("/")
            d = date(int(parts[2]), int(parts[1]), int(parts[0]))
            iso_year, iso_week, _ = d.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"

        result_days = []
        for ds in all_dates:
            wid = _week_id_for_date_str(ds)
            result_days.append({
                "date": ds,
                "calories": cal_by_date.get(ds, 0),
                "protein": prot_by_date.get(ds, 0),
                "workouts": wo_by_date.get(ds, 0),
                "sleep": sleep_by_date.get(ds, 0),
                "self_care": sc_by_week.get(wid, 0),
            })

        return {"days": result_days, "targets": targets}

    # -- Weekly summaries --

    def get_weekly_summaries(self, email: str, limit: int = 20) -> list[dict]:
        """Get recent weekly summaries for a user. Joins via telegram_user_id."""
        user = self._users.find_one({"_id": email})
        if not user or not user.get("telegram_user_id"):
            return []

        feedback_col = self._db["weekly_feedback"]
        cursor = feedback_col.find(
            {"telegram_user_id": user["telegram_user_id"]},
        ).sort("created_at", -1).limit(limit)
        return list(cursor)
