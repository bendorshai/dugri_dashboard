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
        assert "created_at" in doc
        # Bot fields initialized as defaults
        assert doc["targets"]["calories"] is None
        assert doc["timezone"] == "Asia/Jerusalem"

    def test_inserts_with_photo_url(self, storage):
        storage.create_user("a@b.com", "Test", photo_url="https://photo.url/pic.jpg")
        doc = storage._users.insert_one.call_args[0][0]
        assert doc["photo_url"] == "https://photo.url/pic.jpg"

    def test_inserts_without_photo_url_defaults_to_none(self, storage):
        storage.create_user("a@b.com", "Test")
        doc = storage._users.insert_one.call_args[0][0]
        assert doc["photo_url"] is None

    def test_inserts_with_consents(self, storage):
        consents = {
            "terms_accepted_at": "2026-05-19T00:00:00",
            "privacy_accepted_at": "2026-05-19T00:00:00",
            "medical_disclaimer_accepted_at": "2026-05-19T00:00:00",
            "marketing_opt_in": True,
            "marketing_opt_in_at": "2026-05-19T00:00:00",
            "consent_version": "2026-05-19",
        }
        storage.create_user("a@b.com", "Test", consents=consents)
        doc = storage._users.insert_one.call_args[0][0]
        assert doc["consents"] == consents
        assert doc["consents"]["marketing_opt_in"] is True

    def test_new_user_has_trial_pending_status(self, storage):
        storage.create_user("a@b.com", "Test")
        doc = storage._users.insert_one.call_args[0][0]
        assert doc["subscription_status"] == "trial_pending"
        assert doc["trial_started_at"] is None
        # telegram_user_id is omitted (not null) so the sparse unique index skips
        # unlinked users; .get() therefore returns None for a fresh signup.
        assert doc.get("telegram_user_id") is None
        assert "telegram_user_id" not in doc
        assert doc["signup_session_token"] is None


class TestUpdateUserProfile:
    def test_updates_profile_fields(self, storage):
        storage.update_user_profile("a@b.com", {"birth_year": 1990, "weight_kg": 80})
        storage._users.update_one.assert_called_once()
        call_args = storage._users.update_one.call_args
        assert call_args[0][0] == {"_id": "a@b.com"}
        set_data = call_args[0][1]["$set"]
        assert set_data["birth_year"] == 1990
        assert "updated_at" in set_data


class TestCompleteOnboarding:
    def test_marks_onboarding_complete(self, storage):
        storage.complete_onboarding("a@b.com")
        storage._users.update_one.assert_called_once()


class TestSetSignupSessionToken:
    def test_sets_token_and_expiry(self, storage):
        storage.set_signup_session_token("a@b.com", "tok123", "2026-05-20T00:00:00")
        storage._users.update_one.assert_called_once()
        set_data = storage._users.update_one.call_args[0][1]["$set"]
        assert set_data["signup_session_token"] == "tok123"
        assert set_data["signup_session_token_expires_at"] == "2026-05-20T00:00:00"
        assert "updated_at" in set_data


class TestRegenerateSignupSessionToken:
    def test_returns_token_string(self, storage):
        token = storage.regenerate_signup_session_token("a@b.com")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_stores_token_in_db(self, storage):
        storage.regenerate_signup_session_token("a@b.com")
        storage._users.update_one.assert_called_once()
        set_data = storage._users.update_one.call_args[0][1]["$set"]
        assert set_data["signup_session_token"] is not None
        assert set_data["signup_session_token_expires_at"] is not None


class TestGetUserBySessionToken:
    def test_queries_with_token_and_expiry(self, storage):
        storage._users.find_one.return_value = {"_id": "a@b.com"}
        result = storage.get_user_by_session_token("tok123")
        assert result is not None
        query = storage._users.find_one.call_args[0][0]
        assert query["signup_session_token"] == "tok123"
        assert "$gt" in query["signup_session_token_expires_at"]

    def test_returns_none_when_no_match(self, storage):
        storage._users.find_one.return_value = None
        assert storage.get_user_by_session_token("bad-token") is None
