"""
conversational_service.py - Handles all non-actionable user messages.

Questions, discussion, negotiation, multi-intent detection, general chat.
This module is READ-ONLY: it never mutates state (no food logging, no toggle
changes, no goal setting). It reads and responds.

Uses OpenAI function calling so the LLM can request historical data on demand
rather than receiving 30 days of history on every message.

Depends on: analyzer, prompts, repositories.
Used by: handlers/base.py (dispatched when Router returns 'conversational').
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from analyzer import FoodAnalyzer
from prompts import CONVERSATIONAL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

HISTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_food_history",
        "description": (
            "Fetch the user's food and habit log history. "
            "For 'yesterday' questions use days=2. "
            "For 'today' questions use days=1. "
            "For specific day names (e.g. 'Monday') use days=7. "
            "For 'this week' use days=7. "
            "For trends, 'this month', or '10 days' use days=10-30."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": (
                        "How many days to include counting back from today. "
                        "1=today only, 2=today+yesterday, 7=last week."
                    ),
                },
            },
            "required": ["days"],
        },
    },
}

# Type alias: callback that takes (days: int) -> formatted history string
HistoryFetcher = Callable[[int], str]


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
        toggle_state: str,
        today_date: str,
        recent_messages: list[dict] | None = None,
        fetch_history: HistoryFetcher | None = None,
    ) -> str:
        """Generate a conversational response.

        Args:
            user_text: The current user message.
            user_context: Formatted user profile (name, targets, body stats).
            toggle_state: Current toggle states (Hebrew).
            today_date: Today's date and day name, e.g. "13/06/2026 (יום שישי)".
            recent_messages: Conversation history.
            fetch_history: Callback to fetch N days of food/habit history.
                           Called only if the LLM requests it via function calling.

        Returns:
            Plain text response in Hebrew.
        """
        system_prompt = CONVERSATIONAL_SYSTEM_PROMPT.format(
            knowledge_doc=self._knowledge_doc,
            user_context=user_context or "לא זמין",
            toggle_state=toggle_state or "לא זמין",
            today_date=today_date,
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if recent_messages:
            for msg in recent_messages:
                role = "assistant" if msg.get("role") == "bot" else "user"
                messages.append({"role": role, "content": msg.get("text", "")})

        messages.append({"role": "user", "content": user_text})

        try:
            if fetch_history:
                # With tools: converse() returns the raw message object
                response = self._analyzer.converse(
                    messages, max_tokens=500, tools=[HISTORY_TOOL],
                )
                if response.tool_calls:
                    return self._handle_tool_call(
                        messages, response, fetch_history,
                    )
                return response.content or ""
            else:
                # Without tools: converse() returns a plain string
                return self._analyzer.converse(messages, max_tokens=500)

        except Exception:
            logger.exception("ConversationalService GPT call failed")
            return "לא הצלחתי לענות כרגע. נסה שוב."

    def _handle_tool_call(
        self,
        messages: list[dict],
        assistant_response,
        fetch_history: HistoryFetcher,
    ) -> str:
        """Execute tool call and make a second LLM call with the result."""
        tool_call = assistant_response.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        # Minimum 7 days: LLMs often under-request for day-name queries
        # ("Monday" needs 7 days back). The extra CSV lines are cheap.
        days = min(max(args.get("days", 7), 7), 30)

        history_text = fetch_history(days)

        # Append assistant message with tool call + tool result
        messages.append(assistant_response.model_dump())
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": history_text,
        })

        try:
            return self._analyzer.converse(messages, max_tokens=500)
        except Exception:
            logger.exception("ConversationalService follow-up call failed")
            return "לא הצלחתי לענות כרגע. נסה שוב."
