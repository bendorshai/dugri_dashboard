"""
test_migration — Tests for the toggles migration logic.
"""

import sys
from pathlib import Path

import pytest

# Add scripts to path so we can import migrate_toggles
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from migrate_toggles import migrate_user


class TestMigrateUser:
    def test_skips_user_with_existing_toggles(self):
        doc = {
            "_id": "a@b.com",
            "toggles": {"sleep": {"status": "active"}},
        }
        assert migrate_user(doc) is None

    def test_creates_defaults_for_user_without_onboarding(self):
        doc = {"_id": "a@b.com"}
        result = migrate_user(doc)
        assert result is not None
        assert result["sleep"]["status"] == "dormant"
        assert result["workouts"]["status"] == "dormant"
        assert result["self_care"]["status"] == "dormant"
        assert result["target_data"]["status"] == "dormant"
        assert result["eating_window"]["status"] == "dormant"
        assert result["weekly_summary"]["status"] == "active"

    def test_maps_pending_to_dormant(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "habits": {"sleep": {"state": "pending"}},
            },
        }
        result = migrate_user(doc)
        assert result["sleep"]["status"] == "dormant"

    def test_maps_offered_to_dormant(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "habits": {"workouts": {"state": "offered"}},
            },
        }
        result = migrate_user(doc)
        assert result["workouts"]["status"] == "dormant"

    def test_maps_active_to_active(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "habits": {"sleep": {"state": "active"}},
            },
        }
        result = migrate_user(doc)
        assert result["sleep"]["status"] == "active"

    def test_maps_declined_to_cancelled(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "habits": {"self_care": {"state": "declined"}},
            },
        }
        result = migrate_user(doc)
        assert result["self_care"]["status"] == "cancelled"

    def test_maps_nutrition_to_target_data(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "habits": {"nutrition": {"state": "active"}},
            },
        }
        result = migrate_user(doc)
        assert result["target_data"]["status"] == "active"

    def test_maps_eating_window(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "habits": {"eating_window": {"state": "active"}},
            },
        }
        result = migrate_user(doc)
        assert result["eating_window"]["status"] == "active"

    def test_weekly_summary_always_active(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "habits": {
                    "sleep": {"state": "active"},
                    "workouts": {"state": "declined"},
                },
            },
        }
        result = migrate_user(doc)
        assert result["weekly_summary"]["status"] == "active"

    def test_handles_empty_habits_dict(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {"habits": {}},
        }
        result = migrate_user(doc)
        assert result is not None
        assert result["sleep"]["status"] == "dormant"

    def test_full_migration_scenario(self):
        """Realistic user with mixed habit states."""
        doc = {
            "_id": "user@example.com",
            "onboarding": {
                "name_collected": True,
                "habits": {
                    "nutrition": {"state": "active", "last_prompted_at": "2026-05-20"},
                    "eating_window": {"state": "offered"},
                    "sleep": {"state": "active"},
                    "workouts": {"state": "pending"},
                    "self_care": {"state": "declined"},
                },
            },
        }
        result = migrate_user(doc)
        assert result["target_data"]["status"] == "active"
        assert result["eating_window"]["status"] == "dormant"
        assert result["sleep"]["status"] == "active"
        assert result["workouts"]["status"] == "dormant"
        assert result["self_care"]["status"] == "cancelled"
        assert result["weekly_summary"]["status"] == "active"
