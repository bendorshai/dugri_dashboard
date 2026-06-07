"""
help_service.py — עונה על שאלות 'איך דוגרי עובד' ושאלות ידע עצמי.

טריפ שני נפרד כדי לא לטעון את prompt-הידע הגדול על כל הודעה.
משתמש במסמך הידע העצמי + היסטוריית שיחה לקונטקסט.

תלוי ב: analyzer, prompts.
נצרך על ידי: services/message_router_service.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from analyzer import FoodAnalyzer
from prompts import SELF_KNOWLEDGE_SYSTEM_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class HelpResponse(BaseModel):
    response_text: str
    knowledge_gap: bool = False


class HelpService:
    def __init__(self, analyzer: FoodAnalyzer, knowledge_path: Path | None = None):
        self._analyzer = analyzer
        self._knowledge_doc = ""
        if knowledge_path and knowledge_path.exists():
            self._knowledge_doc = knowledge_path.read_text(encoding="utf-8")

    def answer(
        self,
        question_text: str,
        recent_messages: list[dict] | None = None,
    ) -> HelpResponse:
        system_prompt = SELF_KNOWLEDGE_SYSTEM_PROMPT_TEMPLATE.format(
            knowledge_doc=self._knowledge_doc,
        )
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if recent_messages:
            for msg in recent_messages:
                role = "assistant" if msg.get("role") == "bot" else "user"
                messages.append({"role": role, "content": msg.get("text", "")})

        messages.append({"role": "user", "content": question_text})

        try:
            response = self._analyzer.answer_help(messages, HelpResponse, max_tokens=1000)
            result = response.choices[0].message.parsed
            if result is None:
                return HelpResponse(response_text="לא הצלחתי לענות.")
            return result
        except Exception:
            logger.exception("HelpService GPT call failed")
            return HelpResponse(response_text="לא הצלחתי לענות כרגע. נסה שוב.")
