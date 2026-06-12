"""
conversational_service.py - Handles all non-actionable user messages.

Questions, discussion, negotiation, multi-intent detection, general chat.
This module is READ-ONLY: it never mutates state (no food logging, no toggle
changes, no goal setting). It reads and responds.

Depends on: analyzer, prompts, repositories.
Used by: handlers/base.py (dispatched when Router returns 'conversational').
"""

from __future__ import annotations

import logging
from pathlib import Path

from analyzer import FoodAnalyzer
from prompts import CONVERSATIONAL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class ConversationalService:
    def __init__(
        self,
        analyzer: FoodAnalyzer,
        knowledge_path: Path | None = None,
    ):
        self._analyzer = analyzer
        self._knowledge_doc = ""
        if knowledge_path and knowledge_path.exists():
            self._knowledge_doc = knowledge_path.read_text(encoding="utf-8")

    def respond(
        self,
        user_text: str,
        user_context: str,
        data_summary: str,
        toggle_state: str,
        recent_messages: list[dict] | None = None,
    ) -> str:
        """Generate a conversational response.

        Args:
            user_text: The current user message.
            user_context: Formatted user profile (name, targets, body stats).
            data_summary: Last 30 days of entries formatted as text.
            toggle_state: Current toggle states (Hebrew).
            recent_messages: Conversation history.

        Returns:
            Plain text response in Hebrew.
        """
        system_prompt = CONVERSATIONAL_SYSTEM_PROMPT.format(
            knowledge_doc=self._knowledge_doc,
            user_context=user_context or "לא זמין",
            data_summary=data_summary or "אין נתונים",
            toggle_state=toggle_state or "לא זמין",
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if recent_messages:
            for msg in recent_messages:
                role = "assistant" if msg.get("role") == "bot" else "user"
                messages.append({"role": role, "content": msg.get("text", "")})

        messages.append({"role": "user", "content": user_text})

        try:
            return self._analyzer.converse(messages, max_tokens=500)
        except Exception:
            logger.exception("ConversationalService GPT call failed")
            return "לא הצלחתי לענות כרגע. נסה שוב."
