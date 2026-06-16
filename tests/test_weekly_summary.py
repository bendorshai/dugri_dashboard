"""
test_weekly_summary - TDD tests for the enhanced weekly summary.

Tests the proactive offer path and the all-habit feedback structure.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from models.profile import User, Targets, ToggleState, Toggles, EatingWindow
from services.feedback_service import FeedbackService
from repositories.food_repository import FoodRepository
from repositories.user_repository import UserRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from repositories.sleep_repository import SleepRepository
from repositories.workout_repository import WorkoutRepository
from repositories.self_care_repository import SelfCareRepository
from analyzer import FoodAnalyzer


def _make_profile(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123, "targets": Targets(calories=2000, protein=150)}
    defaults.update(kwargs)
    return User(**defaults)


def _make_feedback_service():
    analyzer = MagicMock(spec=FoodAnalyzer)
    food_repo = MagicMock(spec=FoodRepository)
    user_repo = MagicMock(spec=UserRepository)
    feedback_repo = MagicMock(spec=WeeklyFeedbackRepository)
    sleep_repo = MagicMock(spec=SleepRepository)
    workout_repo = MagicMock(spec=WorkoutRepository)
    self_care_repo = MagicMock(spec=SelfCareRepository)
    sleep_repo.get_recent.return_value = []
    workout_repo.get_recent.return_value = []
    self_care_repo.get_recent.return_value = []
    svc = FeedbackService(analyzer, food_repo, user_repo, feedback_repo,
                          sleep_repo, workout_repo, self_care_repo)
    return svc, analyzer, food_repo, user_repo, feedback_repo



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
        profile = _make_profile()

        result = svc.give_feedback(123, "22/05/2026", profile, True)
        assert "אין נתונים" in result


class TestFeedbackGreeting:
    """Greeting is prepended to feedback when user has both name and gender."""

    def _run_feedback(self, name=None, gender=None):
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        from models.food import FoodEntry
        food_repo.get_by_user_and_dates.return_value = [
            FoodEntry(telegram_user_id=123, date="05/06/2026", time="08:00",
                      description="ביצים", calories=300, protein=25),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {
            "feedback_text": "הכל טוב", "discovered_pattern": None, "pattern_summary": None,
        }
        profile = _make_profile(name=name, gender=gender)
        return svc.give_feedback(123, "05/06/2026", profile, False)

    def test_greeting_with_name_and_male(self):
        result = self._run_feedback(name="שי", gender="male")
        # Should have greeting before the feedback text
        import messages as M
        assert any(g.format(name="שי") in result for g in M.FEEDBACK_GREETING_MALE)

    def test_greeting_with_name_and_female(self):
        result = self._run_feedback(name="דנה", gender="female")
        import messages as M
        assert any(g.format(name="דנה") in result for g in M.FEEDBACK_GREETING_FEMALE)

    def test_no_greeting_without_name(self):
        result = self._run_feedback(name=None, gender="male")
        # Should start with 💬 directly into feedback text
        assert result.startswith("💬 הכל טוב")

    def test_no_greeting_without_gender(self):
        result = self._run_feedback(name="שי", gender=None)
        assert result.startswith("💬 הכל טוב")

    def test_no_greeting_without_both(self):
        result = self._run_feedback(name=None, gender=None)
        assert result.startswith("💬 הכל טוב")


class TestFeedbackPreComputation:
    """Verify that give_feedback pre-computes stats in Python
    and passes them (not raw CSV) to the analyzer."""

    def _make_entry(self, date, time, desc, cal, prot, within_window=True):
        from models.food import FoodEntry
        return FoodEntry(
            telegram_user_id=123, date=date, time=time,
            description=desc, calories=cal, protein=prot,
            within_window=within_window,
        )

    def test_month_stats_structure(self):
        """Verify month_stats has all required sections."""
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        food_repo.get_by_user_and_dates.return_value = [
            self._make_entry("05/06/2026", "08:00", "ביצים", 300, 25),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {
            "feedback_text": "ok", "discovered_pattern": None, "pattern_summary": None,
        }
        profile = _make_profile()

        svc.give_feedback(123, "05/06/2026", profile, False)

        month_stats = analyzer.generate_weekly_feedback.call_args[0][0]
        assert "raw_entries" in month_stats
        assert "summaries" in month_stats
        assert "targets" in month_stats
        assert "active_toggles" in month_stats
        assert isinstance(month_stats["raw_entries"]["food"], list)

    def test_raw_food_entries_included(self):
        """Verify individual food entries are passed to GPT."""
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        food_repo.get_by_user_and_dates.return_value = [
            self._make_entry("05/06/2026", "08:00", "ביצים", 300, 25),
            self._make_entry("05/06/2026", "13:00", "שניצל", 700, 50),
            self._make_entry("04/06/2026", "12:00", "סלט", 400, 20),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {
            "feedback_text": "ok", "discovered_pattern": None, "pattern_summary": None,
        }
        profile = _make_profile()

        svc.give_feedback(123, "05/06/2026", profile, False)

        month_stats = analyzer.generate_weekly_feedback.call_args[0][0]
        food = month_stats["raw_entries"]["food"]
        assert len(food) == 3
        assert food[0]["description"] == "ביצים"
        assert food[0]["calories"] == 300

    def test_weekly_food_summaries(self):
        """Verify weekly food averages are pre-computed."""
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        food_repo.get_by_user_and_dates.return_value = [
            self._make_entry("05/06/2026", "08:00", "ביצים", 300, 25),
            self._make_entry("05/06/2026", "13:00", "שניצל", 700, 50),
            self._make_entry("04/06/2026", "12:00", "סלט", 400, 20),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {
            "feedback_text": "ok", "discovered_pattern": None, "pattern_summary": None,
        }
        profile = _make_profile()

        svc.give_feedback(123, "05/06/2026", profile, False)

        summaries = analyzer.generate_weekly_feedback.call_args[0][0]["summaries"]
        focus_week = summaries["food_weekly"][0]
        assert focus_week["days_tracked"] == 2
        assert focus_week["avg_calories"] == round((1000 + 400) / 2)
        assert focus_week["avg_protein"] == round((75 + 20) / 2)

    def test_targets_vs_percentage(self):
        """Verify cal and prot vs target percentages."""
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        food_repo.get_by_user_and_dates.return_value = [
            self._make_entry("05/06/2026", "12:00", "ארוחה", 1800, 120),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {
            "feedback_text": "ok", "discovered_pattern": None, "pattern_summary": None,
        }
        profile = _make_profile()

        svc.give_feedback(123, "05/06/2026", profile, False)

        summaries = analyzer.generate_weekly_feedback.call_args[0][0]["summaries"]
        assert summaries["focus_week_cal_pct"] == 90   # 1800/2000 * 100
        assert summaries["focus_week_prot_pct"] == 80   # 120/150 * 100

    def test_no_target_no_percentage(self):
        """No targets set -> no percentage keys in summaries."""
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        food_repo.get_by_user_and_dates.return_value = [
            self._make_entry("05/06/2026", "12:00", "ארוחה", 500, 30),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {
            "feedback_text": "ok", "discovered_pattern": None, "pattern_summary": None,
        }
        profile = _make_profile(targets=Targets())

        svc.give_feedback(123, "05/06/2026", profile, False)

        summaries = analyzer.generate_weekly_feedback.call_args[0][0]["summaries"]
        assert "focus_week_cal_pct" not in summaries
        assert "focus_week_prot_pct" not in summaries

    def test_eating_window_compliance_in_raw(self):
        """Eating window compliance is pre-computed per day."""
        svc, analyzer, food_repo, _, feedback_repo = _make_feedback_service()
        food_repo.get_by_user_and_dates.return_value = [
            self._make_entry("05/06/2026", "12:00", "ארוחה", 500, 30, within_window=True),
            self._make_entry("05/06/2026", "23:00", "חטיף", 200, 5, within_window=False),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {
            "feedback_text": "ok", "discovered_pattern": None, "pattern_summary": None,
        }
        profile = _make_profile(eating_window=EatingWindow(start="08:00", end="20:00"))

        svc.give_feedback(123, "05/06/2026", profile, False)

        raw = analyzer.generate_weekly_feedback.call_args[0][0]["raw_entries"]
        compliance = raw["eating_window_compliance"]
        assert len(compliance) == 1
        assert compliance[0]["date"] == "05/06/2026"
        assert compliance[0]["kept"] is False
