"""
internal_api.py — Internal webhook endpoint for dashboard-to-bot notifications.

Handles target change notifications from the dashboard. When a user updates
their targets on the dashboard, this endpoint receives the old and new values,
generates a GPT-powered validation message in Dugri's tone, and sends it
to the user via Telegram.

Depends on: analyzer, prompts, telegram bot instance.
Used by: bot.py (registered as a webhook route).
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
