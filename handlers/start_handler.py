"""
start_handler.py — טיפול בפקודת /start.

ארבעה מקרים:
1. טוקן תקין, פרופיל נמצא, לא מקושר -> קישור + אונבורדינג
2. טוקן תקין, כבר מקושר -> ברכה + תפריט
3. טוקן לא תקין/פג -> הפניה לאתר
4. בלי טוקן, אין פרופיל -> הפניה לאתר
5. בלי טוקן, יש פרופיל -> ברכה + תפריט

תלוי ב: services/linking_service, services/onboarding_service.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from keyboards import make_main_menu_keyboard
from services.linking_service import LinkingService
from services.onboarding_service import OnboardingService

class StartHandler:
    def __init__(self, linking_service: LinkingService, onboarding_service: OnboardingService, landing_page_url: str = "https://www.dugri.life"):
        self._linking = linking_service
        self._onboarding = onboarding_service
        self._landing_page_url = landing_page_url

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message:
            return

        tid = update.effective_user.id
        args = context.args  # /start <token> -> args = ["<token>"]

        if args:
            token = args[0]
            result = self._linking.link(tid, token)

            if result.status == "linked":
                greeting = self._onboarding.start_onboarding(tid)
                await message.reply_text(greeting)
                return

            elif result.status == "already_linked":
                await message.reply_text(
                    "היי, כבר מקושר 👋 בוא נמשיך.",
                    reply_markup=make_main_menu_keyboard(),
                )
                return

            else:  # invalid
                await message.reply_text(
                    f"הקישור פג או לא תקין. חזור לאתר וצור קישור חדש:\n{self._landing_page_url}"
                )
                return

        # No token
        profile = self._linking.get_profile_without_token(tid)
        if profile is None:
            await message.reply_text(
                f"כדי להתחיל, הירשם כאן: {self._landing_page_url}"
            )
        else:
            await message.reply_text(
                "היי 👋 בוא נמשיך.",
                reply_markup=make_main_menu_keyboard(),
            )
