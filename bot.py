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

from sheets import SheetsClient
from analyzer import FoodAnalyzer
from storage import MongoStorage
from keyboards import (
    CB_MENU, CB_PROFILE, CB_EDIT_FIELD, CB_SUGGEST,
    CB_ASK, CB_FOOD_EDIT, CB_FOOD_DELETE, CB_FOOD_AGAIN, CB_BULK_FIX, CB_WEEKLY, CB_DAILY, CB_BACK,
)
from handlers import HealthHandlers
from scheduler import schedule_eating_window_jobs

logger = logging.getLogger(__name__)


def _make_error_handler(mongo_storage: MongoStorage):
    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Unhandled exception while processing update:", exc_info=context.error)

        chat_id = None
        message_text = ""
        update_id = None
        handler_name = ""
        if isinstance(update, Update):
            update_id = update.update_id
            if update.effective_chat:
                chat_id = update.effective_chat.id
            if update.effective_message and update.effective_message.text:
                message_text = update.effective_message.text
            if update.callback_query and update.callback_query.data:
                handler_name = f"callback:{update.callback_query.data}"
            elif update.effective_message:
                handler_name = "message"

        try:
            mongo_storage.log_error(
                error=context.error,
                handler=handler_name,
                chat_id=chat_id,
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
    chat_id: int,
    sheets_client: SheetsClient,
    analyzer: FoodAnalyzer,
    mongo_storage: MongoStorage,
) -> Application:
    app = Application.builder().token(token).build()

    h = HealthHandlers(
        chat_id=chat_id,
        sheets_client=sheets_client,
        analyzer=analyzer,
        mongo_storage=mongo_storage,
    )

    # Command handlers
    app.add_handler(CommandHandler("start", h.handle_start_command))
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
    app.add_handler(CallbackQueryHandler(h.handle_back_callback, pattern=f"^{CB_BACK}"))

    # Error handler
    app.add_error_handler(_make_error_handler(mongo_storage))

    # Schedule eating window jobs
    profile = mongo_storage.get_user_profile(chat_id)
    if profile:
        schedule_eating_window_jobs(
            app.job_queue, chat_id, profile,
            mongo_storage, analyzer, sheets_client,
        )

    return app
