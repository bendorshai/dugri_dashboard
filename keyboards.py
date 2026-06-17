from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

THUMBS_UP = "\U0001F44D"
OK_HAND = "\U0001F44C"

# Callback prefixes
CB_MENU = "menu_"
CB_PROFILE = "prof_"
CB_EDIT_FIELD = "pfield_"
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
CB_FEATURE = "feat_"
CB_SLEEP_EDIT = "sledit_"
CB_SLEEP_DELETE = "sldel_"
CB_WORKOUT_EDIT = "woedit_"
CB_WORKOUT_DELETE = "wodel_"
CB_SELFCARE_EDIT = "scedit_"
CB_SELFCARE_DELETE = "scdel_"


def make_daily_summary_keyboard(dashboard_url: str = "") -> InlineKeyboardMarkup:
    base_url = dashboard_url.rstrip("/") if dashboard_url else ""
    buttons = [
        [InlineKeyboardButton("📋 מה אכלתי היום?", callback_data=f"{CB_DAILY}summary")],
    ]
    if base_url:
        buttons.append([
            InlineKeyboardButton("⚙️ הגדרות", url=f"{base_url}/dashboard/preferences"),
            InlineKeyboardButton("👤 פרופיל", url=f"{base_url}/dashboard/profile"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("⚙️ הגדרות", callback_data=f"{CB_MENU}settings"),
            InlineKeyboardButton("👤 פרופיל", callback_data=f"{CB_MENU}profile"),
        ])
    return InlineKeyboardMarkup(buttons)


def make_main_menu_keyboard(dashboard_url: str = "") -> InlineKeyboardMarkup:
    base_url = dashboard_url.rstrip("/") if dashboard_url else ""
    buttons = [
        [InlineKeyboardButton("📋 מה אכלתי היום?", callback_data=f"{CB_DAILY}summary")],
        [InlineKeyboardButton("📅 סיכום שבועי", callback_data=f"{CB_WEEKLY}summary")],
        [InlineKeyboardButton("💬 תן לי משוב", callback_data=f"{CB_FEEDBACK}daily")],
        [
            InlineKeyboardButton("🐛 משהו לא בסדר", callback_data=f"{CB_FEATURE}bug"),
            InlineKeyboardButton("💡 הצעה לשיפור", callback_data=f"{CB_FEATURE}suggestion"),
        ],
    ]
    if base_url:
        buttons.append([InlineKeyboardButton("👤 פרופיל ויעדים", url=f"{base_url}/dashboard/profile")])
        buttons.append([InlineKeyboardButton("⚙️ הגדרות", url=f"{base_url}/dashboard/preferences")])
    else:
        buttons.append([InlineKeyboardButton("👤 פרופיל ויעדים", callback_data=f"{CB_MENU}profile")])
        buttons.append([InlineKeyboardButton("⚙️ הגדרות", callback_data=f"{CB_MENU}settings")])
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


def make_sleep_entry_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ עריכה", callback_data=f"{CB_SLEEP_EDIT}{entry_id}"),
            InlineKeyboardButton("🗑 מחיקה", callback_data=f"{CB_SLEEP_DELETE}{entry_id}"),
        ],
    ])


def make_workout_entry_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ עריכה", callback_data=f"{CB_WORKOUT_EDIT}{entry_id}"),
            InlineKeyboardButton("🗑 מחיקה", callback_data=f"{CB_WORKOUT_DELETE}{entry_id}"),
        ],
    ])


def make_self_care_entry_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ עריכה", callback_data=f"{CB_SELFCARE_EDIT}{entry_id}"),
            InlineKeyboardButton("🗑 מחיקה", callback_data=f"{CB_SELFCARE_DELETE}{entry_id}"),
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


def make_trial_cta_keyboard(dashboard_url: str = "") -> InlineKeyboardMarkup:
    base = dashboard_url.rstrip("/") if dashboard_url else "https://www.dugri.life"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("לתוכניות המנוי", url=f"{base}/plans"),
    ]])
