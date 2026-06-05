"""
reset_user.py — Reset a user's opt-in/goal state for testing.

Usage:
    python scripts/reset_user.py <email>

Resets: toggles, targets, eating_window, trial_started_at,
        recent_messages, dashboard flags, body stats, name/onboarding,
        feedback steering state.
Does NOT delete: food_entries, sleep_logs, workout_logs, self_care_logs,
        consents, email, telegram_user_id.

Full clean-slate reset: the user goes through the complete onboarding
flow (name collection, lazy opt-in, goal setting) from scratch.
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


MONGO_URI = "mongodb://mongo:CeIVOLCoGytTovcrdPkcKLVdgjeoFchP@junction.proxy.rlwy.net:10627"


def get_mongo_uri() -> str:
    return MONGO_URI


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
        "subscription_status": "trial_active",
        "trial_started_at": now,
        "recent_messages": [],
        "dashboard_intro_shown": False,
        "target_retry_done": False,
        "eating_window_retry_done": False,
        # Personal details (collected during nutrition goal flow)
        "name": None,
        "onboarding": {"name_collected": False},
        "birth_year": None,
        "height_cm": None,
        "weight_kg": None,
        "gender": None,
        # Weekly feedback state
        "feedback_steering_prompt": None,
        "last_feedback_offered_at": None,
        "updated_at": now,
    }

    result = db.users.update_one({"_id": email}, {"$set": reset_fields})

    if result.modified_count:
        print(f"\nReset complete.")
        print(f"  trial_started_at: {now}")
        print(f"  subscription_status: trial_active")
        print(f"  toggles: all dormant (weekly_summary active)")
        print(f"  targets: cleared")
        print(f"  eating_window: cleared")
        print(f"  name/onboarding: cleared (will ask name again)")
        print(f"  body stats: cleared (height, weight, birth_year, gender)")
        print(f"  feedback state: cleared")
        print(f"  Food entries: preserved")
    else:
        print("WARNING: No changes made (user may already be in default state)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reset_user.py <email>")
        sys.exit(1)

    reset_user(sys.argv[1])
