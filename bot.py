"""
bot.py — יצירת אפליקציית הטלגרם של דוגרי.

מרכיב את כל ה-handlers, ה-error handler, ומתזמן את ה-jobs.

תלוי ב: handlers, repositories, services, analyzer, scheduler.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)

from analyzer import FoodAnalyzer
from repositories.user_repository import UserRepository
from repositories.food_repository import FoodRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from repositories.error_repository import ErrorRepository
from services.eating_day_service import EatingDayService
from services.linking_service import LinkingService
from services.conversation_state_service import ConversationStateService
from services.onboarding_service import OnboardingService
from services.habit_service import HabitService
from services.help_service import HelpService
from services.qa_service import QaService
from services.message_router_service import MessageRouterService
from services.trial_service import TrialService
from services.feedback_service import FeedbackService
from services.toggle_service import ToggleService
from handlers.start_handler import StartHandler
from keyboards import (
    CB_MENU, CB_PROFILE, CB_EDIT_FIELD, CB_SUGGEST,
    CB_ASK, CB_FOOD_EDIT, CB_FOOD_DELETE, CB_FOOD_AGAIN, CB_BULK_FIX, CB_WEEKLY, CB_DAILY, CB_BACK,
    CB_FEEDBACK,
)
from handlers import HealthHandlers
from scheduler import schedule_eating_window_jobs, schedule_hooks_for_user

logger = logging.getLogger(__name__)


def _make_error_handler(error_repo: ErrorRepository):
    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Unhandled exception while processing update:", exc_info=context.error)

        telegram_user_id = None
        message_text = ""
        update_id = None
        handler_name = ""
        if isinstance(update, Update):
            update_id = update.update_id
            if update.effective_user:
                telegram_user_id = update.effective_user.id
            if update.effective_message and update.effective_message.text:
                message_text = update.effective_message.text
            if update.callback_query and update.callback_query.data:
                handler_name = f"callback:{update.callback_query.data}"
            elif update.effective_message:
                handler_name = "message"

        try:
            error_repo.log(
                error=context.error,
                handler=handler_name,
                telegram_user_id=telegram_user_id,
                message_text=message_text,
                update_id=update_id,
            )
        except Exception:
            logger.exception("Failed to log error to MongoDB")

        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text("❌ שגיאה פנימית. נסה שוב.")
            except Exception:
                pass

    return _error_handler


def create_bot(
    token: str,
    analyzer: FoodAnalyzer,
    user_repo: UserRepository,
    food_repo: FoodRepository,
    feedback_repo: WeeklyFeedbackRepository,
    error_repo: ErrorRepository,
    eating_day_service: EatingDayService,
    sleep_repo=None,
    workout_repo=None,
    self_care_repo=None,
    landing_page_url: str = "https://dugri.up.railway.app",
) -> Application:
    app = Application.builder().token(token).build()

    # Services
    state_service = ConversationStateService(user_repo)
    toggle_service = ToggleService(user_repo)
    onboarding_service = OnboardingService(user_repo, state_service, toggle_service)

    # Message router (if habit repos are provided)
    message_router = None
    if sleep_repo and workout_repo and self_care_repo:
        habit_service = HabitService(sleep_repo, workout_repo, self_care_repo)
        qa_service = QaService(analyzer, food_repo)
        help_service = HelpService(analyzer)
        message_router = MessageRouterService(habit_service, qa_service, help_service)

    trial_service = TrialService(user_repo, landing_page_url)
    feedback_service = FeedbackService(
        analyzer, food_repo, user_repo, feedback_repo, state_service,
    )

    h = HealthHandlers(
        analyzer=analyzer,
        user_repo=user_repo,
        food_repo=food_repo,
        feedback_repo=feedback_repo,
        eating_day_service=eating_day_service,
        state_service=state_service,
        onboarding_service=onboarding_service,
        message_router=message_router,
        trial_service=trial_service,
        feedback_service=feedback_service,
        toggle_service=toggle_service,
        landing_page_url=landing_page_url,
    )

    # Start handler with linking
    linking_service = LinkingService(user_repo)
    start_handler = StartHandler(linking_service, onboarding_service, landing_page_url)
    app.add_handler(CommandHandler("start", start_handler.handle_start))

    # Command handlers
    app.add_handler(CommandHandler("menu", h.handle_menu_command))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h.handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, h.handle_photo))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(h.handle_menu_callback, pattern=f"^{CB_MENU}"))
    app.add_handler(CallbackQueryHandler(h.handle_profile_callback, pattern=f"^{CB_PROFILE}"))
    app.add_handler(CallbackQueryHandler(h.handle_edit_field_callback, pattern=f"^{CB_EDIT_FIELD}"))
    app.add_handler(CallbackQueryHandler(h.handle_suggest_callback, pattern=f"^{CB_SUGGEST}"))
    app.add_handler(CallbackQueryHandler(h.handle_ask_callback, pattern=f"^{CB_ASK}"))
    app.add_handler(CallbackQueryHandler(h.handle_food_edit_callback, pattern=f"^{CB_FOOD_EDIT}"))
    app.add_handler(CallbackQueryHandler(h.handle_food_delete_callback, pattern=f"^{CB_FOOD_DELETE}"))
    app.add_handler(CallbackQueryHandler(h.handle_food_again_callback, pattern=f"^{CB_FOOD_AGAIN}"))
    app.add_handler(CallbackQueryHandler(h.handle_bulk_fix_callback, pattern=f"^{CB_BULK_FIX}"))
    app.add_handler(CallbackQueryHandler(h.handle_weekly_callback, pattern=f"^{CB_WEEKLY}"))
    app.add_handler(CallbackQueryHandler(h.handle_daily_callback, pattern=f"^{CB_DAILY}"))
    app.add_handler(CallbackQueryHandler(h.handle_feedback_callback, pattern=f"^{CB_FEEDBACK}"))
    app.add_handler(CallbackQueryHandler(h.handle_back_callback, pattern=f"^{CB_BACK}"))

    # Error handler
    app.add_error_handler(_make_error_handler(error_repo))

    # Schedule eating window jobs for all existing users with eating windows
    profiles = user_repo.find({"eating_window": {"$ne": None}})
    for profile in profiles:
        schedule_eating_window_jobs(
            app.job_queue, profile.telegram_user_id, profile,
            user_repo, food_repo, feedback_repo,
            analyzer, eating_day_service,
        )

    # Schedule hooks for all users with active toggles
    all_users = user_repo.find({"telegram_user_id": {"$ne": None}})
    for profile in all_users:
        if profile.telegram_user_id:
            hooks = schedule_hooks_for_user(
                app.job_queue, profile.telegram_user_id, profile,
                user_repo, toggle_service,
            )

    return app
