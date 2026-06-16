"""
test_repository_move - TDD tests for move() on all repositories.

Expected behavior:
- FoodRepository.move() updates date, optionally time and within_window
- SleepRepository.move() updates date, optionally sleep_time
- WorkoutRepository.move() updates date
- SelfCareRepository.move() updates date and recomputes week_id
- All move() methods use $set via update_one
"""

import sys
from unittest.mock import MagicMock

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from bson import ObjectId


class TestFoodRepositoryMove:
    def test_move_date_only(self):
        from repositories.food_repository import FoodRepository

        col = MagicMock()
        repo = FoodRepository(col)
        repo.move("aabbccdd" * 3, "15/06/2026")
        col.update_one.assert_called_once()
        args = col.update_one.call_args
        assert args[0][1] == {"$set": {"date": "15/06/2026"}}

    def test_move_date_and_time(self):
        from repositories.food_repository import FoodRepository

        col = MagicMock()
        repo = FoodRepository(col)
        repo.move("aabbccdd" * 3, "15/06/2026", new_time="20:00")
        args = col.update_one.call_args
        assert args[0][1]["$set"]["date"] == "15/06/2026"
        assert args[0][1]["$set"]["time"] == "20:00"

    def test_move_with_within_window(self):
        from repositories.food_repository import FoodRepository

        col = MagicMock()
        repo = FoodRepository(col)
        repo.move("aabbccdd" * 3, "15/06/2026", within_window=False)
        args = col.update_one.call_args
        assert args[0][1]["$set"]["within_window"] is False


class TestSleepRepositoryMove:
    def test_move_date_only(self):
        from repositories.sleep_repository import SleepRepository

        col = MagicMock()
        repo = SleepRepository(col)
        repo.move("aabbccdd" * 3, "15/06/2026")
        col.update_one.assert_called_once()
        args = col.update_one.call_args
        assert args[0][1] == {"$set": {"date": "15/06/2026"}}

    def test_move_date_and_time(self):
        from repositories.sleep_repository import SleepRepository

        col = MagicMock()
        repo = SleepRepository(col)
        repo.move("aabbccdd" * 3, "15/06/2026", new_sleep_time="23:30")
        args = col.update_one.call_args
        assert args[0][1]["$set"]["sleep_time"] == "23:30"


class TestWorkoutRepositoryMove:
    def test_move_date(self):
        from repositories.workout_repository import WorkoutRepository

        col = MagicMock()
        repo = WorkoutRepository(col)
        repo.move("aabbccdd" * 3, "15/06/2026")
        col.update_one.assert_called_once()
        args = col.update_one.call_args
        assert args[0][1] == {"$set": {"date": "15/06/2026"}}


class TestSelfCareRepositoryMove:
    def test_move_recomputes_week_id(self):
        from repositories.self_care_repository import SelfCareRepository

        col = MagicMock()
        repo = SelfCareRepository(col)
        repo.move("aabbccdd" * 3, "16/06/2026")
        col.update_one.assert_called_once()
        args = col.update_one.call_args
        fields = args[0][1]["$set"]
        assert fields["date"] == "16/06/2026"
        assert fields["week_id"] == "2026-W25"
