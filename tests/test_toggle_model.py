"""
test_toggle_model - TDD tests for the toggle system data model.

Tests ToggleState, Toggles, and User model integration with toggles.
"""

from datetime import datetime, timezone

import pytest

from models.profile import (
    User, ToggleState, Toggles, Targets, EatingWindow,
    Onboarding, OnboardingHabits, HabitState,
)


class TestToggleStateDefaults:
    def test_default_state_is_dormant(self):
        ts = ToggleState()
        assert ts.status == "dormant"
        assert ts.revealed_at is None
        assert ts.activated_at is None
        assert ts.last_asked_at is None
        assert ts.consecutive_unanswered == 0

    def test_accepts_valid_statuses(self):
        for status in ("dormant", "active", "cancelled"):
            ts = ToggleState(status=status)
            assert ts.status == status

    def test_rejects_invalid_status(self):
        with pytest.raises(Exception):
            ToggleState(status="pending")

    def test_can_set_timestamps(self):
        now = datetime.now(timezone.utc)
        ts = ToggleState(
            status="active",
            revealed_at=now,
            activated_at=now,
            last_asked_at=now,
            consecutive_unanswered=0,
        )
        assert ts.revealed_at == now
        assert ts.activated_at == now


class TestTogglesDefaults:
    def test_all_opt_in_toggles_start_dormant(self):
        toggles = Toggles()
        assert toggles.sleep.status == "dormant"
        assert toggles.eating_window.status == "dormant"
        assert toggles.workouts.status == "dormant"
        assert toggles.self_care.status == "dormant"
        assert toggles.nutrition.status == "dormant"

    def test_weekly_summary_starts_active(self):
        """Weekly summary is opt-out default - born active."""
        toggles = Toggles()
        assert toggles.weekly_summary.status == "active"

    def test_toggle_names(self):
        """All expected toggle names exist."""
        toggles = Toggles()
        expected = {"sleep", "eating_window", "workouts", "self_care", "nutrition", "weekly_summary"}
        actual = set(Toggles.model_fields.keys())
        assert expected == actual


class TestUserWithToggles:
    def test_user_has_toggles_field(self):
        user = User(email="a@b.com")
        assert isinstance(user.toggles, Toggles)

    def test_user_has_dashboard_intro_shown(self):
        user = User(email="a@b.com")
        assert user.dashboard_intro_shown is False

    def test_user_has_target_retry_done(self):
        user = User(email="a@b.com")
        assert user.target_retry_done is False

    def test_user_has_eating_window_retry_done(self):
        user = User(email="a@b.com")
        assert user.eating_window_retry_done is False

    def test_toggles_round_trip_mongo(self):
        """Toggles survive to_mongo_dict -> from_mongo_dict."""
        now = datetime.now(timezone.utc)
        user = User(
            email="a@b.com",
            toggles=Toggles(
                sleep=ToggleState(status="active", activated_at=now),
                workouts=ToggleState(status="cancelled"),
            ),
            dashboard_intro_shown=True,
            target_retry_done=True,
            eating_window_retry_done=True,
        )
        doc = user.to_mongo_dict()
        restored = User.from_mongo_dict(doc)
        assert restored.toggles.sleep.status == "active"
        assert restored.toggles.sleep.activated_at == now
        assert restored.toggles.workouts.status == "cancelled"
        assert restored.toggles.weekly_summary.status == "active"
        assert restored.dashboard_intro_shown is True
        assert restored.target_retry_done is True
        assert restored.eating_window_retry_done is True


class TestToggleMigration:
    """Test migration from old onboarding.habits format to new toggles format."""

    def test_migrates_pending_to_dormant(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "name_collected": True,
                "habits": {
                    "sleep": {"state": "pending"},
                    "workouts": {"state": "pending"},
                    "self_care": {"state": "pending"},
                    "nutrition": {"state": "pending"},
                    "eating_window": {"state": "pending"},
                },
            },
        }
        user = User.from_mongo_dict(doc)
        assert user.toggles.sleep.status == "dormant"
        assert user.toggles.workouts.status == "dormant"
        assert user.toggles.self_care.status == "dormant"
        assert user.toggles.nutrition.status == "dormant"
        assert user.toggles.eating_window.status == "dormant"

    def test_migrates_offered_to_dormant(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "name_collected": True,
                "habits": {
                    "sleep": {"state": "offered"},
                },
            },
        }
        user = User.from_mongo_dict(doc)
        assert user.toggles.sleep.status == "dormant"

    def test_migrates_active_to_active(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "name_collected": True,
                "habits": {
                    "sleep": {"state": "active"},
                    "workouts": {"state": "active"},
                },
            },
        }
        user = User.from_mongo_dict(doc)
        assert user.toggles.sleep.status == "active"
        assert user.toggles.workouts.status == "active"

    def test_migrates_declined_to_cancelled(self):
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "name_collected": True,
                "habits": {
                    "sleep": {"state": "declined"},
                },
            },
        }
        user = User.from_mongo_dict(doc)
        assert user.toggles.sleep.status == "cancelled"

    def test_no_onboarding_habits_keeps_defaults(self):
        doc = {"_id": "a@b.com"}
        user = User.from_mongo_dict(doc)
        assert user.toggles.sleep.status == "dormant"
        assert user.toggles.weekly_summary.status == "active"

    def test_existing_toggles_field_not_overwritten_by_migration(self):
        """If document already has toggles, don't overwrite from onboarding."""
        doc = {
            "_id": "a@b.com",
            "toggles": {
                "sleep": {"status": "active"},
                "eating_window": {"status": "dormant"},
                "workouts": {"status": "dormant"},
                "self_care": {"status": "dormant"},
                "target_data": {"status": "dormant"},
                "weekly_summary": {"status": "active"},
            },
            "onboarding": {
                "name_collected": True,
                "habits": {
                    "sleep": {"state": "declined"},
                },
            },
        }
        user = User.from_mongo_dict(doc)
        # toggles field takes precedence - sleep stays active, not cancelled
        assert user.toggles.sleep.status == "active"

    def test_migration_maps_nutrition_habit_to_nutrition_toggle(self):
        """Old 'nutrition' habit maps to 'nutrition' toggle."""
        doc = {
            "_id": "a@b.com",
            "onboarding": {
                "name_collected": True,
                "habits": {
                    "nutrition": {"state": "active"},
                },
            },
        }
        user = User.from_mongo_dict(doc)
        assert user.toggles.nutrition.status == "active"


class TestBackwardCompatibility:
    """Ensure old HabitState/OnboardingHabits still importable for existing tests."""

    def test_old_classes_still_importable(self):
        assert HabitState is not None
        assert OnboardingHabits is not None

    def test_old_onboarding_field_still_works(self):
        user = User(email="a@b.com")
        assert isinstance(user.onboarding, Onboarding)
        assert user.onboarding.name_collected is False
