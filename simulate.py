"""
simulate.py - Admin simulator endpoint for dashboard testing.

Thin transport replacement: swaps the Telegram API layer while running
messages through the exact same handler pipeline (classifier, GPT,
toggles, trial - everything).

SimulatorBot wraps the real telegram.Bot, overriding outgoing methods
to capture responses instead of sending to Telegram.
"""

from __future__ import annotations

import asyncio
import json
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient

logger = logging.getLogger(__name__)


class SimulatorBot:
    """Wraps a real telegram.Bot, capturing outgoing messages instead of sending."""

    def __init__(self, real_bot: Any):
        self._real_bot = real_bot
        self.captured: list[dict] = []
        self._msg_id_counter = 1000

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real_bot, name)

    def _next_msg_id(self) -> int:
        self._msg_id_counter += 1
        return self._msg_id_counter

    def _serialize_reply_markup(self, reply_markup: Any) -> dict | None:
        if reply_markup is None:
            return None
        if hasattr(reply_markup, "to_dict"):
            return reply_markup.to_dict()
        if hasattr(reply_markup, "inline_keyboard"):
            return {
                "inline_keyboard": [
                    [
                        {k: v for k, v in btn.items() if v is not None}
                        if isinstance(btn, dict)
                        else {k: v for k, v in btn.to_dict().items() if v is not None}
                        for btn in row
                    ]
                    for row in reply_markup.inline_keyboard
                ]
            }
        return None

    def _make_fake_message(self, chat_id: int, text: str) -> Any:
        """Build a minimal fake Message object that satisfies downstream code."""
        from telegram import Chat, Message, User

        msg_id = self._next_msg_id()
        return Message(
            message_id=msg_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=self._real_bot.id, is_bot=True, first_name="Dugri"),
            text=text,
        )

    async def send_message(self, chat_id=None, text="", reply_markup=None, **kwargs):
        self.captured.append({
            "type": "message",
            "text": text,
            "reply_markup": self._serialize_reply_markup(reply_markup),
        })
        return self._make_fake_message(chat_id or 0, text)

    async def send_chat_action(self, *args, **kwargs):
        pass

    async def answer_callback_query(self, *args, **kwargs):
        pass

    async def edit_message_text(self, text="", chat_id=None, message_id=None,
                                reply_markup=None, **kwargs):
        self.captured.append({
            "type": "edit",
            "text": text,
            "reply_markup": self._serialize_reply_markup(reply_markup),
        })
        return self._make_fake_message(chat_id or 0, text)

    async def edit_message_reply_markup(self, chat_id=None, message_id=None,
                                        reply_markup=None, **kwargs):
        self.captured.append({
            "type": "edit_markup",
            "text": "",
            "reply_markup": self._serialize_reply_markup(reply_markup),
        })
        return True

    async def get_me(self):
        return await self._real_bot.get_me()


def build_fake_update(telegram_user_id: int, text: str | None = None,
                      callback_data: str | None = None,
                      bot: Any = None,
                      reply_to_message_id: int | None = None,
                      reply_to_text: str | None = None) -> dict:
    """Build a raw Telegram Update dict for deserialization."""
    update_id = int(datetime.now(timezone.utc).timestamp() * 1000) % 999999999

    user_dict = {
        "id": telegram_user_id,
        "is_bot": False,
        "first_name": "TestUser",
    }
    chat_dict = {
        "id": telegram_user_id,
        "type": "private",
    }

    if callback_data:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": str(update_id),
                "from": user_dict,
                "chat_instance": str(telegram_user_id),
                "data": callback_data,
                "message": {
                    "message_id": 1,
                    "date": int(datetime.now(timezone.utc).timestamp()),
                    "chat": chat_dict,
                    "from": {
                        "id": bot.id if bot else 0,
                        "is_bot": True,
                        "first_name": "Dugri",
                    },
                    "text": "menu",
                },
            },
        }
    else:
        msg = {
            "message_id": update_id % 99999,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": chat_dict,
            "from": user_dict,
            "text": text or "",
        }
        # Add bot_command entity so PTB's CommandHandler matches /commands
        if text and text.startswith("/"):
            cmd = text.split()[0]
            msg["entities"] = [{
                "type": "bot_command",
                "offset": 0,
                "length": len(cmd),
            }]
        # Add reply_to_message so the bot sees message.reply_to_message.text
        if reply_to_message_id and reply_to_text is not None:
            msg["reply_to_message"] = {
                "message_id": reply_to_message_id,
                "date": int(datetime.now(timezone.utc).timestamp()),
                "chat": chat_dict,
                "from": {
                    "id": bot.id if bot else 0,
                    "is_bot": True,
                    "first_name": "Dugri",
                },
                "text": reply_to_text,
            }
        return {
            "update_id": update_id,
            "message": msg,
        }


def make_simulate_handler(application: Any, mongo_uri: str, db_name: str,
                          internal_secret: str):
    """Create a Tornado RequestHandler class for /internal/simulate.

    Returns a (pattern, handler_class, init_kwargs) tuple for Tornado routing.
    """
    import tornado.web

    class SimulateHandler(tornado.web.RequestHandler):
        SUPPORTED_METHODS = ("POST",)

        def initialize(self, app, uri, db, secret):
            self._app = app
            self._mongo_uri = uri
            self._db_name = db
            self._secret = secret

        async def post(self):
            # Validate secret
            req_secret = self.request.headers.get("X-Internal-Secret", "")
            if self._secret and not hmac.compare_digest(req_secret, self._secret):
                self.set_status(403)
                self.write(json.dumps({"error": "forbidden"}))
                return

            body = json.loads(self.request.body.decode())
            email = body.get("email")
            text = body.get("text")
            callback_data = body.get("callback_data")
            reply_to_message_id = body.get("reply_to_message_id")
            reply_to_text = body.get("reply_to_text")

            if not email:
                self.set_status(400)
                self.write(json.dumps({"error": "email required"}))
                return
            if not text and not callback_data:
                self.set_status(400)
                self.write(json.dumps({"error": "text or callback_data required"}))
                return

            # Look up user
            client = MongoClient(self._mongo_uri)
            db = client[self._db_name]
            user = db["users"].find_one({"_id": email})
            client.close()

            if not user:
                self.set_status(404)
                self.write(json.dumps({"error": "user not found"}))
                return

            tid = user.get("telegram_user_id")
            if not tid:
                # Unlinked user (e.g. after reset) - use a stable fake ID
                # so /start {token} can trigger the linking flow
                tid = 999999999

            # Build simulator bot FIRST so Update objects reference it
            # (message.reply_text() uses the bot stored in the Message)
            sim_bot = SimulatorBot(self._app.bot)
            original_bot = self._app.bot

            from telegram import Update
            update_dict = build_fake_update(tid, text=text,
                                            callback_data=callback_data,
                                            bot=self._app.bot,
                                            reply_to_message_id=reply_to_message_id,
                                            reply_to_text=reply_to_text)
            update = Update.de_json(update_dict, sim_bot)

            try:
                self._app._bot = sim_bot
                await self._app.process_update(update)
            except Exception:
                logger.exception("Simulator: error processing update")
            finally:
                self._app._bot = original_bot

            # Ensure captured responses are persisted to recent_messages.
            # handle_message saves via _save_bot_message, but other
            # handlers (start_handler, callbacks) use reply_text which
            # doesn't save. Check DB and save any missing bot messages.
            if sim_bot.captured:
                save_client = MongoClient(self._mongo_uri)
                save_db = save_client[self._db_name]
                current = save_db["users"].find_one(
                    {"telegram_user_id": tid}, {"recent_messages": 1},
                )
                existing_texts = set()
                if current:
                    for m in current.get("recent_messages", []):
                        if m.get("role") == "bot":
                            existing_texts.add(m.get("text", "")[:100])

                msgs_to_save = []
                for cap in sim_bot.captured:
                    txt = cap.get("text", "")
                    if txt and txt[:100] not in existing_texts:
                        msgs_to_save.append({
                            "role": "bot",
                            "text": txt[:500],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })

                if msgs_to_save:
                    save_db["users"].update_one(
                        {"telegram_user_id": tid},
                        {"$push": {
                            "recent_messages": {
                                "$each": msgs_to_save,
                                "$slice": -12,
                            },
                        }},
                    )
                save_client.close()

            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"responses": sim_bot.captured}))

    return (
        r"/internal/simulate",
        SimulateHandler,
        {"app": application, "uri": mongo_uri, "db": db_name, "secret": internal_secret},
    )


# ---------------------------------------------------------------------------
# Simulate-tick: run the scheduler for a single user with a fake clock
# ---------------------------------------------------------------------------

class _FakeJobData:
    """Minimal stand-in for context.job so scheduler code can read .data."""
    def __init__(self, data: dict):
        self.data = data


class _FakeContext:
    """Minimal stand-in for PTB CallbackContext for scheduler functions."""
    def __init__(self, bot, job_data: dict):
        self.bot = bot
        self.job = _FakeJobData(job_data)


def make_simulate_tick_handler(application: Any, mongo_uri: str, db_name: str,
                               internal_secret: str):
    """Create a Tornado RequestHandler for /internal/simulate-tick.

    Runs the scheduler's per-user checks with a fake clock, capturing
    outgoing messages via SimulatorBot instead of sending to Telegram.
    """
    import tornado.web

    class SimulateTickHandler(tornado.web.RequestHandler):
        SUPPORTED_METHODS = ("POST",)

        def initialize(self, app, uri, db, secret):
            self._app = app
            self._mongo_uri = uri
            self._db_name = db
            self._secret = secret

        async def post(self):
            req_secret = self.request.headers.get("X-Internal-Secret", "")
            if self._secret and not hmac.compare_digest(req_secret, self._secret):
                self.set_status(403)
                self.write(json.dumps({"error": "forbidden"}))
                return

            body = json.loads(self.request.body.decode())
            email = body.get("email")
            fake_now_str = body.get("fake_now")

            if not email:
                self.set_status(400)
                self.write(json.dumps({"error": "email required"}))
                return
            if not fake_now_str:
                self.set_status(400)
                self.write(json.dumps({"error": "fake_now required"}))
                return

            # Parse fake_now as UTC-aware datetime
            try:
                fake_now = datetime.fromisoformat(fake_now_str.replace("Z", "+00:00"))
                if fake_now.tzinfo is None:
                    fake_now = fake_now.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                self.set_status(400)
                self.write(json.dumps({"error": "invalid fake_now format"}))
                return

            # Get services from the running poller job
            poller_jobs = self._app.job_queue.get_jobs_by_name("global_poller")
            if not poller_jobs:
                self.set_status(500)
                self.write(json.dumps({"error": "poller not running"}))
                return
            job_data = poller_jobs[0].data

            user_repo = job_data["user_repo"]
            toggle_service = job_data["toggle_service"]

            # Look up user by email, build profile
            profile = user_repo.find_one({"_id": email})
            if not profile:
                self.set_status(404)
                self.write(json.dumps({"error": "user not found"}))
                return

            tid = profile.telegram_user_id
            if not tid:
                self.set_status(400)
                self.write(json.dumps({"error": "user not linked (no telegram_user_id)"}))
                return

            # Build SimulatorBot to capture outgoing messages
            sim_bot = SimulatorBot(self._app.bot)
            fake_context = _FakeContext(sim_bot, job_data)

            from scheduler import _check_trial_expiry_message, _check_user_hooks

            # Run trial expiry check
            trial_service = job_data.get("trial_service")
            if trial_service:
                try:
                    await _check_trial_expiry_message(
                        fake_context, profile, user_repo, toggle_service,
                        trial_service,
                        analyzer=job_data.get("analyzer"),
                        gem_service=job_data.get("gem_service"),
                        feedback_service=job_data.get("feedback_service"),
                        admin_chat_id=0,
                        landing_page_url=job_data.get("landing_page_url", ""),
                        food_repo=job_data.get("food_repo"),
                        sleep_repo=job_data.get("sleep_repo"),
                        workout_repo=job_data.get("workout_repo"),
                        self_care_repo=job_data.get("self_care_repo"),
                        now_override=fake_now,
                    )
                except Exception:
                    logger.exception("Simulate-tick: trial expiry check failed")

            # Run user hooks (habits, eating window, re-engagement, gems, reveals)
            try:
                await _check_user_hooks(
                    fake_context, profile, user_repo, toggle_service,
                    goal_service=job_data.get("goal_service"),
                    eating_day_svc=job_data.get("eating_day_service"),
                    hook_schedule_store=job_data.get("hook_schedule_store"),
                    admin_chat_id=0,
                    food_repo=job_data.get("food_repo"),
                    now_override=fake_now,
                )
            except Exception:
                logger.exception("Simulate-tick: user hooks check failed")

            # Persist captured responses to recent_messages
            if sim_bot.captured:
                save_client = MongoClient(self._mongo_uri)
                save_db = save_client[self._db_name]
                msgs_to_save = []
                for cap in sim_bot.captured:
                    txt = cap.get("text", "")
                    if txt:
                        msgs_to_save.append({
                            "role": "bot",
                            "text": txt[:500],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                if msgs_to_save:
                    save_db["users"].update_one(
                        {"telegram_user_id": tid},
                        {"$push": {
                            "recent_messages": {
                                "$each": msgs_to_save,
                                "$slice": -12,
                            },
                        }},
                    )
                save_client.close()

            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"responses": sim_bot.captured}))

    return (
        r"/internal/simulate-tick",
        SimulateTickHandler,
        {"app": application, "uri": mongo_uri, "db": db_name, "secret": internal_secret},
    )
