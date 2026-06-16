"""
onboarding_service.py - Minimal onboarding: name collection only.

The onboarding collects the user's name after Telegram linking.
Goal and habit reveals are handled by GoalService and the hook system.

Depends on: repositories/user_repository, messages.
Used by: handlers/start_handler, handlers/base.
"""

from __future__ import annotations

import messages as M
from repositories.user_repository import UserRepository


class OnboardingService:
    def __init__(
        self,
        user_repo: UserRepository,
        toggle_service=None,
    ):
        self._user_repo = user_repo

    def start_onboarding(self, telegram_user_id: int) -> str:
        """Begin onboarding after successful linking. Returns the greeting."""
        return M.ONBOARDING_GREETING

    def handle_name_response(self, telegram_user_id: int, name: str, late: bool = False) -> str:
        """Process the user's name response.

        late=False: direct reply to greeting (asks 'בן או בת?')
        late=True: declared name later ('אחלה, {name}')
        """
        self._user_repo.update_fields(telegram_user_id, {
            "name": name,
            "onboarding.name_collected": True,
        })
        if late:
            return M.ONBOARDING_NAME_LATE.format(name=name)
        return M.ONBOARDING_NAME_RESPONSE.format(name=name)

    def handle_gender_response(self, telegram_user_id: int, gender: str) -> str:
        """Process the user's gender response (male/female)."""
        self._user_repo.update_fields(telegram_user_id, {"gender": gender})
        return M.ONBOARDING_GENDER_RESPONSE
