"""
main.py - נקודת כניסה של בוט דוגרי.

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
from repositories.hook_schedule_repository import HookScheduleStore
from repositories.token_log_repository import TokenLogRepository
from services.eating_day_service import EatingDayService
from bot import create_bot

VERSION = "11.0.1"
VERSION_NOTES = "Fix simulator: deserialize Update with SimulatorBot so reply_text is captured"
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
            if isinstance(obj, dict):
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

    # Repositories - single "users" collection for both dashboard and bot
    user_repo = UserRepository(db["users"])
    food_repo = FoodRepository(db["food_entries"])
    feedback_repo = WeeklyFeedbackRepository(db["weekly_feedback"])
    error_repo = ErrorRepository(db["error_logs"])
    sleep_repo = SleepRepository(db["sleep_logs"])
    workout_repo = WorkoutRepository(db["workout_logs"])
    self_care_repo = SelfCareRepository(db["self_care_logs"])
    hook_schedule_store = HookScheduleStore(db["hook_schedule"])
    token_log_repo = TokenLogRepository(db["token_logs"])

    from repositories.feature_request_repository import FeatureRequestRepository
    feature_request_repo = FeatureRequestRepository(db["feature_requests"])
    from repositories.inappropriate_log_repository import InappropriateLogRepository
    inappropriate_log_repo = InappropriateLogRepository(db["inappropriate_logs"])

    # Services
    eating_day_service = EatingDayService(food_repo)

    # Analyzer
    food_analyzer = FoodAnalyzer(api_key=openai_cfg["api_key"])
    logger.info("GPT food analyzer ready")

    # Landing page URL
    landing_page_url = cfg.get("landing_page_url", "https://www.dugri.life")

    # Admin chat ID (used for startup notification and debug metadata)
    admin_chat_id = tg.get("admin_chat_id", 2145100468)

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
        hook_schedule_store=hook_schedule_store,
        landing_page_url=landing_page_url,
        feature_request_repo=feature_request_repo,
        admin_chat_id=admin_chat_id,
        token_log_repo=token_log_repo,
        emotional_support_config=cfg.get("emotional_support"),
        inappropriate_log_repo=inappropriate_log_repo,
    )

    # Startup notification to admin

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

    # Startup - webhook if public domain is set, polling otherwise.
    # On Railway (PORT set) without a public domain, we still need to
    # bind the port so Railway's health check doesn't kill the process.
    webhook_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    port = os.environ.get("PORT", "")

    # Simulator endpoint setup
    internal_secret = cfg.get("internal_secret", "")
    sim_route = None
    try:
        from simulate import make_simulate_handler
        sim_route = make_simulate_handler(
            app, mongo_uri, mongo_cfg["db_name"], internal_secret,
        )
        logger.info("Simulator endpoint registered at /internal/simulate")
    except Exception:
        logger.exception("Failed to set up simulator endpoint")

    if webhook_domain:
        port_num = int(port or 8443)
        webhook_url = f"https://{webhook_domain}/webhook"
        logger.info("Bot starting - webhook mode at %s (port %d)", webhook_url, port_num)

        if sim_route:
            # Manual webhook setup to add custom routes alongside the PTB webhook
            import asyncio

            async def _run_webhook_with_simulate():
                await app.initialize()
                await app.bot.set_webhook(url=webhook_url)
                await app.start()

                from telegram.ext._utils.webhookhandler import WebhookAppClass, WebhookServer
                webhook_app = WebhookAppClass("/webhook", app.bot, app.update_queue)
                # Add simulator route to the Tornado app
                webhook_app.add_handlers(r".*", [sim_route])

                httpd = WebhookServer("0.0.0.0", port_num, webhook_app, None)
                await httpd.serve_forever()

                try:
                    await app.post_init(app)
                except Exception:
                    logger.exception("post_init failed")

                # Block until stop signal
                stop_event = asyncio.Event()
                import signal
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        asyncio.get_event_loop().add_signal_handler(sig, stop_event.set)
                    except NotImplementedError:
                        pass  # Windows
                await stop_event.wait()

                await httpd.shutdown()
                await app.stop()
                await app.shutdown()

            asyncio.run(_run_webhook_with_simulate())
        else:
            app.run_webhook(
                listen="0.0.0.0",
                port=port_num,
                url_path="webhook",
                webhook_url=webhook_url,
            )
    elif port:
        # Railway without public domain - polling + Tornado server for
        # health checks and internal API (simulate endpoint)
        import threading
        import tornado.web
        import tornado.ioloop

        class _HealthHandler(tornado.web.RequestHandler):
            def get(self):
                self.write("ok")

        port_num = int(port)
        routes = [(r"/", _HealthHandler)]
        if sim_route:
            routes.append(sim_route)
        http_app = tornado.web.Application(routes)
        http_app.listen(port_num, address="0.0.0.0")

        def _run_tornado():
            tornado.ioloop.IOLoop.current().start()

        threading.Thread(target=_run_tornado, daemon=True).start()
        logger.info("Bot starting - polling mode + HTTP on port %d (health + simulate)", port_num)
        app.run_polling(drop_pending_updates=True)
    else:
        # Local dev - polling + simulate endpoint on separate port
        if sim_route:
            import asyncio
            import threading
            import tornado.web
            import tornado.ioloop

            def _start_simulate_server():
                sim_app = tornado.web.Application([sim_route])
                sim_app.listen(8081)
                logger.info("Simulator endpoint available at http://localhost:8081/internal/simulate")
                tornado.ioloop.IOLoop.current().start()

            threading.Thread(target=_start_simulate_server, daemon=True).start()

        logger.info("Bot starting - polling mode (local)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log startup crash to MongoDB so we can diagnose remotely
        import traceback
        tb = traceback.format_exc()
        logger.critical("STARTUP CRASH:\n%s", tb)
        try:
            cfg = load_config()
            mc = MongoClient(cfg["mongodb"]["uri"])
            from datetime import datetime, timezone
            mc[cfg["mongodb"]["db_name"]]["error_logs"].insert_one({
                "handler": "startup",
                "error_type": "StartupCrash",
                "error_message": str(tb)[-500:],
                "traceback": tb,
                "version": VERSION,
                "timestamp": datetime.now(timezone.utc),
            })
        except Exception:
            pass
        raise
