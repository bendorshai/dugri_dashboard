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
                      bot: Any = None) -> dict:
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
                self.set_status(400)
                self.write(json.dumps({"error": "user not linked to telegram"}))
                return

            # Build fake update
            from telegram import Update
            update_dict = build_fake_update(tid, text=text,
                                            callback_data=callback_data,
                                            bot=self._app.bot)
            update = Update.de_json(update_dict, self._app.bot)

            # Swap bot with simulator
            sim_bot = SimulatorBot(self._app.bot)
            original_bot = self._app.bot

            try:
                # Monkey-patch: replace the bot on the application
                self._app._bot = sim_bot
                await self._app.process_update(update)
            except Exception:
                logger.exception("Simulator: error processing update")
            finally:
                self._app._bot = original_bot

            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"responses": sim_bot.captured}))

    return (
        r"/internal/simulate",
        SimulateHandler,
        {"app": application, "uri": mongo_uri, "db": db_name, "secret": internal_secret},
    )
