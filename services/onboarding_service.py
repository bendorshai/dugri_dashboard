"""
onboarding_service.py — Minimal onboarding: name + target offer.

The onboarding collects the user's name and invites them to log their first
meal. After the first meal, it offers to calculate personalized targets.

Habit reveals (sleep, eating window, workouts, self-care) are handled by
the hook system in scheduler.py, NOT here.

Depends on: repositories/user_repository, services/conversation_state_service,
            services/toggle_service, messages.
Used by: handlers/start_handler, handlers/base.
"""

from __future__ import annotations

import messages as M
from models.profile import User
from repositories.user_repository import UserRepository
from services.conversation_state_service import ConversationStateService
from services.toggle_service import ToggleService


class OnboardingService:
    def __init__(
        self,
        user_repo: UserRepository,
        state_service: ConversationStateService,
        toggle_service: ToggleService | None = None,
    ):
        self._user_repo = user_repo
        self._state_service = state_service
        self._toggle_service = toggle_service

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

    # ------------------------------------------------------------------
    # Target offer (after first meal)
    # ------------------------------------------------------------------

    def should_offer_target(self, profile: User, meal_count: int) -> bool:
        """Should we offer target calculation? Only after the first meal, if dormant."""
        if meal_count != 1:
            return False
        return profile.toggles.target_data.status == "dormant"

    def offer_target(self, telegram_user_id: int) -> str:
        """Offer to calculate personalized calorie/protein targets."""
        self._state_service.set_pending(telegram_user_id, "awaiting_target_consent")
        if self._toggle_service:
            self._toggle_service.reveal_toggle(telegram_user_id, "target_data")
        return M.TARGET_OFFER_FIRST

    def handle_target_consent(self, telegram_user_id: int, accepted: bool) -> str:
        """Handle yes/no response to target offer."""
        if accepted:
            self._state_service.set_pending(telegram_user_id, "awaiting_body_stats")
            return M.ASK_BODY_STATS
        else:
            self._state_service.clear_pending(telegram_user_id)
            return M.TARGET_DECLINED
