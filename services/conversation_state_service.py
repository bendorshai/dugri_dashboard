"""
conversation_state_service.py — the central state dispatcher.

Knows what Dugri is waiting for from the user, and routes the next message.
Relies on pending_state on the profile (UserRepository).
Checked first — before any classifier or other routing.

Depends on: repositories/user_repository, models/profile.
Used by: handlers/base.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from models.profile import UserProfile, PendingState
from repositories.user_repository import UserRepository


PENDING_TTL_SECONDS = 3600  # 1 hour — generous because classifier handles context, not the TTL

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    kind: str
    data: dict
    handled: bool = True


class ConversationStateService:
    def __init__(self, user_repo: UserRepository):
        self._user_repo = user_repo
        self._on_expired: Callable[[int, str, dict], None] | None = None

    @property
    def on_expired(self) -> Callable[[int, str, dict], None] | None:
        return self._on_expired

    @on_expired.setter
    def on_expired(self, callback: Callable[[int, str, dict], None] | None) -> None:
        self._on_expired = callback

    def get_pending(self, profile: UserProfile) -> PendingState | None:
        if profile.pending_state is None:
            return None
        age = (datetime.now(timezone.utc) - profile.pending_state.created_at).total_seconds()
        if age > PENDING_TTL_SECONDS:
            expired = profile.pending_state
            self.clear_pending(profile.telegram_user_id)
            # Notify callback (e.g. GoalService ghosting handler)
            if self._on_expired:
                try:
                    self._on_expired(profile.telegram_user_id, expired.kind, expired.data)
                except Exception:
                    logger.exception("on_expired callback failed for kind=%s", expired.kind)
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
