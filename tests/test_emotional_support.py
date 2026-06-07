"""
test_emotional_support.py - TDD tests for EmotionalSupportService.

Unit tests for empathy pool selection, inline empathy, and ChatGPT prompt building.
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from services.emotional_support_service import EmotionalSupportService


@pytest.fixture
def repos():
    return {
        "food_repo": MagicMock(),
        "sleep_repo": MagicMock(),
        "workout_repo": MagicMock(),
        "self_care_repo": MagicMock(),
        "user_repo": MagicMock(),
    }


@pytest.fixture
def service(repos):
    return EmotionalSupportService(
        food_repo=repos["food_repo"],
        sleep_repo=repos["sleep_repo"],
        workout_repo=repos["workout_repo"],
        self_care_repo=repos["self_care_repo"],
        user_repo=repos["user_repo"],
    )


class TestGetEmpathyResponse:
    def test_returns_string(self, service):
        result = service.get_empathy_response()
        assert isinstance(result, str)
        assert len(result) > 10

    def test_returns_from_pool(self, service):
        """Multiple calls should return valid strings (from pool)."""
        results = {service.get_empathy_response() for _ in range(20)}
        assert len(results) > 1  # random selection produces variety


class TestGetInlineEmpathy:
    def test_returns_shorter_string(self, service):
        result = service.get_inline_empathy()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_shorter_than_standalone(self, service):
        inline = service.get_inline_empathy()
        standalone = service.get_empathy_response()
        # Inline should be notably shorter
        assert len(inline) < len(standalone)


class TestGetOfferText:
    def test_returns_string(self, service):
        result = service.get_offer_text()
        assert isinstance(result, str)
        assert "ChatGPT" in result or "פרומפט" in result


class TestBuildChatgptPrompt:
    def test_includes_user_message(self, service, repos):
        repos["user_repo"].get.return_value = None
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "אני מרגיש רע")
        assert "אני מרגיש רע" in result

    def test_includes_habit_data(self, service, repos):
        repos["user_repo"].get.return_value = None

        # Create mock food entries
        food_entry = MagicMock()
        food_entry.calories = 500
        food_entry.protein = 30
        food_entry.date = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
        repos["food_repo"].get_by_user_and_dates.return_value = [food_entry]
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "אני עצוב")
        assert "500" in result or "קלוריות" in result

    def test_no_profile_graceful(self, service, repos):
        """With no user profile, should still produce a valid prompt."""
        repos["user_repo"].get.return_value = None
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "אני מרגיש רע")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_data_no_crash(self, service, repos):
        """With completely empty habit data, should not crash."""
        repos["user_repo"].get.return_value = None
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(999, "test")
        assert isinstance(result, str)
