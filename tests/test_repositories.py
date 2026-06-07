"""
test_repositories — TDD tests for all repository classes.

Uses mock pymongo collections (same pattern as existing test_storage.py).
Includes multi-user isolation tests.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from models.profile import UserProfile, EatingWindow, Targets
from models.food import FoodEntry
from repositories.user_repository import UserRepository
from repositories.food_repository import FoodRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from repositories.error_repository import ErrorRepository
from repositories.token_log_repository import TokenLogRepository


FAKE_OID = str(ObjectId())
FAKE_OID_2 = str(ObjectId())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_collection():
    return MagicMock()


def _make_profile(tid: int = 123, **kwargs) -> UserProfile:
    kwargs.setdefault("email", "test@test.com")
    return UserProfile(telegram_user_id=tid, **kwargs)


def _make_food_entry(tid: int = 123, **kwargs) -> FoodEntry:
    defaults = {
        "telegram_user_id": tid,
        "date": "05/05/2026",
        "time": "14:30",
        "description": "test food",
        "calories": 500,
        "protein": 30,
        "within_window": True,
    }
    defaults.update(kwargs)
    return FoodEntry(**defaults)


# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------

class TestUserRepository:
    def test_get_returns_none_when_missing(self):
        col = _make_mock_collection()
        col.find_one.return_value = None
        repo = UserRepository(col)

        result = repo.get(999)
        assert result is None
        col.find_one.assert_called_once_with({"telegram_user_id": 999})

    def test_get_returns_profile(self):
        col = _make_mock_collection()
        col.find_one.return_value = {
            "_id": "test@test.com",
            "telegram_user_id": 123,
            "timezone": "Asia/Jerusalem",
        }
        repo = UserRepository(col)

        result = repo.get(123)
        assert result is not None
        assert result.telegram_user_id == 123
        assert result.email == "test@test.com"
        assert result.timezone == "Asia/Jerusalem"

    def test_get_by_email(self):
        col = _make_mock_collection()
        col.find_one.return_value = {
            "_id": "test@test.com",
            "telegram_user_id": 123,
        }
        repo = UserRepository(col)

        result = repo.get_by_email("test@test.com")
        assert result is not None
        assert result.email == "test@test.com"
        col.find_one.assert_called_once_with({"_id": "test@test.com"})

    def test_save_does_upsert(self):
        col = _make_mock_collection()
        repo = UserRepository(col)
        profile = _make_profile(123)

        repo.save(profile)
        col.replace_one.assert_called_once()
        args, kwargs = col.replace_one.call_args
        assert args[0] == {"_id": "test@test.com"}
        assert kwargs["upsert"] is True

    def test_update_fields_by_telegram_id(self):
        col = _make_mock_collection()
        repo = UserRepository(col)

        repo.update_fields(123, {"name": "שי"})
        col.update_one.assert_called_once()
        args = col.update_one.call_args[0]
        assert args[0] == {"telegram_user_id": 123}
        assert "name" in args[1]["$set"]
        assert "updated_at" in args[1]["$set"]

    def test_update_fields_by_email(self):
        col = _make_mock_collection()
        repo = UserRepository(col)

        repo.update_fields_by_email("test@test.com", {"name": "שי"})
        col.update_one.assert_called_once()
        args = col.update_one.call_args[0]
        assert args[0] == {"_id": "test@test.com"}
        assert "name" in args[1]["$set"]
        assert "updated_at" in args[1]["$set"]

    def test_get_by_signup_token_filters_correctly(self):
        col = _make_mock_collection()
        col.find_one.return_value = {
            "_id": "test@test.com",
            "telegram_user_id": 123,
            "signup_session_token": FAKE_OID,
        }
        repo = UserRepository(col)

        result = repo.get_by_signup_token(FAKE_OID)
        assert result is not None
        call_filter = col.find_one.call_args[0][0]
        assert call_filter["signup_session_token"] == FAKE_OID
        assert "$gt" in call_filter["signup_session_token_expires_at"]

    def test_get_by_signup_token_returns_none_when_not_found(self):
        col = _make_mock_collection()
        col.find_one.return_value = None
        repo = UserRepository(col)

        result = repo.get_by_signup_token("nonexistent")
        assert result is None

    def test_increment_tokens_uses_inc_operator(self):
        col = _make_mock_collection()
        repo = UserRepository(col)

        repo.increment_tokens(123, "gpt-4o-mini", 500, 200)
        col.update_one.assert_called_once()
        args = col.update_one.call_args[0]
        assert args[0] == {"telegram_user_id": 123}
        assert args[1] == {"$inc": {
            "tokens_used.gpt-4o-mini.prompt": 500,
            "tokens_used.gpt-4o-mini.completion": 200,
        }}

    def test_increment_tokens_skips_when_zero(self):
        col = _make_mock_collection()
        repo = UserRepository(col)

        repo.increment_tokens(123, "gpt-4o", 0, 0)
        col.update_one.assert_not_called()

    def test_increment_tokens_allows_partial_zero(self):
        col = _make_mock_collection()
        repo = UserRepository(col)

        repo.increment_tokens(123, "gpt-4o", 100, 0)
        col.update_one.assert_called_once()


# ---------------------------------------------------------------------------
# FoodRepository
# ---------------------------------------------------------------------------

class TestFoodRepository:
    def test_add_returns_entry_with_id(self):
        col = _make_mock_collection()
        col.insert_one.return_value = MagicMock(inserted_id=FAKE_OID)
        repo = FoodRepository(col)

        entry = _make_food_entry()
        result = repo.add(entry)
        assert result.id == FAKE_OID
        col.insert_one.assert_called_once()

    def test_get_by_id(self):
        col = _make_mock_collection()
        col.find_one.return_value = {
            "_id": FAKE_OID,
            "telegram_user_id": 123,
            "date": "05/05/2026",
            "time": "14:30",
            "description": "test",
            "calories": 500,
            "protein": 30,
            "within_window": True,
        }
        repo = FoodRepository(col)

        result = repo.get(FAKE_OID)
        assert result is not None
        assert result.calories == 500

    def test_get_returns_none_when_missing(self):
        col = _make_mock_collection()
        col.find_one.return_value = None
        repo = FoodRepository(col)

        result = repo.get(FAKE_OID_2)
        assert result is None

    def test_update(self):
        col = _make_mock_collection()
        repo = FoodRepository(col)

        repo.update(FAKE_OID, {"calories": 600})
        col.update_one.assert_called_once()

    def test_delete(self):
        col = _make_mock_collection()
        repo = FoodRepository(col)

        repo.delete(FAKE_OID)
        col.delete_one.assert_called_once()

    def test_get_by_user_and_dates(self):
        col = _make_mock_collection()
        col.find.return_value = [
            {
                "_id": FAKE_OID,
                "telegram_user_id": 123,
                "date": "05/05/2026",
                "time": "14:30",
                "description": "meal",
                "calories": 500,
                "protein": 30,
                "within_window": True,
            },
        ]
        repo = FoodRepository(col)

        results = repo.get_by_user_and_dates(123, ["05/05/2026"])
        assert len(results) == 1
        call_filter = col.find.call_args[0][0]
        assert call_filter["telegram_user_id"] == 123
        assert call_filter["date"] == {"$in": ["05/05/2026"]}

    def test_get_all_for_user(self):
        col = _make_mock_collection()
        col.find.return_value = []
        repo = FoodRepository(col)

        results = repo.get_all_for_user(123)
        assert results == []
        call_filter = col.find.call_args[0][0]
        assert call_filter["telegram_user_id"] == 123


class TestFoodRepositoryMultiUserIsolation:
    """Two users with entries on the same date must not mix."""

    def test_query_for_user_a_excludes_user_b(self):
        col = _make_mock_collection()
        user_a_entry = {
            "_id": FAKE_OID,
            "telegram_user_id": 111,
            "date": "05/05/2026",
            "time": "12:00",
            "description": "user A meal",
            "calories": 400,
            "protein": 20,
            "within_window": True,
        }
        col.find.return_value = [user_a_entry]
        repo = FoodRepository(col)

        results = repo.get_by_user_and_dates(111, ["05/05/2026"])
        assert len(results) == 1
        assert results[0].description == "user A meal"

        call_filter = col.find.call_args[0][0]
        assert call_filter["telegram_user_id"] == 111


# ---------------------------------------------------------------------------
# WeeklyFeedbackRepository
# ---------------------------------------------------------------------------

class TestWeeklyFeedbackRepository:
    def test_save_inserts(self):
        col = _make_mock_collection()
        repo = WeeklyFeedbackRepository(col)

        repo.save(123, "05/05/2026", "Great week!", {"calories_avg": 2000})
        col.insert_one.assert_called_once()
        doc = col.insert_one.call_args[0][0]
        assert doc["telegram_user_id"] == 123
        assert doc["feedback_text"] == "Great week!"

    def test_get_recent_returns_sorted_limited(self):
        col = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.__iter__ = lambda self: iter([
            {"telegram_user_id": 123, "feedback_text": "fb1"},
        ])
        col.find.return_value = mock_cursor
        repo = WeeklyFeedbackRepository(col)

        results = repo.get_recent(123, limit=3)
        assert len(results) == 1
        col.find.assert_called_once_with({"telegram_user_id": 123})
        mock_cursor.sort.assert_called_once_with("created_at", -1)
        mock_cursor.limit.assert_called_once_with(3)


# ---------------------------------------------------------------------------
# ErrorRepository
# ---------------------------------------------------------------------------

class TestErrorRepository:
    def test_creates_ttl_index(self):
        col = _make_mock_collection()
        repo = ErrorRepository(col)
        col.create_index.assert_called_once_with(
            "timestamp",
            expireAfterSeconds=30 * 24 * 60 * 60,
        )

    def test_log_inserts_with_correct_fields(self):
        col = _make_mock_collection()
        repo = ErrorRepository(col)

        error = ValueError("test error")
        repo.log(error, "handle_message", 123, "hello", 456)

        col.insert_one.assert_called_once()
        doc = col.insert_one.call_args[0][0]
        assert doc["error_type"] == "ValueError"
        assert doc["error_message"] == "test error"
        assert doc["handler"] == "handle_message"
        assert doc["telegram_user_id"] == 123
        assert doc["message_text"] == "hello"
        assert doc["update_id"] == 456
        assert "timestamp" in doc
        assert "traceback" in doc


# ---------------------------------------------------------------------------
# FoodRepository - cleanup_expired_edits
# ---------------------------------------------------------------------------

class TestFoodRepositoryCleanup:
    def test_cleanup_expired_edits_unsets_fields(self):
        col = _make_mock_collection()
        col.update_many.return_value = MagicMock(modified_count=3)
        from repositories.food_repository import FoodRepository
        repo = FoodRepository(col)

        result = repo.cleanup_expired_edits()

        assert result == 3
        col.update_many.assert_called_once()
        call_args = col.update_many.call_args
        query = call_args[0][0]
        update = call_args[0][1]
        assert "edit_expires_at" in query
        assert "$unset" in update
        unset_fields = update["$unset"]
        assert "original_description" in unset_fields
        assert "original_calories" in unset_fields
        assert "original_protein" in unset_fields
        assert "correction_history" in unset_fields
        assert "photo_file_id" in unset_fields
        assert "edit_expires_at" in unset_fields

    def test_cleanup_returns_zero_when_nothing_expired(self):
        col = _make_mock_collection()
        col.update_many.return_value = MagicMock(modified_count=0)
        from repositories.food_repository import FoodRepository
        repo = FoodRepository(col)

        result = repo.cleanup_expired_edits()
        assert result == 0


# ---------------------------------------------------------------------------
# TokenLogRepository
# ---------------------------------------------------------------------------

class TestTokenLogRepository:
    def test_log_upserts_with_inc(self):
        col = _make_mock_collection()
        repo = TokenLogRepository(col)

        repo.log(123, "gpt-4o-mini", "2026-06-07", 500, 200)
        col.update_one.assert_called_once()
        args, kwargs = col.update_one.call_args
        assert args[0] == {"telegram_user_id": 123, "model": "gpt-4o-mini", "date": "2026-06-07"}
        assert args[1] == {"$inc": {"prompt_tokens": 500, "completion_tokens": 200}}
        assert kwargs["upsert"] is True

    def test_log_skips_when_zero(self):
        col = _make_mock_collection()
        repo = TokenLogRepository(col)

        repo.log(123, "gpt-4o", "2026-06-07", 0, 0)
        col.update_one.assert_not_called()

    def test_get_usage_aggregates_by_date_and_model(self):
        col = _make_mock_collection()
        col.aggregate.return_value = [
            {"_id": {"date": "2026-06-06", "model": "gpt-4o-mini"}, "prompt_tokens": 1000, "completion_tokens": 400},
            {"_id": {"date": "2026-06-07", "model": "gpt-4o"}, "prompt_tokens": 500, "completion_tokens": 300},
        ]
        repo = TokenLogRepository(col)

        results = repo.get_usage("2026-06-01", "2026-06-07")
        assert len(results) == 2
        assert results[0] == {"date": "2026-06-06", "model": "gpt-4o-mini", "prompt_tokens": 1000, "completion_tokens": 400}
        assert results[1] == {"date": "2026-06-07", "model": "gpt-4o", "prompt_tokens": 500, "completion_tokens": 300}

    def test_get_totals_sums_by_model(self):
        col = _make_mock_collection()
        col.aggregate.return_value = [
            {"_id": "gpt-4o", "prompt_tokens": 2000, "completion_tokens": 1000},
            {"_id": "gpt-4o-mini", "prompt_tokens": 8000, "completion_tokens": 4000},
        ]
        repo = TokenLogRepository(col)

        result = repo.get_totals("2026-06-01", "2026-06-07")
        assert result == {
            "gpt-4o": {"prompt_tokens": 2000, "completion_tokens": 1000},
            "gpt-4o-mini": {"prompt_tokens": 8000, "completion_tokens": 4000},
        }

    def test_creates_indexes(self):
        col = _make_mock_collection()
        TokenLogRepository(col)
        assert col.create_index.call_count == 2
