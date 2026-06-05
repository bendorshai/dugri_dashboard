"""
test_storage_v2 — TDD tests for new dashboard storage methods.

Tests toggle management, unified targets, and weekly summaries retrieval.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from storage import DashboardStorage


@pytest.fixture()
def mock_client():
    with patch("storage.MongoClient") as mock_cls:
        mock_db = MagicMock()
        mock_cls.return_value.__getitem__ = MagicMock(return_value=mock_db)
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        yield mock_cls, mock_db, mock_collection


@pytest.fixture()
def storage(mock_client):
    return DashboardStorage(uri="mongodb://localhost:27017", db_name="test_db")


class TestUpdateUserToggles:
    def test_updates_toggles_field(self, storage):
        toggles = {"sleep": {"status": "active"}, "workouts": {"status": "dormant"}}
        storage.update_user_toggles("a@b.com", toggles)
        storage._users.update_one.assert_called_once()
        call_args = storage._users.update_one.call_args
        assert call_args[0][0] == {"_id": "a@b.com"}
        set_data = call_args[0][1]["$set"]
        assert set_data["toggles"] == toggles
        assert "updated_at" in set_data


class TestUpdateUserTargets:
    def test_updates_calorie_and_protein_targets(self, storage):
        old = storage.update_user_targets("a@b.com", 1800, 130)
        storage._users.update_one.assert_called_once()
        set_data = storage._users.update_one.call_args[0][1]["$set"]
        assert set_data["targets.calories"] == 1800
        assert set_data["targets.protein"] == 130

    def test_returns_old_targets(self, storage):
        storage._users.find_one.return_value = {
            "_id": "a@b.com",
            "targets": {"calories": 2000, "protein": 150},
        }
        old = storage.update_user_targets("a@b.com", 1800, 130)
        assert old == {"calories": 2000, "protein": 150}

    def test_returns_empty_when_no_prior_targets(self, storage):
        storage._users.find_one.return_value = {"_id": "a@b.com"}
        old = storage.update_user_targets("a@b.com", 1800, 130)
        assert old == {}

    def test_handles_none_targets(self, storage):
        storage._users.find_one.return_value = None
        old = storage.update_user_targets("a@b.com", 1800, 130)
        assert old == {}


class TestGetWeeklySummaries:
    def test_queries_by_telegram_user_id(self, storage):
        # Setup: user has telegram_user_id
        storage._users.find_one.return_value = {
            "_id": "a@b.com",
            "telegram_user_id": 123,
        }
        # Mock the weekly_feedback collection
        mock_feedback = MagicMock()
        storage._db.__getitem__ = MagicMock(return_value=mock_feedback)
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = [
            {"date": "22/05/2026", "feedback_text": "Great week"},
        ]
        mock_feedback.find.return_value = cursor

        summaries = storage.get_weekly_summaries("a@b.com", limit=10)
        assert len(summaries) == 1
        assert summaries[0]["feedback_text"] == "Great week"

    def test_returns_empty_when_no_telegram_id(self, storage):
        storage._users.find_one.return_value = {
            "_id": "a@b.com",
            "telegram_user_id": None,
        }
        summaries = storage.get_weekly_summaries("a@b.com")
        assert summaries == []

    def test_returns_empty_when_user_not_found(self, storage):
        storage._users.find_one.return_value = None
        summaries = storage.get_weekly_summaries("a@b.com")
        assert summaries == []


class TestGetTrendData:
    def _setup_user(self, storage, targets=None):
        storage._users.find_one.return_value = {
            "_id": "a@b.com",
            "telegram_user_id": 123,
            "targets": targets or {},
        }

    def _setup_collections(self, storage, food=None, workouts=None):
        collections = {}

        def get_collection(name):
            if name not in collections:
                collections[name] = MagicMock()
                collections[name].find.return_value = []
            return collections[name]

        storage._db.__getitem__ = MagicMock(side_effect=get_collection)
        if food is not None:
            get_collection("food_entries").find.return_value = food
        if workouts is not None:
            get_collection("workout_logs").find.return_value = workouts

    def test_returns_all_metrics_and_targets(self, storage):
        self._setup_user(storage, {"calories": 2000, "protein": 150, "workouts_per_week": 3})
        self._setup_collections(storage)

        result = storage.get_trend_data("a@b.com", days=7)
        assert "days" in result
        assert result["targets"]["calories"] == 2000
        assert result["targets"]["protein"] == 150
        assert result["targets"]["workouts_per_week"] == 3

    def test_aggregates_calories_and_protein_per_day(self, storage):
        today_str = date.today().strftime("%d/%m/%Y")
        self._setup_user(storage, {"calories": 2000})
        self._setup_collections(storage, food=[
            {"date": today_str, "calories": 500, "protein": 30},
            {"date": today_str, "calories": 700, "protein": 50},
        ])

        result = storage.get_trend_data("a@b.com", days=1)
        day = result["days"][0]
        assert day["calories"] == 1200
        assert day["protein"] == 80

    def test_counts_workouts_per_day(self, storage):
        today_str = date.today().strftime("%d/%m/%Y")
        self._setup_user(storage)
        self._setup_collections(storage, food=[], workouts=[
            {"date": today_str},
            {"date": today_str},
        ])

        result = storage.get_trend_data("a@b.com", days=1)
        assert result["days"][0]["workouts"] == 2

    def test_fills_missing_days_with_zero(self, storage):
        self._setup_user(storage)
        self._setup_collections(storage)

        result = storage.get_trend_data("a@b.com", days=7)
        assert len(result["days"]) == 7
        for d in result["days"]:
            assert d["calories"] == 0
            assert d["protein"] == 0
            assert d["workouts"] == 0

    def test_days_sorted_chronologically(self, storage):
        self._setup_user(storage)
        self._setup_collections(storage)

        result = storage.get_trend_data("a@b.com", days=7)
        dates = [d["date"] for d in result["days"]]
        assert dates == sorted(dates, key=lambda d: d.split("/")[::-1])

    def test_days_zero_returns_all_history(self, storage):
        self._setup_user(storage)
        self._setup_collections(storage, food=[
            {"date": "01/01/2025", "calories": 100, "protein": 10},
        ])

        result = storage.get_trend_data("a@b.com", days=0)
        # Should query without date filter and build days from entries
        assert any(d["calories"] == 100 for d in result["days"])

    def test_returns_empty_when_no_telegram_id(self, storage):
        storage._users.find_one.return_value = {
            "_id": "a@b.com",
            "telegram_user_id": None,
        }
        result = storage.get_trend_data("a@b.com", days=7)
        assert result == {"days": [], "targets": {}}

    def test_returns_empty_when_user_not_found(self, storage):
        storage._users.find_one.return_value = None
        result = storage.get_trend_data("a@b.com", days=7)
        assert result == {"days": [], "targets": {}}


class TestCreateUserWithToggles:
    def test_new_user_has_toggles_field(self, storage):
        storage.create_user("a@b.com", "Test User")
        doc = storage._users.insert_one.call_args[0][0]
        assert "toggles" in doc
        assert doc["toggles"]["weekly_summary"]["status"] == "active"
        assert doc["toggles"]["sleep"]["status"] == "dormant"
