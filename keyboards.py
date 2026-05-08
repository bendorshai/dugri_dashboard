from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

THUMBS_UP = "\U0001F44D"
OK_HAND = "\U0001F44C"

# Callback prefixes
CB_MENU = "menu_"
CB_PROFILE = "prof_"
CB_EDIT_FIELD = "pfield_"
CB_SUGGEST = "suggest_"
CB_ASK = "ask_"
CB_FOOD_EDIT = "fedit_"
CB_FOOD_DELETE = "fdel_"
CB_BULK_FIX = "bfix_"
CB_WEEKLY = "weekly_"
CB_BACK = "back_"


def make_daily_summary_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍽 הצעות ארוחה", callback_data=f"{CB_SUGGEST}meals"),
            InlineKeyboardButton("❓ שאל שאלה", callback_data=f"{CB_ASK}question"),
        ],
        [
            InlineKeyboardButton("⚙️ הגדרות", callback_data=f"{CB_MENU}settings"),
            InlineKeyboardButton("👤 פרופיל", callback_data=f"{CB_MENU}profile"),
        ],
    ])


def make_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 סיכום שבועי", callback_data=f"{CB_WEEKLY}summary")],
        [InlineKeyboardButton("🍽 הצעות ארוחה", callback_data=f"{CB_SUGGEST}meals")],
        [InlineKeyboardButton("❓ שאל שאלה על תזונה", callback_data=f"{CB_ASK}question")],
        [InlineKeyboardButton("🔧 תיקון כללי", callback_data=f"{CB_BULK_FIX}start")],
        [InlineKeyboardButton("👤 פרופיל ויעדים", callback_data=f"{CB_MENU}profile")],
        [InlineKeyboardButton("⚙️ הגדרות", callback_data=f"{CB_MENU}settings")],
    ])


def make_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("גיל", callback_data=f"{CB_EDIT_FIELD}age"),
            InlineKeyboardButton("גובה", callback_data=f"{CB_EDIT_FIELD}height_cm"),
            InlineKeyboardButton("משקל", callback_data=f"{CB_EDIT_FIELD}weight_kg"),
        ],
        [
            InlineKeyboardButton("יעד קלוריות", callback_data=f"{CB_EDIT_FIELD}target_calories"),
            InlineKeyboardButton("יעד חלבון", callback_data=f"{CB_EDIT_FIELD}target_protein"),
        ],
        [
            InlineKeyboardButton("חלון אכילה", callback_data=f"{CB_EDIT_FIELD}eating_window"),
            InlineKeyboardButton("אזור זמן", callback_data=f"{CB_EDIT_FIELD}timezone"),
        ],
        [InlineKeyboardButton("🤖 הצע יעדים לפי נתוני גוף", callback_data=f"{CB_PROFILE}suggest_targets")],
        [InlineKeyboardButton("חזור", callback_data=f"{CB_BACK}main")],
    ])


def make_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 פרופיל ויעדים", callback_data=f"{CB_MENU}profile")],
        [InlineKeyboardButton("חזור", callback_data=f"{CB_BACK}main")],
    ])


def make_food_edit_keyboard(row_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 מחיקה", callback_data=f"{CB_FOOD_DELETE}{row_number}")],
        [InlineKeyboardButton("חזור", callback_data=f"{CB_BACK}main")],
    ])


def make_food_entry_keyboard(row_number: int) -> InlineKeyboardMarkup:
    """Keyboard shown after logging food: edit/delete only."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ עריכה", callback_data=f"{CB_FOOD_EDIT}{row_number}"),
            InlineKeyboardButton("🗑 מחיקה", callback_data=f"{CB_FOOD_DELETE}{row_number}"),
        ],
    ])


def format_daily_status(
    total_cal: int,
    total_protein: int,
    target_cal: int,
    target_protein: int,
) -> str:
    cal_icon = "✅" if total_cal <= target_cal else "⚠️"
    prot_icon = "✅" if total_protein >= target_protein else "⚠️"
    cal_remaining = target_cal - total_cal
    prot_remaining = target_protein - total_protein

    lines = [
        "\n📊 סיכום יומי:",
        f"{cal_icon} קלוריות: {total_cal}/{target_cal} (נותרו: {cal_remaining})",
        f"{prot_icon} חלבון: {total_protein}g/{target_protein}g (נותרו: {prot_remaining}g)",
    ]
    return "\n".join(lines)
