"""
test_weekly_summary — TDD tests for the enhanced weekly summary.

Tests the proactive offer path and the preserve-improve-preserve structure.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from models.profile import User, ToggleState, Toggles
from services.feedback_service import FeedbackService
from repositories.food_repository import FoodRepository
from repositories.user_repository import UserRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from analyzer import FoodAnalyzer, MessageClassification


def _make_feedback_service():
    analyzer = MagicMock(spec=FoodAnalyzer)
    food_repo = MagicMock(spec=FoodRepository)
    user_repo = MagicMock(spec=UserRepository)
    feedback_repo = MagicMock(spec=WeeklyFeedbackRepository)
    svc = FeedbackService(analyzer, food_repo, user_repo, feedback_repo)
    return svc, analyzer, food_repo, user_repo, feedback_repo


class TestClassifierToggleTypes:
    def test_toggle_cancel_type_exists(self):
        mc = MessageClassification(type="toggle_cancel", toggle_name="weekly_summary")
        assert mc.type == "toggle_cancel"
        assert mc.toggle_name == "weekly_summary"

    def test_toggle_activate_type_exists(self):
        mc = MessageClassification(type="toggle_activate", toggle_name="sleep")
        assert mc.type == "toggle_activate"
        assert mc.toggle_name == "sleep"

    def test_toggle_name_can_be_none(self):
        mc = MessageClassification(type="meal")
        assert mc.toggle_name is None


class TestFeedbackServiceShouldOfferWeekly:
    def test_should_offer_when_never_offered(self):
        svc, _, _, _, _ = _make_feedback_service()
        assert svc.should_offer_weekly(None, datetime.now(timezone.utc)) is True

    def test_should_offer_after_7_days(self):
        svc, _, _, _, _ = _make_feedback_service()
        last = datetime.now(timezone.utc) - timedelta(days=8)
        assert svc.should_offer_weekly(last, datetime.now(timezone.utc)) is True

    def test_should_not_offer_before_7_days(self):
        svc, _, _, _, _ = _make_feedback_service()
        last = datetime.now(timezone.utc) - timedelta(days=3)
        assert svc.should_offer_weekly(last, datetime.now(timezone.utc)) is False


class TestFeedbackServiceNoData:
    def test_returns_no_data_message(self):
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        food_repo.get_by_user_and_dates.return_value = []
        feedback_repo.get_recent.return_value = []

        result = svc.give_feedback(123, "22/05/2026", 2000, 150, None, True)
        assert "אין נתונים" in result
