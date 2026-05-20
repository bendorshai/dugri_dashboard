"""
help_service.py — עונה על שאלות 'איך דוגרי עובד'.

טריפ שני נפרד כדי לא לטעון את prompt-הידע הגדול על כל הודעה.

תלוי ב: analyzer.
נצרך על ידי: services/message_router_service.
"""

from __future__ import annotations

from analyzer import FoodAnalyzer
from prompts import DUGRI_HELP_SYSTEM_PROMPT


class HelpService:
    def __init__(self, analyzer: FoodAnalyzer):
        self._analyzer = analyzer

    def answer(self, question_text: str) -> str:
        try:
            response = self._analyzer.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": DUGRI_HELP_SYSTEM_PROMPT},
                    {"role": "user", "content": question_text},
                ],
                temperature=0,
                max_tokens=1000,
            )
            return response.choices[0].message.content or "לא הצלחתי לענות."
        except Exception:
            return "לא הצלחתי לענות כרגע. נסה שוב."
