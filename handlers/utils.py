from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.profile import User
    from services.toggle_service import ToggleService

logger = logging.getLogger(__name__)

MAX_TG_LENGTH = 4096
PENDING_STATE_TTL = 300  # 5 minutes


async def safe_answer(query, text: str = "") -> None:
    """Acknowledge a callback query, silently ignoring failures."""
    try:
        await query.answer(text)
    except Exception:
        logger.debug("Could not answer callback query")


async def safe_react(message, emoji: str) -> None:
    """Set a reaction on a message, silently ignoring failures."""
    try:
        await message.set_reaction(emoji)
    except Exception:
        logger.debug("Could not set reaction %s", emoji)


async def send_long_text(message, text: str, reply_markup=None) -> None:
    """Send text that may exceed Telegram's 4096-char limit, splitting into chunks."""
    if len(text) <= MAX_TG_LENGTH:
        await message.reply_text(text, reply_markup=reply_markup)
        return
    while text:
        if len(text) <= MAX_TG_LENGTH:
            await message.reply_text(text, reply_markup=reply_markup)
            break
        split_at = text.rfind("\n", 0, MAX_TG_LENGTH)
        if split_at <= 0:
            split_at = MAX_TG_LENGTH
        await message.reply_text(text[:split_at])
        text = text[split_at:].lstrip("\n")


TOGGLE_GATE_DAYS_MAP = {
    "nutrition": 0, "sleep": 1, "eating_window": 4, "workouts": 4, "self_care": 4,
}


def format_debug_metadata(
    classification_type: str | None,
    profile: User,
    toggle_service: ToggleService,
    source: str = "handler",
) -> str:
    """Format debug metadata block for super debug mode."""
    day_number = toggle_service.get_day_number(profile)

    lines = [f"--- SUPER DEBUG (day {day_number}) ---"]
    lines.append(f"[Source] {source}")
    lines.append(f"[Classification] {classification_type or 'N/A (scheduled)'}")

    lines.append("[Toggles]")
    toggle_names = ["nutrition", "sleep", "eating_window", "workouts", "self_care", "weekly_summary"]
    for name in toggle_names:
        toggle = getattr(profile.toggles, name, None)
        if not toggle:
            continue
        gate = TOGGLE_GATE_DAYS_MAP.get(name, "")
        gate_str = f" (day {gate})" if gate != "" else ""
        parts = [f"{name}{gate_str}: {toggle.status}"]
        if toggle.status == "active":
            if toggle.goal_status == "set" and toggle.goal_value:
                parts.append(f"goal=set {toggle.goal_value}")
            elif toggle.goal_status == "pending" and toggle.goal_offered_at:
                parts.append("goal pending (offered, awaiting value)")
            elif toggle.goal_status == "pending":
                parts.append("goal pending (not yet offered)")
            elif toggle.goal_status == "declined":
                parts.append("goal declined")
            elif toggle.goal_status == "remind":
                remind = toggle.goal_remind_at.strftime("%Y-%m-%d") if toggle.goal_remind_at else "?"
                parts.append(f"goal remind ({remind})")
            elif toggle.goal_status == "remind_pending":
                parts.append("goal remind_pending")
        elif toggle.status == "dormant":
            if toggle.revealed_at:
                parts.append("revealed, waiting for accept")
            else:
                parts.append("not revealed")
        lines.append(", ".join(parts))

    next_step = toggle_service.predict_next_step(profile)
    lines.append(f"[Next] {next_step}")

    return "\n".join(lines)


async def send_long_bot(bot, tid: int, text: str, reply_markup=None) -> None:
    """Send text via bot.send_message, splitting if it exceeds Telegram's 4096-char limit."""
    if len(text) <= MAX_TG_LENGTH:
        await bot.send_message(chat_id=tid, text=text, reply_markup=reply_markup)
        return
    while text:
        if len(text) <= MAX_TG_LENGTH:
            await bot.send_message(chat_id=tid, text=text, reply_markup=reply_markup)
            break
        split_at = text.rfind("\n", 0, MAX_TG_LENGTH)
        if split_at <= 0:
            split_at = MAX_TG_LENGTH
        await bot.send_message(chat_id=tid, text=text[:split_at])
        text = text[split_at:].lstrip("\n")
