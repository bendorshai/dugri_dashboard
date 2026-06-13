"""
emotional_support_service.py - empathy responses and emotional CTA.

Dugri is not a therapist. When users share emotions, this service provides
brief validation and a CTA based on the configured mode:

- "creator" (default): refer user to Shai (Dugri's creator, a therapist)
  via a Telegram deep link.
- "chatgpt" (legacy, disabled by default): build a personalized ChatGPT
  prompt with the user's habit data from the last 7 days.

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

_MAX_FOOD_ENTRIES = 20


class EmotionalSupportService:
    def __init__(
        self,
        food_repo: FoodRepository,
        sleep_repo: SleepRepository,
        workout_repo: WorkoutRepository,
        self_care_repo: SelfCareRepository,
        user_repo: UserRepository,
        emotional_support_config: dict | None = None,
    ):
        self._food_repo = food_repo
        self._sleep_repo = sleep_repo
        self._workout_repo = workout_repo
        self._self_care_repo = self_care_repo
        self._user_repo = user_repo
        cfg = emotional_support_config or {}
        self.mode = cfg.get("mode", "creator")
        self.creator_username = cfg.get("creator_telegram_username", "DoorCore")

    def get_empathy_response(self) -> str:
        if self.mode == "creator":
            return random.choice(M.EMOTIONAL_EMPATHY_STANDALONE_CREATOR)
        return random.choice(M.EMOTIONAL_EMPATHY_STANDALONE)

    def get_inline_empathy(self) -> str:
        return random.choice(M.EMOTIONAL_EMPATHY_INLINE)

    # WARNING: This GPT prompt is horrible and must be thoroughly tested
    # if this option (emotional_support.mode = "chatgpt") is ever re-enabled.
    def build_chatgpt_prompt(self, telegram_user_id: int, user_message: str) -> str:
        detailed_entries = self._build_detailed_entries(telegram_user_id)
        return M.EMOTIONAL_CHATGPT_PROMPT_TEMPLATE.format(
            detailed_entries=detailed_entries,
            user_message=user_message,
        )

    def _build_detailed_entries(self, telegram_user_id: int) -> str:
        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]

        sections = []

        # Food - detailed entries
        food_entries = self._food_repo.get_by_user_and_dates(telegram_user_id, dates)
        if food_entries:
            lines = ["תזונה:"]
            for entry in food_entries[:_MAX_FOOD_ENTRIES]:
                desc = entry.description
                cal = getattr(entry, "calories", 0) or 0
                prot = getattr(entry, "protein", 0) or 0
                lines.append(f"  {entry.date} {entry.time} - {desc} ({cal} קל', {prot}g חלבון)")
            if len(food_entries) > _MAX_FOOD_ENTRIES:
                lines.append(f"  ...ועוד {len(food_entries) - _MAX_FOOD_ENTRIES} רשומות")
            sections.append("\n".join(lines))

        # Sleep - detailed entries
        sleep_logs = self._sleep_repo.get_recent(telegram_user_id, limit=7)
        if sleep_logs:
            lines = ["שינה:"]
            for log in sleep_logs:
                lines.append(f"  {log.date} - נרדם ב-{log.sleep_time}")
            sections.append("\n".join(lines))

        # Workouts - detailed entries
        workout_logs = self._workout_repo.get_recent(telegram_user_id, limit=7)
        if workout_logs:
            lines = ["אימונים:"]
            for log in workout_logs:
                note = f" - {log.note}" if log.note else ""
                lines.append(f"  {log.date}{note}")
            sections.append("\n".join(lines))

        # Self-care - detailed entries
        self_care_logs = self._self_care_repo.get_recent(telegram_user_id, limit=7)
        if self_care_logs:
            lines = ["משהו לעצמי:"]
            for log in self_care_logs:
                lines.append(f"  {log.description}")
            sections.append("\n".join(lines))

        if not sections:
            return "אין נתוני הרגלים מהשבוע האחרון."

        return "\n\n".join(sections)
