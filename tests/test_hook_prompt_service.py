"""
test_hook_prompt_service - TDD tests for personalized self-care hook prompts.

Expected behavior:
- No past activities -> always returns a generic prompt from the pool
- Has activities + random < 0.25 -> returns generic prompt
- Has activities + random >= 0.25 -> returns personalized prompt with most frequent + random other
- Single activity -> personalized mentions just that activity
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from services.hook_prompt_service import HookPromptService

GENERIC_POOL = [
    "מה עשית השבוע שהיה טוב לך?",
    "היי, איזה דבר טוב עשית לעצמך השבוע?",
]


class TestPickSelfCarePrompt:
    def test_empty_activities_returns_generic(self):
        result = HookPromptService.pick_self_care_prompt({}, GENERIC_POOL)
        assert result in GENERIC_POOL

    @patch("services.hook_prompt_service.random")
    def test_generic_probability(self, mock_random):
        """When random.random() < 0.25, returns generic even with activities."""
        mock_random.random.return_value = 0.1
        mock_random.choice.side_effect = lambda pool: pool[0]

        activities = {"נגינה בגיטרה": 3, "הליכה לים": 1}
        result = HookPromptService.pick_self_care_prompt(activities, GENERIC_POOL)
        assert result in GENERIC_POOL

    @patch("services.hook_prompt_service.random")
    def test_personalized_with_two_activities(self, mock_random):
        """Most frequent appears first, random other is picked via random.choice."""
        mock_random.random.return_value = 0.5
        mock_random.choice.return_value = "הליכה לים"

        activities = {"נגינה בגיטרה": 5, "הליכה לים": 2, "רכיבה על סוסים": 1}
        result = HookPromptService.pick_self_care_prompt(activities, GENERIC_POOL)

        assert "נגינה בגיטרה" in result
        assert "הליכה לים" in result

    @patch("services.hook_prompt_service.random")
    def test_single_activity_format(self, mock_random):
        """With only one activity, prompt mentions just that one."""
        mock_random.random.return_value = 0.5

        activities = {"נגינה בגיטרה": 3}
        result = HookPromptService.pick_self_care_prompt(activities, GENERIC_POOL)

        assert "נגינה בגיטרה" in result
        # Should not contain "או" (or) since there's only one activity
        assert "או" not in result
