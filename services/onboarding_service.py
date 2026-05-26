"""
onboarding_service.py — Minimal onboarding: name collection only.

The onboarding collects the user's name after Telegram linking.
Goal and habit reveals are handled by GoalService and the hook system.

Depends on: repositories/user_repository, services/conversation_state_service, messages.
Used by: handlers/start_handler, handlers/base.
"""

from __future__ import annotations

import messages as M
from repositories.user_repository import UserRepository
from services.conversation_state_service import ConversationStateService


class OnboardingService:
    def __init__(
        self,
        user_repo: UserRepository,
        state_service: ConversationStateService,
        toggle_service=None,
    ):
        self._user_repo = user_repo
        self._state_service = state_service

    def start_onboarding(self, telegram_user_id: int) -> str:
        """Begin onboarding after successful linking. Returns the greeting."""
        self._state_service.set_pending(telegram_user_id, "awaiting_name")
        return M.ONBOARDING_GREETING

    def handle_name_response(self, telegram_user_id: int, name: str) -> str:
        """Process the user's name response."""
        self._user_repo.update_fields(telegram_user_id, {
            "name": name,
            "onboarding.name_collected": True,
        })
        self._state_service.clear_pending(telegram_user_id)
        return M.ONBOARDING_NAME_RESPONSE.format(name=name)
