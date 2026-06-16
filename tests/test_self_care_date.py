"""
test_self_care_date — TDD tests for SelfCareLog date field.

Expected behavior:
- SelfCareLog with date auto-computes week_id
- Backward compat: old docs with week_id but no date still deserialize
- Date validation matches DD/MM/YYYY format
- compute_week_id utility converts DD/MM/YYYY to YYYY-WXX
- Service chain passes date (not week_id) through to model
- Repository get_for_date queries by date
"""

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from models.self_care import SelfCareLog, compute_week_id


class TestComputeWeekId:
    def test_basic(self):
        assert compute_week_id("16/06/2026") == "2026-W25"

    def test_start_of_year(self):
        # Jan 1 2026 is a Thursday -> ISO week 1
        assert compute_week_id("01/01/2026") == "2026-W01"

    def test_end_of_year(self):
        # Dec 31 2025 is a Wednesday -> ISO week 1 of 2026
        assert compute_week_id("31/12/2025") == "2026-W01"


class TestSelfCareLogDate:
    def test_date_auto_computes_week_id(self):
        log = SelfCareLog(
            telegram_user_id=123,
            date="16/06/2026",
            description="הלכתי לים",
        )
        assert log.date == "16/06/2026"
        assert log.week_id == "2026-W25"

    def test_backward_compat_week_id_only(self):
        """Old documents with week_id but no date still deserialize."""
        log = SelfCareLog(
            telegram_user_id=123,
            week_id="2026-W21",
            description="קראתי ספר",
        )
        assert log.week_id == "2026-W21"
        assert log.date is None

    def test_explicit_week_id_not_overridden(self):
        """If both date and week_id provided, week_id is kept as-is."""
        log = SelfCareLog(
            telegram_user_id=123,
            date="16/06/2026",
            week_id="2026-W99",
            description="test",
        )
        assert log.week_id == "2026-W99"

    def test_date_validation_rejects_bad_format(self):
        with pytest.raises(ValueError):
            SelfCareLog(
                telegram_user_id=123,
                date="2026-06-16",
                description="bad",
            )

    def test_date_validation_accepts_good_format(self):
        log = SelfCareLog(
            telegram_user_id=123,
            date="01/01/2026",
            description="ok",
        )
        assert log.date == "01/01/2026"

    def test_to_mongo_and_back_with_date(self):
        log = SelfCareLog(
            telegram_user_id=123,
            date="16/06/2026",
            description="הלכתי לים",
        )
        doc = log.to_mongo_dict()
        assert doc["date"] == "16/06/2026"
        assert doc["week_id"] == "2026-W25"

        restored = SelfCareLog.from_mongo_dict(doc)
        assert restored.date == "16/06/2026"
        assert restored.week_id == "2026-W25"

    def test_to_mongo_and_back_legacy_no_date(self):
        """Legacy docs in MongoDB have week_id but no date field."""
        doc = {
            "telegram_user_id": 123,
            "week_id": "2026-W21",
            "description": "קראתי ספר",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        log = SelfCareLog.from_mongo_dict(doc)
        assert log.week_id == "2026-W21"
        assert log.date is None


class TestHabitServiceSelfCare:
    def test_log_self_care_with_date(self):
        from services.habit_service import HabitService

        mock_repo = MagicMock()
        mock_repo.add.side_effect = lambda log: log
        svc = HabitService(
            sleep_repo=MagicMock(),
            workout_repo=MagicMock(),
            self_care_repo=mock_repo,
        )
        result = svc.log_self_care(123, "הלכתי לים", "16/06/2026")
        assert result.date == "16/06/2026"
        assert result.week_id == "2026-W25"


class TestMessageRouterSelfCare:
    def test_route_self_care_passes_date(self):
        from services.message_router_service import MessageRouterService

        habit = MagicMock()
        habit.log_self_care.return_value = MagicMock(id="abc123")
        router = MessageRouterService(habit, MagicMock(), MagicMock())
        result = router.route_self_care(123, "הלכתי לים", "16/06/2026")
        habit.log_self_care.assert_called_once_with(123, "הלכתי לים", "16/06/2026")
        assert result.light_confirmation


class TestSelfCareRepositoryDate:
    def test_get_for_date(self):
        from repositories.self_care_repository import SelfCareRepository

        mock_collection = MagicMock()
        mock_collection.find.return_value = []
        repo = SelfCareRepository(mock_collection)
        repo.get_for_date(123, "16/06/2026")
        mock_collection.find.assert_called_once_with({
            "telegram_user_id": 123,
            "date": "16/06/2026",
        })
