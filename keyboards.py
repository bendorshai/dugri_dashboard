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
CB_FOOD_AGAIN = "fagain_"
CB_WEEKLY = "weekly_"
CB_DAILY = "daily_"
CB_BACK = "back_"
CB_FEEDBACK = "feedback_"
CB_EMOTIONAL = "emo_"
CB_DEBUG = "dbg_"
CB_GEM = "gem_"


def make_daily_summary_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 סיכום יומי", callback_data=f"{CB_DAILY}summary")],
        [
            InlineKeyboardButton("🍽 הצעות ארוחה", callback_data=f"{CB_SUGGEST}meals"),
            InlineKeyboardButton("❓ שאל שאלה", callback_data=f"{CB_ASK}question"),
        ],
        [
            InlineKeyboardButton("⚙️ הגדרות", callback_data=f"{CB_MENU}settings"),
            InlineKeyboardButton("👤 פרופיל", callback_data=f"{CB_MENU}profile"),
        ],
    ])


def make_main_menu_keyboard(dashboard_url: str = "") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📋 סיכום יומי", callback_data=f"{CB_DAILY}summary")],
        [InlineKeyboardButton("📅 סיכום שבועי", callback_data=f"{CB_WEEKLY}summary")],
        [InlineKeyboardButton("💬 משוב על התזונה", callback_data=f"{CB_FEEDBACK}daily")],
        [InlineKeyboardButton("🍽 הצעות ארוחה", callback_data=f"{CB_SUGGEST}meals")],
        [InlineKeyboardButton("❓ שאל שאלה על תזונה", callback_data=f"{CB_ASK}question")],
        [InlineKeyboardButton("👤 פרופיל ויעדים", callback_data=f"{CB_MENU}profile")],
        [InlineKeyboardButton("⚙️ הגדרות", callback_data=f"{CB_MENU}settings")],
    ]
    if dashboard_url:
        buttons.append([InlineKeyboardButton("📊 דשבורד", url=dashboard_url)])
    return InlineKeyboardMarkup(buttons)


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


def make_food_edit_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 מחיקה", callback_data=f"{CB_FOOD_DELETE}{entry_id}")],
        [InlineKeyboardButton("חזור", callback_data=f"{CB_BACK}main")],
    ])


def make_food_entry_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    """Keyboard shown after logging food: edit, delete, and duplicate."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ עריכה", callback_data=f"{CB_FOOD_EDIT}{entry_id}"),
            InlineKeyboardButton("🗑 מחיקה", callback_data=f"{CB_FOOD_DELETE}{entry_id}"),
        ],
        [
            InlineKeyboardButton("🔁 עוד אחד", callback_data=f"{CB_FOOD_AGAIN}{entry_id}"),
        ],
        [
            InlineKeyboardButton("📋 תפריט", callback_data=f"{CB_BACK}main"),
        ],
    ])


def inject_debug_button(reply_markup: InlineKeyboardMarkup | None, debug_key: str) -> InlineKeyboardMarkup:
    """Append a debug button row to an existing keyboard or create a new one."""
    debug_row = [InlineKeyboardButton("🔍", callback_data=f"{CB_DEBUG}{debug_key}")]
    if reply_markup is None:
        return InlineKeyboardMarkup([debug_row])
    return InlineKeyboardMarkup(list(reply_markup.inline_keyboard) + [debug_row])


def make_emotional_support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("רוצה לדבר על זה?", callback_data=f"{CB_EMOTIONAL}chatgpt")],
    ])


def make_emotional_creator_keyboard(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("רוצה לדבר עם שי?", url=f"https://t.me/{username}")],
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
    cal_pct = round(total_cal / target_cal * 100) if target_cal else 0
    prot_pct = round(total_protein / target_protein * 100) if target_protein else 0

    lines = [
        "\n\n📊 סיכום יומי:",
        f"{cal_icon} קלוריות: {total_cal}/{target_cal} ({cal_pct}%, נותרו: {cal_remaining})",
        f"{prot_icon} גרם חלבון: {total_protein}/{target_protein} ({prot_pct}%, נותרו: {prot_remaining})",
    ]
    return "\n".join(lines)


def make_gem_feedback_keyboard(gem_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("\U0001F44D", callback_data=f"{CB_GEM}like_{gem_id}"),
        InlineKeyboardButton("\U0001F44E", callback_data=f"{CB_GEM}dislike_{gem_id}"),
    ]])
