from __future__ import annotations

import json
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

TARGET_SUGGESTION_SYSTEM_PROMPT = (
    "אתה יועץ תזונה מקצועי. בהתבסס על נתוני הגוף של המשתמש, "
    "הצע יעדי קלוריות וחלבון יומיים.\n"
    "החזר JSON עם target_calories ו-target_protein.\n"
    "התבסס על נוסחאות מקובלות כמו Mifflin-St Jeor.\n"
)


class DashboardAnalyzer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def suggest_targets(self, height_cm: int, weight_kg: int, age: int) -> dict | None:
        user_msg = f'גובה: {height_cm} ס"מ\nמשקל: {weight_kg} ק"ג\nגיל: {age}'
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": TARGET_SUGGESTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                max_tokens=200,
            )
            content = response.choices[0].message.content.strip()
            return json.loads(content)
        except Exception:
            logger.exception("GPT target suggestion failed")
            return None
