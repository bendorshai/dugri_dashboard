from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
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

    def log_meta_event(self, **fields) -> None:
        """Append one fired Meta conversion event (with its send outcome) to the
        shared meta_events_log collection. Best-effort; source='dashboard'."""
        doc = {
            "telegram_user_id": fields.get("telegram_user_id"),
            "user_email": fields.get("user_email"),
            "event_key": fields.get("event_key", ""),
            "event_name": fields.get("event_name", ""),
            "action_source": fields.get("action_source"),
            "source": "dashboard",
            "event_time": fields.get("event_time"),
            "custom_data": fields.get("custom_data"),
            "sent_ok": fields.get("sent_ok"),
            "http_status": fields.get("http_status"),
            "events_received": fields.get("events_received"),
            "fbtrace_id": fields.get("fbtrace_id"),
            "error": fields.get("error"),
            # Store a real datetime (BSON Date) - NOT self._now()'s ISO string - so
            # this matches the bot's utc_now() write and admin sort-by-timestamp
            # orders bot + dashboard rows consistently (Mongo sorts mixed types by
            # type-bracket, so string vs Date would split them into two groups).
            "timestamp": datetime.now(timezone.utc),
        }
        try:
            self._db["meta_events_log"].insert_one(doc)
        except Exception:
            logger.warning("Failed to log meta event", exc_info=True)

    def log_webhook(self, **fields) -> None:
        """Append one raw inbound payment-webhook (GI IPN) call to webhook_logs,
        for diagnosis. Best-effort; never raises. This is the ground-truth record
        of exactly what Green Invoice sends, so a payload-format mismatch can be
        seen and fixed instead of failing invisibly."""
        doc = {
            "args": fields.get("args"),
            "json": fields.get("json"),
            "form": fields.get("form"),
            "headers": fields.get("headers"),
            "outcome": fields.get("outcome"),
            "matched_email": fields.get("matched_email"),
            "document_id": fields.get("document_id"),
            "verified": fields.get("verified"),
            "timestamp": datetime.now(timezone.utc),
        }
        try:
            self._db["webhook_logs"].insert_one(doc)
        except Exception:
            logger.warning("Failed to log webhook", exc_info=True)

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
            # telegram_user_id is intentionally OMITTED (not set to null): the
            # users collection has a sparse UNIQUE index on telegram_user_id, and
            # a *present* null is indexed - so a second unlinked signup would
            # collide on null (E11000). Leaving the field absent lets the sparse
            # index skip unlinked users; linking sets a real id later.
            "signup_session_token": None,
            "signup_session_token_expires_at": None,
            "consents": consents or {},
            "meta": {"signup_event_id": secrets.token_urlsafe(16)},
            "trial_started_at": None,
            "subscription_status": "trial_pending",
            # Profile fields
            "birth_year": None,
            "height_cm": None,
            "weight_kg": None,
            # Bot fields - defaults until bot onboarding populates them
            "gender": None,
            "targets": {"calories": None, "protein": None, "sleep_time": None, "workouts_per_week": None},
            "eating_window": None,
            "timezone": "Asia/Jerusalem",
            "timezone_source": "default",
            "timezone_updated_at": None,
            "onboarding": {"name_collected": False, "habits": {}},
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

    def set_timezone(self, email: str, timezone: str, source: str) -> None:
        """Persist the user's timezone + its provenance. Caller MUST validate
        the timezone string first (supported_timezones.is_valid_timezone).

        source is one of: browser_detected | user_confirmed | user_manual.
        """
        now = self._now()
        self._users.update_one({"_id": email}, {"$set": {
            "timezone": timezone,
            "timezone_source": source,
            "timezone_updated_at": now,
            "updated_at": now,
        }})

    # -- Meta (Facebook) conversion identifiers --

    def set_meta_identifiers(self, email: str, *, fbp: str | None = None,
                             fbc: str | None = None, fbclid: str | None = None,
                             landing_url: str | None = None, client_ip: str | None = None,
                             client_user_agent: str | None = None) -> None:
        """Persist Meta attribution identifiers under the user's meta.* sub-doc.
        Skips empty values; never overwrites with None."""
        update = {f"meta.{k}": v for k, v in {
            "fbp": fbp, "fbc": fbc, "fbclid": fbclid, "landing_url": landing_url,
            "client_ip": client_ip, "client_user_agent": client_user_agent,
        }.items() if v}
        if not update:
            return
        update["updated_at"] = self._now()
        self._users.update_one({"_id": email}, {"$set": update})

    def get_or_create_signup_event_id(self, email: str) -> str:
        """Stable per-user event id shared by the welcome-CTA pixel + any server Lead."""
        user = self._users.find_one({"_id": email}, {"meta": 1})
        existing = (user or {}).get("meta", {}).get("signup_event_id")
        if existing:
            return existing
        new_id = secrets.token_urlsafe(16)
        self._users.update_one({"_id": email},
                               {"$set": {"meta.signup_event_id": new_id, "updated_at": self._now()}})
        return new_id

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

    # -- Activity record helpers --

    def _get_telegram_user_id(self, email: str) -> int | None:
        user = self._users.find_one({"_id": email}, {"telegram_user_id": 1})
        return user.get("telegram_user_id") if user else None

    # -- Activity CRUD --

    def delete_food_entry(self, email: str, entry_id: str) -> bool:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return False
        result = self._db["food_entries"].delete_one(
            {"_id": ObjectId(entry_id), "telegram_user_id": tid},
        )
        return result.deleted_count > 0

    def delete_workout_log(self, email: str, entry_id: str) -> bool:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return False
        result = self._db["workout_logs"].delete_one(
            {"_id": ObjectId(entry_id), "telegram_user_id": tid},
        )
        return result.deleted_count > 0

    def delete_sleep_log(self, email: str, entry_id: str) -> bool:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return False
        result = self._db["sleep_logs"].delete_one(
            {"_id": ObjectId(entry_id), "telegram_user_id": tid},
        )
        return result.deleted_count > 0

    def delete_self_care_log(self, email: str, entry_id: str) -> bool:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return False
        result = self._db["self_care_logs"].delete_one(
            {"_id": ObjectId(entry_id), "telegram_user_id": tid},
        )
        return result.deleted_count > 0

    def update_food_entry(self, email: str, entry_id: str, data: dict) -> bool:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return False
        allowed = {k: v for k, v in data.items() if k in ("description", "calories", "protein")}
        if not allowed:
            return False
        result = self._db["food_entries"].update_one(
            {"_id": ObjectId(entry_id), "telegram_user_id": tid},
            {"$set": allowed},
        )
        return result.modified_count > 0

    def update_workout_log(self, email: str, entry_id: str, data: dict) -> bool:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return False
        allowed = {k: v for k, v in data.items() if k in ("note",)}
        if not allowed:
            return False
        result = self._db["workout_logs"].update_one(
            {"_id": ObjectId(entry_id), "telegram_user_id": tid},
            {"$set": allowed},
        )
        return result.modified_count > 0

    def update_self_care_log(self, email: str, entry_id: str, data: dict) -> bool:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return False
        allowed = {k: v for k, v in data.items() if k in ("description",)}
        if not allowed:
            return False
        result = self._db["self_care_logs"].update_one(
            {"_id": ObjectId(entry_id), "telegram_user_id": tid},
            {"$set": allowed},
        )
        return result.modified_count > 0

    def create_workout_log(self, email: str, date_str: str, note: str = "") -> str | None:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return None
        result = self._db["workout_logs"].insert_one({
            "telegram_user_id": tid,
            "date": date_str,
            "note": note,
            "created_at": datetime.now(timezone.utc),
        })
        return str(result.inserted_id)

    def create_sleep_log(self, email: str, date_str: str, sleep_time: str) -> str | None:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return None
        result = self._db["sleep_logs"].insert_one({
            "telegram_user_id": tid,
            "date": date_str,
            "sleep_time": sleep_time,
            "created_at": datetime.now(timezone.utc),
        })
        return str(result.inserted_id)

    def create_food_entry(
        self, email: str, date_str: str, time_str: str,
        description: str, calories: int, protein: int,
    ) -> str | None:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return None
        result = self._db["food_entries"].insert_one({
            "telegram_user_id": tid,
            "date": date_str,
            "time": time_str,
            "description": description,
            "calories": calories,
            "protein": protein,
            "within_window": True,
            "created_at": datetime.now(timezone.utc),
        })
        return str(result.inserted_id)

    def create_self_care_log(self, email: str, week_id: str, description: str) -> str | None:
        tid = self._get_telegram_user_id(email)
        if not tid:
            return None
        result = self._db["self_care_logs"].insert_one({
            "telegram_user_id": tid,
            "week_id": week_id,
            "description": description,
            "created_at": datetime.now(timezone.utc),
        })
        return str(result.inserted_id)

    # -- Activity history --

    def get_activity_history(
        self, email: str, start_date: date, end_date: date,
    ) -> dict:
        """Get all activity data (food, workouts, sleep, self-care) for a date range.

        Returns dict with keys: food, workouts, sleep, self_care, targets.
        """
        user = self._users.find_one({"_id": email})
        if not user or not user.get("telegram_user_id"):
            return {"food": [], "workouts": [], "sleep": [], "self_care": [], "targets": {}, "eating_window": None}

        tid = user["telegram_user_id"]
        targets = user.get("targets", {})
        eating_window = user.get("eating_window")

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
            "eating_window": eating_window,
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

    # -- Simulator (admin testing) --

    def update_user_raw(self, email: str, fields: dict) -> bool:
        """Set arbitrary fields on a user document. Admin-only."""
        fields["updated_at"] = self._now()
        result = self._users.update_one({"_id": email}, {"$set": fields})
        return result.modified_count > 0

    def delete_user_logs(self, email: str) -> dict:
        """Delete all activity logs for a user. Returns counts per collection."""
        tid = self._get_telegram_user_id(email)
        if not tid:
            return {}
        counts = {}
        for col_name in ("food_entries", "sleep_logs", "workout_logs", "self_care_logs"):
            result = self._db[col_name].delete_many({"telegram_user_id": tid})
            counts[col_name] = result.deleted_count
        return counts

    def seed_test_user(self) -> bool:
        """Create the simulator test user if it doesn't already exist.

        Returns True if the user was created, False if it already exists.
        """
        email = "test@dugri.simulator"
        if self._users.find_one({"_id": email}):
            return False

        now = self._now()
        fresh_toggle = {
            "status": "dormant",
            "revealed_at": None,
            "activated_at": None,
            "last_asked_at": None,
            "consecutive_unanswered": 0,
            "goal_status": "pending",
            "goal_value": None,
            "goal_remind_at": None,
            "goal_offered_at": None,
        }
        doc = {
            "_id": email,
            "name": "Test User",
            "photo_url": None,
            "telegram_user_id": 999999999,
            "signup_session_token": None,
            "signup_session_token_expires_at": None,
            "consents": {},
            "trial_started_at": now,
            "subscription_status": "trial_active",
            "birth_year": None,
            "height_cm": None,
            "weight_kg": None,
            "gender": None,
            "targets": {
                "calories": None, "protein": None,
                "sleep_time": None, "workouts_per_week": None,
                "weight_goal": None,
            },
            "eating_window": None,
            "timezone": "Asia/Jerusalem",
            "timezone_source": "default",
            "timezone_updated_at": None,
            "onboarding": {"name_collected": True, "habits": {}},
            "feedback_steering_prompt": None,
            "last_feedback_offered_at": None,
            "toggles": {
                "sleep": {**fresh_toggle},
                "eating_window": {**fresh_toggle},
                "workouts": {**fresh_toggle},
                "self_care": {**fresh_toggle},
                "nutrition": {**fresh_toggle},
                "weekly_summary": {**fresh_toggle, "status": "active"},
            },
            "dashboard_intro_shown": False,
            "target_retry_done": False,
            "eating_window_retry_done": False,
            "recent_messages": [],
            "strikes": [],
            "banned_at": None,
            "discovered_patterns": [],
            "gem_state": {
                "used_gem_ids": [],
                "cycle_number": 1,
                "last_delivered_at": None,
                "deliveries": [],
                "feedbacks": [],
                "threshold_adjustment": 0.0,
                "week_start_iso": None,
                "gem_delivered_this_week": False,
                "silent_week": False,
            },
            "re_engagement_stage": "none",
            "last_user_message_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._users.insert_one(doc)
        return True
