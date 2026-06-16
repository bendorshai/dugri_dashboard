"""
migrate_toggles.py - One-time migration: add toggles field to existing users.

Converts old onboarding.habits states to new toggles format.
Safe to run multiple times - skips users that already have toggles.

Usage:
    python scripts/migrate_toggles.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pymongo import MongoClient


STATE_MAP = {
    "pending": "dormant",
    "offered": "dormant",
    "active": "active",
    "declined": "cancelled",
}

HABIT_TO_TOGGLE = {
    "sleep": "sleep",
    "workouts": "workouts",
    "self_care": "self_care",
    "nutrition": "target_data",
    "eating_window": "eating_window",
}

DEFAULT_TOGGLES = {
    "sleep": {"status": "dormant"},
    "eating_window": {"status": "dormant"},
    "workouts": {"status": "dormant"},
    "self_care": {"status": "dormant"},
    "target_data": {"status": "dormant"},
    "weekly_summary": {"status": "active"},
}


def migrate_user(doc: dict) -> dict | None:
    """Build toggles dict from old onboarding.habits. Returns None if already migrated."""
    if "toggles" in doc:
        return None

    onboarding = doc.get("onboarding", {})
    habits = onboarding.get("habits", {}) if isinstance(onboarding, dict) else {}

    toggles = dict(DEFAULT_TOGGLES)
    for old_name, new_name in HABIT_TO_TOGGLE.items():
        habit = habits.get(old_name, {})
        if isinstance(habit, dict):
            old_state = habit.get("state", "pending")
            toggles[new_name] = {"status": STATE_MAP.get(old_state, "dormant")}

    # weekly_summary always starts active (opt-out default)
    toggles["weekly_summary"] = {"status": "active"}

    return toggles


def main():
    parser = argparse.ArgumentParser(description="Migrate users to toggles system")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    config_path = Path(__file__).parent.parent / "config" / "config.json"
    if not config_path.exists():
        print(f"Config not found at {config_path}")
        sys.exit(1)

    config = json.loads(config_path.read_text())
    mongo_cfg = config["mongodb"]
    client = MongoClient(mongo_cfg["uri"])
    db = client[mongo_cfg["db_name"]]
    users = db["users"]

    total = 0
    migrated = 0
    skipped = 0

    for doc in users.find():
        total += 1
        toggles = migrate_user(doc)
        if toggles is None:
            skipped += 1
            continue

        update = {
            "$set": {
                "toggles": toggles,
                "dashboard_intro_shown": False,
                "target_retry_done": False,
                "eating_window_retry_done": False,
            }
        }

        if args.dry_run:
            print(f"  [DRY RUN] Would update {doc['_id']}: {toggles}")
        else:
            users.update_one({"_id": doc["_id"]}, update)

        migrated += 1

    print(f"\nTotal: {total}, Migrated: {migrated}, Skipped (already have toggles): {skipped}")
    if args.dry_run:
        print("(dry run - no changes written)")


if __name__ == "__main__":
    main()
