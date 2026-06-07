"""
emotional_support_service.py - empathy responses and ChatGPT handoff.

Dugri is not a therapist. When users share emotions, this service provides
brief validation and optionally builds a personalized ChatGPT prompt with
the user's habit context from the last 7 days.

Depends on: repositories (food, sleep, workout, self_care, user), messages.
Used by: handlers/base.py.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import messages as M
from repositories.food_repository import FoodRepository
from repositories.sleep_repository import SleepRepository
from repositories.workout_repository import WorkoutRepository
from repositories.self_care_repository import SelfCareRepository
from repositories.user_repository import UserRepository


class EmotionalSupportService:
    def __init__(
        self,
        food_repo: FoodRepository,
        sleep_repo: SleepRepository,
        workout_repo: WorkoutRepository,
        self_care_repo: SelfCareRepository,
        user_repo: UserRepository,
    ):
        self._food_repo = food_repo
        self._sleep_repo = sleep_repo
        self._workout_repo = workout_repo
        self._self_care_repo = self_care_repo
        self._user_repo = user_repo

    def get_empathy_response(self) -> str:
        return random.choice(M.EMOTIONAL_EMPATHY_STANDALONE)

    def get_inline_empathy(self) -> str:
        return random.choice(M.EMOTIONAL_EMPATHY_INLINE)

    def get_offer_text(self) -> str:
        return M.EMOTIONAL_CHATGPT_OFFER

    def build_chatgpt_prompt(self, telegram_user_id: int, user_message: str) -> str:
        habit_summary = self._build_habit_summary(telegram_user_id)
        return M.EMOTIONAL_CHATGPT_PROMPT_TEMPLATE.format(
            habit_summary=habit_summary,
            user_message=user_message,
        )

    def _build_habit_summary(self, telegram_user_id: int) -> str:
        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]

        lines = []

        # Food
        food_entries = self._food_repo.get_by_user_and_dates(telegram_user_id, dates)
        if food_entries:
            total_cal = sum(getattr(e, "calories", 0) or 0 for e in food_entries)
            total_prot = sum(getattr(e, "protein", 0) or 0 for e in food_entries)
            days_with_food = len({e.date for e in food_entries})
            if days_with_food > 0:
                avg_cal = total_cal // days_with_food
                avg_prot = total_prot // days_with_food
                lines.append(f"תזונה: {days_with_food} ימי תיעוד, ממוצע {avg_cal} קלוריות ו-{avg_prot} גרם חלבון ליום")

        # Sleep
        sleep_logs = self._sleep_repo.get_recent(telegram_user_id, limit=7)
        if sleep_logs:
            lines.append(f"שינה: {len(sleep_logs)} דיווחים בשבוע האחרון")

        # Workouts
        workout_logs = self._workout_repo.get_recent(telegram_user_id, limit=7)
        if workout_logs:
            lines.append(f"אימונים: {len(workout_logs)} בשבוע האחרון")

        # Self-care
        self_care_logs = self._self_care_repo.get_recent(telegram_user_id, limit=7)
        if self_care_logs:
            lines.append(f"משהו לעצמי: {len(self_care_logs)} פעילויות בשבוע האחרון")

        if not lines:
            return "אין נתוני הרגלים מהשבוע האחרון."

        return "\n".join(lines)
