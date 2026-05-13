from __future__ import annotations

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
    _, _, _ = mock_client
    return DashboardStorage(uri="mongodb://localhost:27017", db_name="test_db")


class TestGetUser:
    def test_returns_user_when_found(self, storage):
        storage._users.find_one.return_value = {"_id": "a@b.com", "name": "Test"}
        result = storage.get_user("a@b.com")
        assert result["name"] == "Test"
        storage._users.find_one.assert_called_once_with({"_id": "a@b.com"})

    def test_returns_none_when_not_found(self, storage):
        storage._users.find_one.return_value = None
        assert storage.get_user("missing@b.com") is None


class TestCreateUser:
    def test_inserts_user_document(self, storage):
        storage.create_user("a@b.com", "Test User")
        storage._users.insert_one.assert_called_once()
        doc = storage._users.insert_one.call_args[0][0]
        assert doc["_id"] == "a@b.com"
        assert doc["name"] == "Test User"
        assert doc["onboarding_complete"] is False
        assert "created_at" in doc
        assert "goals" in doc


class TestUpdateUserProfile:
    def test_updates_profile_fields(self, storage):
        storage.update_user_profile("a@b.com", {"birth_year": 1990, "weight_kg": 80})
        storage._users.update_one.assert_called_once()
        call_args = storage._users.update_one.call_args
        assert call_args[0][0] == {"_id": "a@b.com"}
        set_data = call_args[0][1]["$set"]
        assert set_data["birth_year"] == 1990
        assert "updated_at" in set_data


class TestUpdateUserGoals:
    def test_updates_goals(self, storage):
        goals = {"calories": {"enabled": True, "target": 2000}}
        storage.update_user_goals("a@b.com", goals)
        storage._users.update_one.assert_called_once()
        set_data = storage._users.update_one.call_args[0][1]["$set"]
        assert set_data["goals"] == goals


class TestCompleteOnboarding:
    def test_marks_onboarding_complete(self, storage):
        storage.complete_onboarding("a@b.com")
        storage._users.update_one.assert_called_once()
        set_data = storage._users.update_one.call_args[0][1]["$set"]
        assert set_data["onboarding_complete"] is True
