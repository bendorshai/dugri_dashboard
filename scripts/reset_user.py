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

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


MONGO_URI = "mongodb://mongo:CeIVOLCoGytTovcrdPkcKLVdgjeoFchP@junction.proxy.rlwy.net:10627"

ONBOARDING_GREETING = (
    "היי, אני דוגרי 👋\n\n"
    "הלב של מה שאני עושה הוא מודעות תזונתית — "
    "שלח לי את הארוחה הבאה שלך בכמה מילים ואני אעשה את החישוב.\n\n"
    "לפני שמתחילים, איך אתה רוצה שאקרא לך?"
)


def get_mongo_uri() -> str:
    return MONGO_URI


def get_bot_token() -> str:
    config_path = Path(__file__).resolve().parent.parent / "config" / "config.json"
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    return config["telegram"]["bot_token"]


def send_greeting(bot_token: str, telegram_user_id: int) -> None:
    """Send the onboarding greeting via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": telegram_user_id,
        "text": ONBOARDING_GREETING,
    })
    if resp.ok:
        print(f"  Greeting sent to Telegram user {telegram_user_id}")
    else:
        print(f"  WARNING: Failed to send greeting: {resp.text}")


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
            "weight_goal": None,
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
        "discovered_patterns": [],
        "strikes": [],
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

        # Send greeting via Telegram and save to recent_messages
        tid = user.get("telegram_user_id")
        if tid:
            try:
                bot_token = get_bot_token()
                send_greeting(bot_token, tid)
                # Save greeting to recent_messages so classifier sees it in history
                greeting_msg = {
                    "role": "bot",
                    "text": ONBOARDING_GREETING[:500],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                db.users.update_one(
                    {"_id": email},
                    {"$push": {"recent_messages": greeting_msg}},
                )
            except Exception as e:
                print(f"  WARNING: Could not send greeting: {e}")
    else:
        print("WARNING: No changes made (user may already be in default state)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reset_user.py <email>")
        sys.exit(1)

    reset_user(sys.argv[1])
