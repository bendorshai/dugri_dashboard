"""
test_phase3 — TDD tests for Phase 3: habits, classifier, routing.
"""

import sys
from unittest.mock import MagicMock

import pytest

for mod in [
    "telegram", "telegram.ext",
    "pymongo", "openai",
]:
    sys.modules.setdefault(mod, MagicMock())

from models.sleep import SleepLog
from models.workout import WorkoutLog
from models.self_care import SelfCareLog
from services.habit_service import HabitService
from services.message_router_service import MessageRouterService
from repositories.sleep_repository import SleepRepository
from repositories.workout_repository import WorkoutRepository
from repositories.self_care_repository import SelfCareRepository
from analyzer import MessageClassification, FoodAnalysisResult, FoodItem, TimedFoodGroup, TimedFoodAnalysisResult


# ---------------------------------------------------------------------------
# HabitService
# ---------------------------------------------------------------------------

class TestHabitService:
    def _make_service(self):
        sleep_repo = MagicMock(spec=SleepRepository)
        workout_repo = MagicMock(spec=WorkoutRepository)
        self_care_repo = MagicMock(spec=SelfCareRepository)

        sleep_repo.add.side_effect = lambda log: log
        workout_repo.add.side_effect = lambda log: log
        self_care_repo.add.side_effect = lambda log: log

        svc = HabitService(sleep_repo, workout_repo, self_care_repo)
        return svc, sleep_repo, workout_repo, self_care_repo

    def test_log_sleep(self):
        svc, sleep_repo, _, _ = self._make_service()
        result = svc.log_sleep(123, "23:30", "05/05/2026")
        sleep_repo.add.assert_called_once()
        assert result.sleep_time == "23:30"

    def test_log_workout(self):
        svc, _, workout_repo, _ = self._make_service()
        result = svc.log_workout(123, "05/05/2026", note="ריצה")
        workout_repo.add.assert_called_once()
        assert result.note == "ריצה"

    def test_log_self_care(self):
        svc, _, _, self_care_repo = self._make_service()
        result = svc.log_self_care(123, "הלכתי לים", "2026-W21")
        self_care_repo.add.assert_called_once()
        assert result.description == "הלכתי לים"

    def test_weekly_workout_count(self):
        svc, _, workout_repo, _ = self._make_service()
        workout_repo.count_for_week.return_value = 3
        count = svc.weekly_workout_count(123, ["05/05/2026", "06/05/2026"])
        assert count == 3
        workout_repo.count_for_week.assert_called_once_with(123, ["05/05/2026", "06/05/2026"])


# ---------------------------------------------------------------------------
# MessageRouterService
# ---------------------------------------------------------------------------

class TestMessageRouterService:
    def _make_router(self):
        habit = MagicMock(spec=HabitService)
        qa = MagicMock()
        help_svc = MagicMock()
        router = MessageRouterService(habit, qa, help_svc)
        return router, habit, qa, help_svc

    def test_route_sleep(self):
        router, habit, _, _ = self._make_router()
        result = router.route_sleep(123, "23:30", "05/05/2026")
        habit.log_sleep.assert_called_once_with(123, "23:30", "05/05/2026")
        assert "23:30" in result.response_text
        assert result.light_confirmation is True

    def test_route_workout(self):
        router, habit, _, _ = self._make_router()
        result = router.route_workout(123, "05/05/2026")
        habit.log_workout.assert_called_once()
        assert result.light_confirmation is True

    def test_route_self_care(self):
        router, habit, _, _ = self._make_router()
        result = router.route_self_care(123, "הלכתי לים", "2026-W21")
        habit.log_self_care.assert_called_once()
        assert "משהו לעצמי" in result.response_text

    def test_route_help(self):
        router, _, _, help_svc = self._make_router()
        help_svc.answer.return_value = "דוגרי מחשב קלוריות..."
        result = router.route_help("איך אתה עובד?")
        help_svc.answer.assert_called_once_with("איך אתה עובד?")
        assert result.response_text == "דוגרי מחשב קלוריות..."

    def test_route_answer_question(self):
        router, _, qa, _ = self._make_router()
        qa.answer.return_value = "אכלת 12000 קלוריות"
        result = router.route_answer_question(123, "כמה אכלתי?", "05/05/2026", 2000, 150)
        qa.answer.assert_called_once()
        assert "12000" in result.response_text

    def test_route_feedback_request_is_placeholder(self):
        router, _, _, _ = self._make_router()
        result = router.route_feedback_request()
        assert "בקרוב" in result.response_text or "תפריט" in result.response_text

    def test_route_none(self):
        router, _, _, _ = self._make_router()
        result = router.route_none()
        assert "לא הבנתי" in result.response_text


# ---------------------------------------------------------------------------
# MessageClassification model
# ---------------------------------------------------------------------------

class TestMessageClassification:
    def test_meal_classification(self):
        mc = MessageClassification(
            type="meal",
            meal=TimedFoodAnalysisResult(groups=[
                TimedFoodGroup(
                    temporal_label="עכשיו",
                    date="05/06/2026",
                    time="13:00",
                    items=[FoodItem(description="שניצל", estimated_grams=200, calories=400, protein=30)],
                    total_calories=400,
                    total_protein=30,
                ),
            ]),
        )
        assert mc.type == "meal"
        assert mc.meal.groups[0].total_calories == 400

    def test_sleep_classification(self):
        mc = MessageClassification(type="sleep", sleep_time="23:30")
        assert mc.type == "sleep"
        assert mc.sleep_time == "23:30"

    def test_none_classification(self):
        mc = MessageClassification(type="none")
        assert mc.type == "none"

    def test_help_classification(self):
        mc = MessageClassification(type="help", question_text="איך אתה עובד?")
        assert mc.type == "help"
        assert mc.question_text == "איך אתה עובד?"


# ---------------------------------------------------------------------------
# Habit repos
# ---------------------------------------------------------------------------

class TestHabitRepos:
    def test_sleep_repo_add(self):
        col = MagicMock()
        col.insert_one.return_value = MagicMock(inserted_id="abc")
        repo = SleepRepository(col)
        log = SleepLog(telegram_user_id=123, date="05/05/2026", sleep_time="23:30")
        result = repo.add(log)
        col.insert_one.assert_called_once()

    def test_workout_repo_count_for_week(self):
        col = MagicMock()
        col.count_documents.return_value = 2
        repo = WorkoutRepository(col)
        count = repo.count_for_week(123, ["05/05/2026"])
        assert count == 2
        call_filter = col.count_documents.call_args[0][0]
        assert call_filter["telegram_user_id"] == 123

    def test_self_care_repo_get_for_week(self):
        col = MagicMock()
        col.find.return_value = [
            {"_id": "x", "telegram_user_id": 123, "week_id": "2026-W21",
             "description": "ים", "created_at": "2026-05-21T00:00:00"},
        ]
        repo = SelfCareRepository(col)
        results = repo.get_for_week(123, "2026-W21")
        assert len(results) == 1
