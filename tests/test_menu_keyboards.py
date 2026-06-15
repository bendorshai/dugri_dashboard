"""
test_menu_keyboards - TDD tests for bot menu keyboard refactor.

# ============================================================================
# KEYBOARD SPECIFICATION (Single Source of Truth)
#
# MAIN MENU (make_main_menu_keyboard)
# ------------------------------------
# Button order:
#   1. "מה אכלתי היום?" -> callback daily_summary
#   2. "סיכום שבועי" -> callback weekly_summary
#   3. "תן לי משוב" -> callback feedback_daily
#   4. Bug + suggestion row (unchanged)
#   5. When dashboard_url provided:
#      - "פרופיל ויעדים" -> URL {dashboard_url}/dashboard/profile
#      - "הגדרות" -> URL {dashboard_url}/dashboard/preferences
#   6. When dashboard_url empty:
#      - "פרופיל ויעדים" -> callback menu_profile (fallback)
#      - "הגדרות" -> callback menu_settings (fallback)
#   7. REMOVED: "הצעות ארוחה", "שאל שאלה על תזונה"
#
# DAILY SUMMARY KEYBOARD (make_daily_summary_keyboard)
# -----------------------------------------------------
# Button order:
#   1. "מה אכלתי היום?" -> callback daily_summary
#   2. When dashboard_url provided:
#      - "הגדרות" + "פרופיל" as URL buttons
#   3. When dashboard_url empty:
#      - "הגדרות" + "פרופיל" as callback buttons (fallback)
#   4. REMOVED: "הצעות ארוחה", "שאל שאלה"
#
# ============================================================================
"""

import pytest

from keyboards import make_main_menu_keyboard, make_daily_summary_keyboard


def _all_buttons(keyboard):
    """Flatten InlineKeyboardMarkup into a list of buttons."""
    return [btn for row in keyboard.inline_keyboard for btn in row]


def _button_texts(keyboard):
    """Get all button texts from a keyboard."""
    return [btn.text for btn in _all_buttons(keyboard)]


def _find_button(keyboard, text_substring):
    """Find a button by partial text match."""
    for btn in _all_buttons(keyboard):
        if text_substring in btn.text:
            return btn
    return None


class TestMainMenuLabels:
    def test_daily_summary_renamed(self):
        kb = make_main_menu_keyboard()
        btn = _find_button(kb, "מה אכלתי היום")
        assert btn is not None
        assert btn.callback_data == "daily_summary"

    def test_no_old_daily_label(self):
        kb = make_main_menu_keyboard()
        assert _find_button(kb, "סיכום יומי") is None

    def test_weekly_summary_unchanged(self):
        kb = make_main_menu_keyboard()
        btn = _find_button(kb, "סיכום שבועי")
        assert btn is not None
        assert btn.callback_data == "weekly_summary"

    def test_feedback_renamed(self):
        kb = make_main_menu_keyboard()
        btn = _find_button(kb, "תן לי משוב")
        assert btn is not None
        assert btn.callback_data == "feedback_daily"

    def test_no_old_feedback_label(self):
        kb = make_main_menu_keyboard()
        assert _find_button(kb, "משוב על התזונה") is None


class TestMainMenuRemovedButtons:
    def test_no_meal_suggestions(self):
        kb = make_main_menu_keyboard()
        assert _find_button(kb, "הצעות ארוחה") is None

    def test_no_nutrition_question(self):
        kb = make_main_menu_keyboard()
        assert _find_button(kb, "שאל שאלה") is None


class TestMainMenuDashboardLinks:
    def test_profile_is_url_when_dashboard_provided(self):
        kb = make_main_menu_keyboard("https://www.dugri.life")
        btn = _find_button(kb, "פרופיל ויעדים")
        assert btn is not None
        assert btn.url == "https://www.dugri.life/dashboard/profile"
        assert btn.callback_data is None

    def test_settings_is_url_when_dashboard_provided(self):
        kb = make_main_menu_keyboard("https://www.dugri.life")
        btn = _find_button(kb, "הגדרות")
        assert btn is not None
        assert btn.url == "https://www.dugri.life/dashboard/preferences"
        assert btn.callback_data is None

    def test_profile_is_callback_when_no_dashboard(self):
        kb = make_main_menu_keyboard()
        btn = _find_button(kb, "פרופיל ויעדים")
        assert btn is not None
        assert btn.callback_data == "menu_profile"

    def test_settings_is_callback_when_no_dashboard(self):
        kb = make_main_menu_keyboard()
        btn = _find_button(kb, "הגדרות")
        assert btn is not None
        assert btn.callback_data == "menu_settings"

    def test_trailing_slash_stripped(self):
        kb = make_main_menu_keyboard("https://www.dugri.life/")
        btn = _find_button(kb, "פרופיל ויעדים")
        assert btn.url == "https://www.dugri.life/dashboard/profile"

    def test_bug_suggestion_row_unchanged(self):
        kb = make_main_menu_keyboard()
        assert _find_button(kb, "משהו לא בסדר") is not None
        assert _find_button(kb, "הצעה לשיפור") is not None


class TestDailySummaryKeyboard:
    def test_daily_summary_renamed(self):
        kb = make_daily_summary_keyboard()
        btn = _find_button(kb, "מה אכלתי היום")
        assert btn is not None
        assert btn.callback_data == "daily_summary"

    def test_no_meal_suggestions(self):
        kb = make_daily_summary_keyboard()
        assert _find_button(kb, "הצעות ארוחה") is None

    def test_no_ask_question(self):
        kb = make_daily_summary_keyboard()
        assert _find_button(kb, "שאל שאלה") is None

    def test_profile_is_url_when_dashboard_provided(self):
        kb = make_daily_summary_keyboard("https://www.dugri.life")
        btn = _find_button(kb, "פרופיל")
        assert btn is not None
        assert btn.url == "https://www.dugri.life/dashboard/profile"

    def test_settings_is_url_when_dashboard_provided(self):
        kb = make_daily_summary_keyboard("https://www.dugri.life")
        btn = _find_button(kb, "הגדרות")
        assert btn is not None
        assert btn.url == "https://www.dugri.life/dashboard/preferences"

    def test_callback_fallback_when_no_dashboard(self):
        kb = make_daily_summary_keyboard()
        btn = _find_button(kb, "הגדרות")
        assert btn is not None
        assert btn.callback_data == "menu_settings"
