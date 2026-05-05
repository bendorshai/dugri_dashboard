from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

import pytest


# Stub pymongo before importing storage
mock_pymongo = MagicMock()
mock_pymongo.DESCENDING = -1
sys.modules.setdefault("pymongo", mock_pymongo)

from storage import MongoStorage


@pytest.fixture
def mock_db():
    mock_client = MagicMock()
    mock_database = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_database)

    collections = {}

    def get_collection(name):
        if name not in collections:
            collections[name] = MagicMock()
        return collections[name]

    mock_database.__getitem__ = MagicMock(side_effect=get_collection)

    with patch("storage.MongoClient", return_value=mock_client):
        storage = MongoStorage(uri="mongodb://test:test@localhost:27017", db_name="health_tracker_test")

    return storage, collections


class TestMongoStorageInit:
    def test_creates_error_ttl_index(self, mock_db):
        storage, collections = mock_db
        collections["error_logs"].create_index.assert_called_once()


class TestUserProfiles:
    def test_get_profile_returns_none_when_missing(self, mock_db):
        storage, collections = mock_db
        collections["user_profiles"].find_one.return_value = None
        assert storage.get_user_profile(123) is None

    def test_get_profile_returns_doc(self, mock_db):
        storage, collections = mock_db
        profile = {"_id": 123, "age": 30, "target_calories": 2000}
        collections["user_profiles"].find_one.return_value = profile
        result = storage.get_user_profile(123)
        assert result == profile
        collections["user_profiles"].find_one.assert_called_with({"_id": 123})

    def test_save_profile_upserts(self, mock_db):
        storage, collections = mock_db
        profile_data = {"age": 30, "height_cm": 175, "weight_kg": 80}
        storage.save_user_profile(123, profile_data)
        collections["user_profiles"].update_one.assert_called_once()
        args = collections["user_profiles"].update_one.call_args
        assert args[0][0] == {"_id": 123}
        assert args[1]["upsert"] is True


class TestFoodEntries:
    def test_save_food_entry_inserts(self, mock_db):
        storage, collections = mock_db
        storage.save_food_entry(
            chat_id=123,
            date_str="05/05/2026",
            time_str="14:30",
            description="שניצל וסלט",
            calories=450,
            protein=35,
            source="text",
            sheet_row=5,
        )
        collections["food_entries"].insert_one.assert_called_once()
        doc = collections["food_entries"].insert_one.call_args[0][0]
        assert doc["chat_id"] == 123
        assert doc["description"] == "שניצל וסלט"
        assert doc["calories"] == 450
        assert doc["protein"] == 35
        assert doc["source"] == "text"
        assert doc["sheet_row"] == 5

    def test_get_today_entries(self, mock_db):
        storage, collections = mock_db
        collections["food_entries"].find.return_value = [
            {"description": "ביצים", "calories": 200, "protein": 15},
        ]
        entries = storage.get_today_entries(123, "05/05/2026")
        collections["food_entries"].find.assert_called_with(
            {"chat_id": 123, "date": "05/05/2026"}
        )
        assert len(entries) == 1

    def test_get_week_entries(self, mock_db):
        storage, collections = mock_db
        collections["food_entries"].find.return_value = []
        storage.get_week_entries(123, ["05/05/2026", "04/05/2026"])
        collections["food_entries"].find.assert_called_with(
            {"chat_id": 123, "date": {"$in": ["05/05/2026", "04/05/2026"]}}
        )


class TestWeeklyFeedback:
    def test_save_weekly_feedback(self, mock_db):
        storage, collections = mock_db
        storage.save_weekly_feedback(
            chat_id=123,
            date_str="05/05/2026",
            feedback_text="מצוין!",
            week_summary={"avg_calories": 1800},
        )
        collections["weekly_feedback"].insert_one.assert_called_once()
        doc = collections["weekly_feedback"].insert_one.call_args[0][0]
        assert doc["feedback_text"] == "מצוין!"

    def test_get_recent_feedbacks(self, mock_db):
        storage, collections = mock_db
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = [{"feedback_text": "טוב!"}]
        collections["weekly_feedback"].find.return_value = mock_cursor
        result = storage.get_recent_feedbacks(123, limit=7)
        assert len(result) == 1


class TestGptInsights:
    def test_save_insight(self, mock_db):
        storage, collections = mock_db
        storage.save_gpt_insight(
            chat_id=123,
            insight_type="feedback_effectiveness",
            insight_text="המשתמש מגיב טוב",
            context={"feedback_given": "כל הכבוד!"},
        )
        collections["gpt_insights"].insert_one.assert_called_once()

    def test_get_insights(self, mock_db):
        storage, collections = mock_db
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = []
        collections["gpt_insights"].find.return_value = mock_cursor
        storage.get_recent_insights(123)
        collections["gpt_insights"].find.assert_called_with({"chat_id": 123})


class TestErrorLogging:
    def test_log_error(self, mock_db):
        storage, collections = mock_db
        err = ValueError("test error")
        storage.log_error(error=err, handler="test", chat_id=123)
        collections["error_logs"].insert_one.assert_called_once()
        doc = collections["error_logs"].insert_one.call_args[0][0]
        assert doc["error_type"] == "ValueError"
        assert doc["chat_id"] == 123
