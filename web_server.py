"""
web_server.py — Starlette HTTP server for Telegram webhook + internal API.

Replaces PTB's built-in run_webhook() so we can serve both Telegram
updates and dashboard-to-bot internal endpoints on the same port.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from telegram import Update

from internal_api import validate_secret, handle_target_change, handle_admin_outreach

logger = logging.getLogger(__name__)


def create_web_app(
    ptb_app: Any,
    internal_secret: str,
    webhook_path: str = "/webhook",
) -> Starlette:
    """Create a Starlette app that handles Telegram webhook + internal routes."""

    async def telegram_webhook(request: Request) -> Response:
        """Receive Telegram updates and push to PTB's update queue."""
        try:
            data = await request.json()
            update = Update.de_json(data=data, bot=ptb_app.bot)
            await ptb_app.update_queue.put(update)
            return Response(status_code=200)
        except Exception:
            logger.exception("Error processing Telegram update")
            return Response(status_code=500)

    async def notify_target_update(request: Request) -> JSONResponse:
        """Handle target change notification from dashboard."""
        secret = request.headers.get("X-Internal-Secret", "")
        if not validate_secret(secret, internal_secret):
            return JSONResponse({"error": "unauthorized"}, status_code=403)

        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)

        tid = data.get("telegram_user_id")
        old_targets = data.get("old_targets", {})
        new_targets = data.get("new_targets", {})

        if not tid:
            return JSONResponse({"error": "missing telegram_user_id"}, status_code=400)

        # Get analyzer from PTB's bot_data
        analyzer = ptb_app.bot_data.get("analyzer")
        if not analyzer:
            logger.error("Analyzer not found in bot_data")
            return JSONResponse({"error": "analyzer not available"}, status_code=500)

        result = await handle_target_change(
            telegram_user_id=tid,
            old_targets=old_targets,
            new_targets=new_targets,
            analyzer=analyzer,
            bot=ptb_app.bot,
        )

        if result:
            return JSONResponse({"ok": True, "message": result})
        return JSONResponse({"error": "failed to send"}, status_code=502)

    async def admin_outreach(request: Request) -> JSONResponse:
        """Send outreach message to a user on behalf of the founder."""
        secret = request.headers.get("X-Internal-Secret", "")
        if not validate_secret(secret, internal_secret):
            return JSONResponse({"error": "unauthorized"}, status_code=403)

        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)

        tid = data.get("telegram_user_id")
        if not tid:
            return JSONResponse({"error": "missing telegram_user_id"}, status_code=400)

        name = data.get("name", "")
        founder_username = data.get("founder_telegram_username", "")

        ok = await handle_admin_outreach(
            telegram_user_id=tid,
            name=name,
            founder_telegram_username=founder_username,
            bot=ptb_app.bot,
        )

        if ok:
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "failed to send"}, status_code=502)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    routes = [
        Route(webhook_path, telegram_webhook, methods=["POST"]),
        Route("/internal/notify-target-update", notify_target_update, methods=["POST"]),
        Route("/internal/admin-outreach", admin_outreach, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]

    return Starlette(routes=routes)
