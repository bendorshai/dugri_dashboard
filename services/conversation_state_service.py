"""
conversation_state_service.py — ה-state dispatcher המרכזי.

יודע מה דוגרי מחכה לו מהמשתמש כרגע, ומנתב את ההודעה הבאה בהתאם.
נשען על pending_state שעל הפרופיל (UserRepository).
נבדק ראשון — לפני כל מסווג או ניתוב אחר.

תלוי ב: repositories/user_repository, models/profile.
נצרך על ידי: handlers/base.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from models.profile import UserProfile, PendingState
from repositories.user_repository import UserRepository


PENDING_TTL_SECONDS = 300  # 5 minutes


@dataclass
class DispatchResult:
    kind: str
    data: dict
    handled: bool = True


class ConversationStateService:
    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo

    def get_pending(self, profile: UserProfile) -> PendingState | None:
        if profile.pending_state is None:
            return None
        age = (datetime.now(timezone.utc) - profile.pending_state.created_at).total_seconds()
        if age > PENDING_TTL_SECONDS:
            self.clear_pending(profile.telegram_user_id)
            return None
        return profile.pending_state

    def set_pending(self, telegram_user_id: int, kind: str, data: dict | None = None) -> None:
        state = PendingState(kind=kind, data=data or {})
        self._user_repo.update_fields(telegram_user_id, {
            "pending_state": state.model_dump(mode="json"),
        })

    def clear_pending(self, telegram_user_id: int) -> None:
        self._user_repo.update_fields(telegram_user_id, {
            "pending_state": None,
        })

    def dispatch(self, profile: UserProfile, message_text: str) -> DispatchResult | None:
        """If there's an active pending state, return it for handling. Otherwise None.

        The caller (handler) is responsible for actually processing the result.
        This service just determines *what* is pending, not *how* to handle it.
        """
        pending = self.get_pending(profile)
        if pending is None:
            return None
        return DispatchResult(kind=pending.kind, data=pending.data)
