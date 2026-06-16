"""
habit_service.py — לוגיקת תיעוד שינה/אימון/משהו-לעצמי.

נשען על ה-repositories של ההרגלים. לא יודע על טלגרם.

תלוי ב: repositories (sleep, workout, self_care), models.
נצרך על ידי: services/message_router_service, handlers.
"""

from __future__ import annotations

from datetime import datetime

from models.sleep import SleepLog
from models.workout import WorkoutLog
from models.self_care import SelfCareLog
from repositories.sleep_repository import SleepRepository
from repositories.workout_repository import WorkoutRepository
from repositories.self_care_repository import SelfCareRepository


class HabitService:
    def __init__(
        self,
        sleep_repo: SleepRepository,
        workout_repo: WorkoutRepository,
        self_care_repo: SelfCareRepository,
    ):
        self._sleep_repo = sleep_repo
        self._workout_repo = workout_repo
        self._self_care_repo = self_care_repo

    def log_sleep(self, telegram_user_id: int, sleep_time: str, date: str) -> SleepLog:
        log = SleepLog(
            telegram_user_id=telegram_user_id,
            date=date,
            sleep_time=sleep_time,
        )
        return self._sleep_repo.add(log)

    def log_workout(self, telegram_user_id: int, date: str, note: str | None = None) -> WorkoutLog:
        log = WorkoutLog(
            telegram_user_id=telegram_user_id,
            date=date,
            note=note,
        )
        return self._workout_repo.add(log)

    def log_self_care(self, telegram_user_id: int, description: str, date: str) -> SelfCareLog:
        log = SelfCareLog(
            telegram_user_id=telegram_user_id,
            date=date,
            description=description,
        )
        return self._self_care_repo.add(log)

    def weekly_workout_count(self, telegram_user_id: int, week_dates: list[str]) -> int:
        return self._workout_repo.count_for_week(telegram_user_id, week_dates)
