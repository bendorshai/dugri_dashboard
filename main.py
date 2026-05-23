"""
main.py — נקודת כניסה של בוט דוגרי.

טוען קונפיג, מאתחל repositories ו-services, ומריץ את הבוט.
"""

import json
import logging
import os
import sys
from pathlib import Path

from pymongo import MongoClient

from analyzer import FoodAnalyzer
from repositories.user_repository import UserRepository
from repositories.food_repository import FoodRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from repositories.error_repository import ErrorRepository
from repositories.sleep_repository import SleepRepository
from repositories.workout_repository import WorkoutRepository
from repositories.self_care_repository import SelfCareRepository
from services.eating_day_service import EatingDayService
from bot import create_bot

VERSION = "2.1.0"
VERSION_NOTES = "education - הסברי הרגלים בתיעוד ראשון"
CONFIG_PATH = Path(__file__).parent / "config" / "config.json"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _parse_last_json(text: str) -> dict:
    """Parse the last valid JSON object from text, handling Railway's duplicate-append bug."""
    decoder = json.JSONDecoder()
    text = text.strip()
    result = None
    pos = 0
    while pos < len(text):
        try:
            obj, end = decoder.raw_decode(text, pos)
            result = obj
            pos = end
        except json.JSONDecodeError:
            pos += 1
    if result is None:
        raise json.JSONDecodeError("No valid JSON found", text, 0)
    return result


def load_config() -> dict:
    env_json = os.environ.get("CONFIG2_JSON") or os.environ.get("CONFIG_JSON")
    if env_json:
        logger.info("Loading config from environment variable")
        return _parse_last_json(env_json)
    if not CONFIG_PATH.exists():
        logger.error("Config file not found: %s", CONFIG_PATH)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return _parse_last_json(f.read())


def main():
    cfg = load_config()

    tg = cfg["telegram"]
    openai_cfg = cfg["openai"]
    mongo_cfg = cfg["mongodb"]

    # MongoDB setup
    mongo_uri = mongo_cfg["uri"]
    safe_uri = mongo_uri.split("@")[-1] if "@" in mongo_uri else mongo_uri
    logger.info("Connecting to MongoDB: %s", safe_uri)

    mongo_client = MongoClient(mongo_uri)
    db = mongo_client[mongo_cfg["db_name"]]

    # Repositories — single "users" collection for both dashboard and bot
    user_repo = UserRepository(db["users"])
    food_repo = FoodRepository(db["food_entries"])
    feedback_repo = WeeklyFeedbackRepository(db["weekly_feedback"])
    error_repo = ErrorRepository(db["error_logs"])
    sleep_repo = SleepRepository(db["sleep_logs"])
    workout_repo = WorkoutRepository(db["workout_logs"])
    self_care_repo = SelfCareRepository(db["self_care_logs"])

    # Services
    eating_day_service = EatingDayService(food_repo)

    # Analyzer
    food_analyzer = FoodAnalyzer(api_key=openai_cfg["api_key"])
    logger.info("GPT food analyzer ready")

    # Landing page URL
    landing_page_url = cfg.get("landing_page_url", "https://dugri.up.railway.app")

    # Create bot
    app = create_bot(
        token=tg["bot_token"],
        analyzer=food_analyzer,
        user_repo=user_repo,
        food_repo=food_repo,
        feedback_repo=feedback_repo,
        error_repo=error_repo,
        eating_day_service=eating_day_service,
        sleep_repo=sleep_repo,
        workout_repo=workout_repo,
        self_care_repo=self_care_repo,
        landing_page_url=landing_page_url,
    )

    # Startup notification to admin
    admin_chat_id = tg.get("admin_chat_id", 2145100468)

    async def post_init(application):
        if admin_chat_id:
            try:
                await application.bot.send_message(
                    chat_id=admin_chat_id,
                    text=f"🚀 דוגרי v{VERSION}\n{VERSION_NOTES}",
                )
            except Exception:
                logger.exception("Failed to send startup message to admin")

    app.post_init = post_init

    # Startup
    webhook_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

    if webhook_domain:
        port = int(os.environ.get("PORT", 8443))
        webhook_url = f"https://{webhook_domain}/webhook"
        logger.info("Bot starting — webhook mode at %s (port %d)", webhook_url, port)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="webhook",
            webhook_url=webhook_url,
        )
    else:
        logger.info("Bot starting — polling mode")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
