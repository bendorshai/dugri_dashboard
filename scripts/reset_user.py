"""
reset_user.py — Reset a user's opt-in/goal state for testing.

Usage:
    python scripts/reset_user.py <email>

Resets: toggles, targets, eating_window, trial_started_at, pending_state,
        recent_messages, dashboard flags.
Does NOT delete: food_entries, sleep_logs, workout_logs, self_care_logs.

The user keeps their name, body stats, and food history. Only the lazy
opt-in state machine is rewound so the full onboarding flow restarts.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_mongo_uri() -> str:
    """Read MongoDB URI from config (same logic as main.py)."""
    config_json = os.environ.get("CONFIG2_JSON")
    if config_json:
        cfg = json.loads(config_json)
    else:
        config_path = Path(__file__).parent.parent / "config" / "config.json"
        with open(config_path) as f:
            cfg = json.load(f)
    mongo = cfg.get("mongodb", {})
    return mongo.get("uri", "")


def reset_user(email: str) -> None:
    from pymongo import MongoClient

    uri = get_mongo_uri()
    if not uri:
        print("ERROR: Could not find MongoDB URI in config")
        sys.exit(1)

    client = MongoClient(uri)
    db_name = "health_tracker"
    db = client[db_name]

    # Verify user exists
    user = db.users.find_one({"_id": email})
    if not user:
        print(f"ERROR: User '{email}' not found")
        sys.exit(1)

    print(f"Resetting user: {email}")
    print(f"  telegram_user_id: {user.get('telegram_user_id')}")
    print(f"  name: {user.get('name')}")

    # Fresh toggle defaults
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

    fresh_toggles = {
        "sleep": {**fresh_toggle},
        "eating_window": {**fresh_toggle},
        "workouts": {**fresh_toggle},
        "self_care": {**fresh_toggle},
        "nutrition": {**fresh_toggle},
        "weekly_summary": {**fresh_toggle, "status": "active"},
    }

    now = datetime.now(timezone.utc).isoformat()

    reset_fields = {
        "toggles": fresh_toggles,
        "targets": {
            "calories": None,
            "protein": None,
            "sleep_time": None,
            "workouts_per_week": None,
        },
        "eating_window": None,
        "trial_started_at": now,
        "pending_state": None,
        "recent_messages": [],
        "dashboard_intro_shown": False,
        "target_retry_done": False,
        "eating_window_retry_done": False,
        "updated_at": now,
    }

    result = db.users.update_one({"_id": email}, {"$set": reset_fields})

    if result.modified_count:
        print(f"\nReset complete.")
        print(f"  trial_started_at: {now}")
        print(f"  toggles: all dormant (weekly_summary active)")
        print(f"  targets: cleared")
        print(f"  eating_window: cleared")
        print(f"  Food entries: preserved")
    else:
        print("WARNING: No changes made (user may already be in default state)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reset_user.py <email>")
        sys.exit(1)

    reset_user(sys.argv[1])
