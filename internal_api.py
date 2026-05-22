"""
internal_api.py — Internal webhook handlers for dashboard-to-bot notifications.

Handles:
- Target change notifications (GPT-powered validation message)
- Admin outreach (founder wants to connect with user)

Depends on: analyzer, prompts, telegram bot instance.
Used by: web_server.py (registered as Starlette routes).
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

from prompts import TARGET_CHANGE_VALIDATION_PROMPT

logger = logging.getLogger(__name__)


def validate_secret(request_secret: str, expected_secret: str) -> bool:
    """Constant-time comparison of internal API secret."""
    return hmac.compare_digest(request_secret, expected_secret)


def build_target_change_prompt(
    old_cal: int | None,
    new_cal: int | None,
    old_prot: int | None,
    new_prot: int | None,
) -> str:
    """Build the GPT prompt for target change validation."""
    return TARGET_CHANGE_VALIDATION_PROMPT.format(
        old_cal=old_cal or "לא הוגדר",
        new_cal=new_cal or "לא הוגדר",
        old_prot=old_prot or "לא הוגדר",
        new_prot=new_prot or "לא הוגדר",
    )


async def handle_target_change(
    telegram_user_id: int,
    old_targets: dict,
    new_targets: dict,
    analyzer: Any,
    bot: Any,
) -> str | None:
    """Generate and send a target change validation message.

    Returns the generated message text, or None on failure.
    """
    prompt = build_target_change_prompt(
        old_cal=old_targets.get("calories"),
        new_cal=new_targets.get("calories"),
        old_prot=old_targets.get("protein"),
        new_prot=new_targets.get("protein"),
    )

    try:
        response = analyzer.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        message_text = response.choices[0].message.content
        if not message_text:
            return None

        await bot.send_message(chat_id=telegram_user_id, text=message_text)
        return message_text
    except Exception:
        logger.exception("Failed to handle target change notification")
        return None


async def handle_admin_outreach(
    telegram_user_id: int,
    name: str,
    founder_telegram_username: str,
    bot: Any,
) -> bool:
    """Send an outreach message inviting the user to chat with the founder.

    Returns True on success, False on failure.
    """
    greeting = f"היי {name}, " if name else "היי, "
    text = (
        f"{greeting}"
        "שי, היזם של דוגרי, רוצה להתחבר איתך כדי ללמוד על שביעות הרצון שלך מדוגרי. "
        "אם בא לך, לחצ/י על הכפתור למטה ותפתח שיחה ישירות איתו 👇"
    )

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        reply_markup = None
        if founder_telegram_username:
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    text="💬 פתח שיחה עם שי",
                    url=f"https://t.me/{founder_telegram_username}",
                ),
            ]])

        await bot.send_message(
            chat_id=telegram_user_id,
            text=text,
            reply_markup=reply_markup,
        )
        return True
    except Exception:
        logger.exception("Failed to send admin outreach message")
        return False
