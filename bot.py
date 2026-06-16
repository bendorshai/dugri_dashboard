"""
bot.py - יצירת אפליקציית הטלגרם של דוגרי.

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
from services.onboarding_service import OnboardingService
from services.habit_service import HabitService
from services.help_service import HelpService
from services.qa_service import QaService
from services.message_router_service import MessageRouterService
from services.trial_service import TrialService
from services.feedback_service import FeedbackService
from services.toggle_service import ToggleService
from services.goal_service import GoalService
from services.emotional_support_service import EmotionalSupportService
from services.re_engagement_service import ReEngagementService
from handlers.start_handler import StartHandler
from keyboards import (
    CB_MENU, CB_PROFILE, CB_EDIT_FIELD, CB_SUGGEST,
    CB_ASK, CB_FOOD_EDIT, CB_FOOD_DELETE, CB_FOOD_AGAIN, CB_WEEKLY, CB_DAILY, CB_BACK,
    CB_FEEDBACK, CB_EMOTIONAL, CB_DEBUG, CB_GEM, CB_FEATURE,
    CB_SLEEP_EDIT, CB_SLEEP_DELETE, CB_WORKOUT_EDIT, CB_WORKOUT_DELETE,
    CB_SELFCARE_EDIT, CB_SELFCARE_DELETE,
)
from handlers import HealthHandlers
from scheduler import schedule_global_poller

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
    hook_schedule_store=None,
    landing_page_url: str = "https://www.dugri.life",
    feature_request_repo=None,
    admin_chat_id: int = 0,
    token_log_repo=None,
    emotional_support_config: dict | None = None,
    inappropriate_log_repo=None,
) -> Application:
    app = Application.builder().token(token).build()

    # Services
    toggle_service = ToggleService(user_repo)
    goal_service = GoalService(user_repo, toggle_service, analyzer)
    onboarding_service = OnboardingService(user_repo)

    # Message router (if habit repos are provided)
    message_router = None
    if sleep_repo and workout_repo and self_care_repo:
        from pathlib import Path
        knowledge_path = Path(__file__).parent / "knowledge" / "dugri-self-knowledge.md"
        habit_service = HabitService(sleep_repo, workout_repo, self_care_repo)
        qa_service = QaService(analyzer, food_repo)
        help_service = HelpService(analyzer, knowledge_path=knowledge_path)
        from services.conversational_service import ConversationalService
        trial_sales_path = Path(__file__).parent / "knowledge" / "dugri-trial-sales.md"
        conversational_service = ConversationalService(
            analyzer, knowledge_path=knowledge_path, trial_sales_path=trial_sales_path,
        )
        message_router = MessageRouterService(
            habit_service, qa_service, help_service, feature_request_repo,
            analyzer=analyzer, user_repo=user_repo,
        )

    # Emotional support (creator referral or ChatGPT handoff)
    emotional_support_service = None
    if sleep_repo and workout_repo and self_care_repo:
        emotional_support_service = EmotionalSupportService(
            food_repo=food_repo,
            sleep_repo=sleep_repo,
            workout_repo=workout_repo,
            self_care_repo=self_care_repo,
            user_repo=user_repo,
            emotional_support_config=emotional_support_config,
        )

    trial_service = TrialService(user_repo, landing_page_url)
    feedback_service = FeedbackService(
        analyzer, food_repo, user_repo, feedback_repo,
        sleep_repo, workout_repo, self_care_repo,
    )
    re_engagement_service = ReEngagementService(user_repo, food_repo, analyzer)

    # Inappropriate strike service
    inappropriate_service = None
    if inappropriate_log_repo:
        from services.inappropriate_service import InappropriateService
        inappropriate_service = InappropriateService(user_repo, inappropriate_log_repo)

    # Wisdom gems
    from services.pattern_detector import PatternDetector
    from services.gem_service import GemService
    pattern_detector = PatternDetector(food_repo)
    gem_service = GemService(user_repo, pattern_detector, toggle_service, analyzer)

    h = HealthHandlers(
        analyzer=analyzer,
        user_repo=user_repo,
        food_repo=food_repo,
        feedback_repo=feedback_repo,
        eating_day_service=eating_day_service,
        onboarding_service=onboarding_service,
        message_router=message_router,
        trial_service=trial_service,
        feedback_service=feedback_service,
        toggle_service=toggle_service,
        goal_service=goal_service,
        emotional_support_service=emotional_support_service,
        conversational_service=conversational_service,
        re_engagement_service=re_engagement_service,
        inappropriate_service=inappropriate_service,
        landing_page_url=landing_page_url,
        admin_chat_id=admin_chat_id,
        token_log_repo=token_log_repo,
        sleep_repo=sleep_repo,
        workout_repo=workout_repo,
        self_care_repo=self_care_repo,
    )
    h.gem_service = gem_service

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
    app.add_handler(CallbackQueryHandler(h.handle_feature_request_callback, pattern=f"^{CB_FEATURE}"))
    app.add_handler(CallbackQueryHandler(h.handle_food_edit_callback, pattern=f"^{CB_FOOD_EDIT}"))
    app.add_handler(CallbackQueryHandler(h.handle_food_delete_callback, pattern=f"^{CB_FOOD_DELETE}"))
    app.add_handler(CallbackQueryHandler(h.handle_food_again_callback, pattern=f"^{CB_FOOD_AGAIN}"))
    app.add_handler(CallbackQueryHandler(h.handle_weekly_callback, pattern=f"^{CB_WEEKLY}"))
    app.add_handler(CallbackQueryHandler(h.handle_daily_callback, pattern=f"^{CB_DAILY}"))
    app.add_handler(CallbackQueryHandler(h.handle_feedback_callback, pattern=f"^{CB_FEEDBACK}"))
    app.add_handler(CallbackQueryHandler(h.handle_emotional_callback, pattern=f"^{CB_EMOTIONAL}"))
    app.add_handler(CallbackQueryHandler(h.handle_back_callback, pattern=f"^{CB_BACK}"))
    app.add_handler(CallbackQueryHandler(h.handle_debug_callback, pattern=f"^{CB_DEBUG}"))
    app.add_handler(CallbackQueryHandler(h.handle_gem_callback, pattern=f"^{CB_GEM}"))
    app.add_handler(CallbackQueryHandler(h.handle_sleep_edit_callback, pattern=f"^{CB_SLEEP_EDIT}"))
    app.add_handler(CallbackQueryHandler(h.handle_sleep_delete_callback, pattern=f"^{CB_SLEEP_DELETE}"))
    app.add_handler(CallbackQueryHandler(h.handle_workout_edit_callback, pattern=f"^{CB_WORKOUT_EDIT}"))
    app.add_handler(CallbackQueryHandler(h.handle_workout_delete_callback, pattern=f"^{CB_WORKOUT_DELETE}"))
    app.add_handler(CallbackQueryHandler(h.handle_selfcare_edit_callback, pattern=f"^{CB_SELFCARE_EDIT}"))
    app.add_handler(CallbackQueryHandler(h.handle_selfcare_delete_callback, pattern=f"^{CB_SELFCARE_DELETE}"))

    # Error handler
    app.add_error_handler(_make_error_handler(error_repo))

    # Single unified polling loop for all scheduled messages
    schedule_global_poller(
        app.job_queue, user_repo, toggle_service,
        goal_service=goal_service,
        eating_day_service=eating_day_service,
        hook_schedule_store=hook_schedule_store,
        food_repo=food_repo,
        re_engagement_service=re_engagement_service,
        gem_service=gem_service,
        admin_chat_id=admin_chat_id,
        trial_service=trial_service,
        feedback_service=feedback_service,
        landing_page_url=landing_page_url,
    )

    return app
