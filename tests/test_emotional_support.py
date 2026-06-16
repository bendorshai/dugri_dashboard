"""
test_emotional_support.py - TDD tests for EmotionalSupportService.

Unit tests for empathy pool selection, inline empathy, ChatGPT prompt building,
and creator-mode referral.

Note: Keyboard tests reload the keyboards module to avoid pollution from
test files that stub sys.modules["telegram"] at module level (e.g.
test_handlers.py, test_handle_classified.py). Without the reload, the
InlineKeyboardMarkup import in keyboards.py picks up a MagicMock
when those files are collected first (alphabetical ordering).
"""

import importlib
import sys
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from services.emotional_support_service import EmotionalSupportService

# Other test files (test_handlers.py, test_handle_classified.py) replace
# sys.modules["telegram"] with a MagicMock at module level. When pytest
# collects them first (alphabetical order), keyboards.py ends up importing
# MagicMock instead of InlineKeyboardMarkup. Fix: force-reimport the real
# telegram module, then reload keyboards so it picks up the real classes.
if isinstance(sys.modules.get("telegram"), MagicMock):
    del sys.modules["telegram"]
    import telegram  # noqa: F811
    importlib.reload(importlib.import_module("keyboards"))

from keyboards import make_emotional_support_keyboard, make_emotional_creator_keyboard


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
    """Default service - creator mode (no config = default)."""
    return EmotionalSupportService(
        food_repo=repos["food_repo"],
        sleep_repo=repos["sleep_repo"],
        workout_repo=repos["workout_repo"],
        self_care_repo=repos["self_care_repo"],
        user_repo=repos["user_repo"],
    )


@pytest.fixture
def chatgpt_service(repos):
    """Service configured for legacy chatgpt mode."""
    return EmotionalSupportService(
        food_repo=repos["food_repo"],
        sleep_repo=repos["sleep_repo"],
        workout_repo=repos["workout_repo"],
        self_care_repo=repos["self_care_repo"],
        user_repo=repos["user_repo"],
        emotional_support_config={"mode": "chatgpt"},
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


class TestBuildChatgptPrompt:
    def test_includes_user_message(self, service, repos):
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "אני מרגיש רע")
        assert "אני מרגיש רע" in result

    def test_includes_detailed_food_entries(self, service, repos):
        food_entry = MagicMock()
        food_entry.calories = 500
        food_entry.protein = 30
        food_entry.date = "06/06/2026"
        food_entry.time = "12:30"
        food_entry.description = "סלט ירקות עם טונה"
        repos["food_repo"].get_by_user_and_dates.return_value = [food_entry]
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "אני עצוב")
        assert "סלט ירקות עם טונה" in result
        assert "500" in result
        assert "12:30" in result

    def test_includes_detailed_sleep_entries(self, service, repos):
        repos["food_repo"].get_by_user_and_dates.return_value = []
        sleep_log = MagicMock()
        sleep_log.date = "06/06/2026"
        sleep_log.sleep_time = "23:30"
        repos["sleep_repo"].get_recent.return_value = [sleep_log]
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "test")
        assert "23:30" in result

    def test_includes_detailed_workout_entries(self, service, repos):
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        workout_log = MagicMock()
        workout_log.date = "05/06/2026"
        workout_log.note = "ריצה 5 קמ"
        repos["workout_repo"].get_recent.return_value = [workout_log]
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "test")
        assert "ריצה 5 קמ" in result

    def test_includes_detailed_self_care_entries(self, service, repos):
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        self_care_log = MagicMock()
        self_care_log.description = "יצאתי לטיול עם חברים"
        repos["self_care_repo"].get_recent.return_value = [self_care_log]

        result = service.build_chatgpt_prompt(123, "test")
        assert "יצאתי לטיול עם חברים" in result

    def test_no_dugri_mention(self, service, repos):
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "test")
        assert "דוגרי" not in result

    def test_no_therapist_disclaimer(self, service, repos):
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(123, "test")
        assert "מטפל מוסמך" not in result
        assert "לא מטפל" not in result

    def test_empty_data_no_crash(self, service, repos):
        """With completely empty habit data, should not crash."""
        repos["food_repo"].get_by_user_and_dates.return_value = []
        repos["sleep_repo"].get_recent.return_value = []
        repos["workout_repo"].get_recent.return_value = []
        repos["self_care_repo"].get_recent.return_value = []

        result = service.build_chatgpt_prompt(999, "test")
        assert isinstance(result, str)


class TestEmotionalSupportKeyboard:
    def test_single_button(self):
        keyboard = make_emotional_support_keyboard()
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        assert len(all_buttons) == 1

    def test_button_is_callback(self):
        keyboard = make_emotional_support_keyboard()
        button = keyboard.inline_keyboard[0][0]
        assert button.callback_data is not None
        assert button.url is None


class TestCreatorMode:
    def test_default_mode_is_creator(self, service):
        assert service.mode == "creator"

    def test_creator_username_default(self, service):
        assert service.creator_username == "DoorCore"

    def test_custom_creator_username(self, repos):
        svc = EmotionalSupportService(
            **repos,
            emotional_support_config={
                "mode": "creator",
                "creator_telegram_username": "custom_user",
            },
        )
        assert svc.creator_username == "custom_user"

    def test_creator_empathy_mentions_shai(self, service):
        results = {service.get_empathy_response() for _ in range(30)}
        assert all("שי" in r for r in results)

    def test_creator_empathy_mentions_therapist(self, service):
        results = {service.get_empathy_response() for _ in range(30)}
        assert all("מטפל" in r for r in results)

    def test_chatgpt_mode_uses_old_pool(self, chatgpt_service):
        results = {chatgpt_service.get_empathy_response() for _ in range(30)}
        assert all("GPT" in r for r in results)

    def test_chatgpt_mode_flag(self, chatgpt_service):
        assert chatgpt_service.mode == "chatgpt"


class TestCreatorKeyboard:
    def test_single_url_button(self):
        keyboard = make_emotional_creator_keyboard("DoorCore")
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        assert len(all_buttons) == 1
        button = all_buttons[0]
        assert button.url == "https://t.me/DoorCore"
        assert button.callback_data is None

    def test_button_text_hebrew(self):
        keyboard = make_emotional_creator_keyboard("DoorCore")
        button = keyboard.inline_keyboard[0][0]
        assert "שי" in button.text

    def test_custom_username_in_url(self):
        keyboard = make_emotional_creator_keyboard("custom_user")
        button = keyboard.inline_keyboard[0][0]
        assert button.url == "https://t.me/custom_user"
