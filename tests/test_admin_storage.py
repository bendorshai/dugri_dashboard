from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from admin_storage import AdminStorage, _cache, CACHE_TTL


@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture()
def storage():
    with patch("admin_storage.MongoClient") as mock_client:
        mock_db = MagicMock()
        mock_client.return_value.__getitem__ = MagicMock(return_value=mock_db)
        s = AdminStorage(uri="mongodb://localhost", db_name="test")
        s._db = mock_db
        s._users = mock_db["users"]
        s._food = mock_db["food_entries"]
        s._sleep = mock_db["sleep_logs"]
        s._workouts = mock_db["workout_logs"]
        s._self_care = mock_db["self_care_logs"]
        return s


class TestKPIs:
    def test_total_users(self, storage):
        storage._users.count_documents.return_value = 7
        assert storage.get_total_users() == 7
        storage._users.count_documents.assert_called_once_with(
            {"telegram_user_id": {"$ne": None}},
        )

    def test_total_signups(self, storage):
        storage._users.count_documents.return_value = 12
        assert storage.get_total_signups() == 12
        storage._users.count_documents.assert_called_once_with({})

    def test_active_this_week(self, storage):
        storage._food.aggregate.return_value = [{"n": 4}]
        assert storage.get_active_this_week() == 4

    def test_active_this_week_empty(self, storage):
        storage._food.aggregate.return_value = []
        assert storage.get_active_this_week() == 0


class TestCache:
    def test_cache_returns_stored_value(self, storage):
        storage._users.count_documents.return_value = 5
        first = storage.get_total_users()
        storage._users.count_documents.return_value = 99
        second = storage.get_total_users()
        assert first == second == 5
        assert storage._users.count_documents.call_count == 1

    def test_cache_expires(self, storage):
        storage._users.count_documents.return_value = 5
        storage.get_total_users()

        # Manually expire cache
        key = "total_users"
        _cache[key] = (_cache[key][0] - CACHE_TTL - 1, _cache[key][1])

        storage._users.count_documents.return_value = 10
        assert storage.get_total_users() == 10
        assert storage._users.count_documents.call_count == 2


class TestHabitAdoption:
    def test_counts_active_toggles(self, storage):
        # count_documents will be called 5 times, once per habit
        storage._users.count_documents.side_effect = [10, 5, 8, 3, 15]
        result = storage.get_habit_adoption()
        assert result == {
            "sleep": 10,
            "eating_window": 5,
            "workouts": 8,
            "self_care": 3,
            "weekly_summary": 15,
        }


class TestActivityHours:
    def test_returns_24_hours(self, storage):
        storage._food.aggregate.return_value = [
            {"_id": 8, "count": 5},
            {"_id": 13, "count": 12},
            {"_id": 20, "count": 8},
        ]
        result = storage.get_activity_hours()
        assert len(result) == 24
        assert result[8] == 5
        assert result[13] == 12
        assert result[20] == 8
        assert result[0] == 0


class TestStuckAtGate:
    def test_includes_unlinked_users(self, storage):
        storage._users.find.side_effect = [
            # First call: unlinked users
            [{"_id": "no-bot@test.com", "name": "No Bot", "created_at": "2026-05-20"}],
            # Second call: linked users
            [],
        ]

        result = storage.get_stuck_at_gate_users()
        assert len(result) == 1
        assert result[0]["email"] == "no-bot@test.com"
        assert result[0]["sub_reason"] == "never_linked"

    def test_includes_linked_with_no_entries(self, storage):
        storage._users.find.side_effect = [
            # First call: unlinked users
            [],
            # Second call: linked users
            [{"_id": "linked@test.com", "name": "Linked", "telegram_user_id": 111, "created_at": "2026-05-20"}],
        ]
        storage._food.count_documents.return_value = 0

        result = storage.get_stuck_at_gate_users()
        assert len(result) == 1
        assert result[0]["email"] == "linked@test.com"
        assert result[0]["sub_reason"] == "linked_no_entries"


class TestEnrichLeads:
    def test_joins_user_info(self, storage):
        storage._users.find.return_value = [
            {"_id": "user@test.com", "name": "Test", "telegram_user_id": 123, "created_at": "2026-05-20"},
        ]

        result = storage._enrich_leads(
            [{"_id": 123, "last_active": "2026-05-22"}],
            "super_active",
        )
        assert len(result) == 1
        assert result[0]["email"] == "user@test.com"
        assert result[0]["name"] == "Test"
        assert result[0]["category"] == "super_active"

    def test_empty_input(self, storage):
        assert storage._enrich_leads([], "churning") == []
