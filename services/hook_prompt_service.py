"""
hook_prompt_service.py - personalized hook prompt selection.

Picks self-care hook prompts based on user's activity histogram.
If the user has logged activities before, 75% of the time Dugri asks
about specific past activities instead of a generic question.

Depends on: nothing (pure logic).
Used by: handlers/base.py, scheduler.py.
"""

from __future__ import annotations

import random


class HookPromptService:
    @staticmethod
    def pick_self_care_prompt(
        activities: dict[str, int],
        generic_pool: list[str],
    ) -> str:
        """Pick a self-care hook prompt, personalized if history exists."""
        if not activities or random.random() < 0.25:
            return random.choice(generic_pool)

        sorted_acts = sorted(activities.items(), key=lambda x: -x[1])
        most_frequent = sorted_acts[0][0]

        if len(sorted_acts) == 1:
            return f"תגיד יצא לך ל{most_frequent} השבוע במקרה?"

        others = [name for name, _ in sorted_acts[1:]]
        random_other = random.choice(others)
        return f"תגיד יצא לך ל{most_frequent} או ל{random_other} השבוע במקרה?"
