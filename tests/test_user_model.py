"""
test_user_model — TDD tests for the unified User model.

Tests the new User model where PK is email and telegram_user_id is optional.
"""

from datetime import datetime, timezone

import pytest

from models.profile import (
    User, EatingWindow, Targets, Onboarding, OnboardingHabits,
)


class TestUserModelBasics:
    def test_create_minimal_user(self):
        user = User(email="a@b.com")
        assert user.email == "a@b.com"
        assert user.telegram_user_id is None
        assert user.subscription_status == "trial_pending"
        assert user.trial_started_at is None

    def test_create_user_with_telegram_id(self):
        user = User(email="a@b.com", telegram_user_id=12345)
        assert user.telegram_user_id == 12345

    def test_defaults_are_sensible(self):
        user = User(email="a@b.com")
        assert user.name is None
        assert user.gender is None
        assert user.photo_url is None
        assert user.targets.calories is None
        assert user.eating_window is None
        assert user.timezone == "Asia/Jerusalem"
        assert user.consents == {}
        assert user.birth_year is None
        assert user.height_cm is None
        assert user.weight_kg is None


class TestUserMongoSerialization:
    def test_to_mongo_dict_maps_email_to_id(self):
        user = User(email="a@b.com", telegram_user_id=12345, name="Test")
        doc = user.to_mongo_dict()
        assert doc["_id"] == "a@b.com"
        assert "email" not in doc
        assert doc["telegram_user_id"] == 12345
        assert doc["name"] == "Test"

    def test_from_mongo_dict_maps_id_to_email(self):
        doc = {
            "_id": "a@b.com",
            "telegram_user_id": 12345,
            "name": "Test",
        }
        user = User.from_mongo_dict(doc)
        assert user.email == "a@b.com"
        assert user.telegram_user_id == 12345
        assert user.name == "Test"

    def test_round_trip(self):
        original = User(
            email="a@b.com",
            telegram_user_id=12345,
            name="שי",
            targets=Targets(calories=2000, protein=120),
            eating_window=EatingWindow(start="10:00", end="18:00"),
            consents={"terms_accepted_at": "2026-05-20"},
            birth_year=1990,
        )
        doc = original.to_mongo_dict()
        restored = User.from_mongo_dict(doc)
        assert restored.email == original.email
        assert restored.telegram_user_id == original.telegram_user_id
        assert restored.name == original.name
        assert restored.targets.calories == 2000
        assert restored.eating_window.start == "10:00"
        assert restored.consents == {"terms_accepted_at": "2026-05-20"}
        assert restored.birth_year == 1990

    def test_from_mongo_dict_without_telegram_id(self):
        """Dashboard-created user with no bot contact yet."""
        doc = {
            "_id": "a@b.com",
            "name": "Test",
            "subscription_status": "trial_pending",
        }
        user = User.from_mongo_dict(doc)
        assert user.email == "a@b.com"
        assert user.telegram_user_id is None


class TestUserLegacyMigration:
    def test_handles_legacy_flat_targets(self):
        doc = {
            "_id": "a@b.com",
            "target_calories": 2000,
            "target_protein": 120,
        }
        user = User.from_mongo_dict(doc)
        assert user.targets.calories == 2000
        assert user.targets.protein == 120

    def test_handles_legacy_eating_window_fields(self):
        doc = {
            "_id": "a@b.com",
            "eating_window_start": "10:00",
            "eating_window_end": "18:00",
        }
        user = User.from_mongo_dict(doc)
        assert user.eating_window is not None
        assert user.eating_window.start == "10:00"

    def test_strips_legacy_dashboard_fields(self):
        """Fields from old dashboard_users that aren't in the User model."""
        doc = {
            "_id": "a@b.com",
            "chat_id": 12345,
            "onboarding_complete": True,
            "terms_accepted": True,
            "bot_key": "abc123",
        }
        user = User.from_mongo_dict(doc)
        assert user.email == "a@b.com"
        # These legacy fields should not cause validation errors


class TestUserProfileAlias:
    """UserProfile should still work as an alias for backward compat."""

    def test_userprofile_alias_exists(self):
        from models.profile import UserProfile
        assert UserProfile is User
