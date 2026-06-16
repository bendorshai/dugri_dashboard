"""
inappropriate_service.py - Strike recording and ban enforcement.

Records strikes for inappropriate messages, logs them permanently,
and triggers a ban after INAPPROPRIATE_MAX_STRIKES.

Depends on: repositories, models, constants, messages.
Used by: handlers/base.py (_handle_classified).
"""

from __future__ import annotations

from datetime import datetime, timezone

from constants import INAPPROPRIATE_MAX_STRIKES
from models.profile import Strike, User
from repositories.inappropriate_log_repository import InappropriateLogRepository
from repositories.user_repository import UserRepository
import messages as M


STRIKE_REASON = "inappropriate_message"


class InappropriateService:
    def __init__(
        self,
        user_repo: UserRepository,
        inappropriate_log_repo: InappropriateLogRepository,
    ):
        self._user_repo = user_repo
        self._log_repo = inappropriate_log_repo

    def record_strike(
        self, telegram_user_id: int, message_text: str, profile: User,
    ) -> dict:
        strike = Strike(
            reason=STRIKE_REASON,
            detail=message_text[:200],
            source="message_classifier",
        )
        self._user_repo.push_to_list(
            telegram_user_id, "strikes", strike.model_dump(mode="json"),
        )
        self._log_repo.log(telegram_user_id, message_text)

        count = (
            sum(1 for s in profile.strikes if s.reason == STRIKE_REASON) + 1
        )

        if count >= INAPPROPRIATE_MAX_STRIKES:
            self._user_repo.update_fields(telegram_user_id, {
                "banned_at": datetime.now(timezone.utc).isoformat(),
            })
            logs = self._log_repo.get_by_user(telegram_user_id)
            return {"action": "ban", "logs": logs}

        return {"action": "strike", "strike_number": count}

    def format_ban_message(self, logs: list[dict], gender: str) -> str:
        lines = []
        for i, log in enumerate(logs, 1):
            ts = log["created_at"]
            if isinstance(ts, datetime):
                date_str = ts.strftime("%d/%m/%Y %H:%M")
            else:
                date_str = str(ts)
            lines.append(f"{i}. \"{log['message_text']}\" ({date_str})")
        message_list = "\n".join(lines)
        template = M.INAPPROPRIATE_BAN.get(gender, M.INAPPROPRIATE_BAN["male"])
        return template.format(message_list=message_list)

    @staticmethod
    def is_banned(profile: User) -> bool:
        return profile.banned_at is not None
