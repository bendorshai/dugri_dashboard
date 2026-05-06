from __future__ import annotations

import json
import logging
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class FoodItem(BaseModel):
    description: str
    calories: int
    protein: int


class FoodAnalysisResult(BaseModel):
    items: list[FoodItem]
    total_calories: int
    total_protein: int


class CorrectionResult(BaseModel):
    corrected_description: str
    corrected_calories: int
    corrected_protein: int


class MessageParseResult(BaseModel):
    type: Literal["food", "correction", "unknown"]
    food: FoodAnalysisResult | None = None
    correction: CorrectionResult | None = None


class BulkCorrectionItem(BaseModel):
    row_index: int
    original_description: str
    corrected_description: str
    corrected_calories: int
    corrected_protein: int


class BulkCorrectionResult(BaseModel):
    corrections: list[BulkCorrectionItem]


PARSE_MESSAGE_SYSTEM_PROMPT = (
    "אתה מערכת ניתוח תזונתי. תפקידך לנתח הודעת טקסט מהמשתמש ולהחליט אם זו:\n"
    '1. "food" — הודעה על מאכל חדש שהמשתמש אכל\n'
    '2. "correction" — תיקון או עדכון לרשומה האחרונה (למשל "ההמבורגר היה 300 גרם לא 150", "תוסיף קטשופ")\n'
    '3. "unknown" — לא ברור\n\n'
    "כללי מזון:\n"
    "- אם המשתמש ציין כמות (גרמים), חשב לפי הכמות המדויקת.\n"
    "- אם לא ציין כמות, העריך מנה סטנדרטית.\n"
    "- היה מדויק ככל האפשר.\n"
    "- שמור על התיאור בעברית כפי שהמשתמש כתב.\n\n"
    "כללי תיקון:\n"
    "- אם המשתמש מתקן (משנה כמות, מוסיף פריט, מתקן טעות) — החזר type=correction.\n"
    "- בתיקון, החזר את התיאור המעודכן המלא (כולל חלקים שלא השתנו), ואת הקלוריות והחלבון המעודכנים.\n"
    "- אם אין רשומה קודמת לתיקון, התייחס כ-food חדש.\n"
)

FOOD_TEXT_SYSTEM_PROMPT = (
    "אתה מערכת ניתוח תזונתי. תפקידך לנתח תיאור מזון ולהעריך קלוריות וחלבון.\n\n"
    "כללים:\n"
    "- אם המשתמש ציין כמות (גרמים), חשב לפי הכמות המדויקת.\n"
    "- אם לא ציין כמות, העריך מנה סטנדרטית.\n"
    "- אם יש מספר מאכלים, פרט כל אחד בנפרד.\n"
    "- היה מדויק ככל האפשר אך העדף הערכה על פני שגיאה.\n"
    "- שמור על התיאור בעברית כפי שהמשתמש כתב.\n"
    "- החזר JSON מובנה עם items (רשימה), total_calories, total_protein.\n"
)

FOOD_PHOTO_SYSTEM_PROMPT = (
    "אתה מערכת ניתוח תזונתי מתמונות. זהה את המאכלים בתמונה והעריך קלוריות וחלבון.\n\n"
    "כללים:\n"
    "- זהה כל מאכל בנפרד.\n"
    "- העריך גודל מנה מהתמונה.\n"
    "- אם יש כיתוב נוסף מהמשתמש, השתמש בו לדיוק.\n"
    "- ענה בעברית.\n"
)

WEEKLY_FEEDBACK_SYSTEM_PROMPT = (
    "אתה מאמן תזונה חיובי ומעודד. תפקידך לתת משוב קצר (שורה אחת) על השבוע.\n\n"
    "כללים:\n"
    "- המשוב חייב להיות בעברית, עליז ומכבד.\n"
    "- שורה אחת בלבד.\n"
    "- עודד שינוי חיובי.\n"
    "- נתח את המשובים הקודמים שלך ואת תגובת המשתמש כדי לבחור את סגנון המשוב היעיל ביותר.\n\n"
    "החזר JSON עם:\n"
    "- feedback_text: המשוב למשתמש (שורה אחת)\n"
    "- insight: תובנה קצרה על מה עובד/לא עובד במשובים שלך\n"
    "- insight_category: קטגוריית התובנה (למשל positive_reinforcement, specific_goals)\n"
)

MEAL_SUGGESTION_SYSTEM_PROMPT = (
    "אתה יועץ תזונה. הצע 3 ארוחות בריאות שעונות על היעד.\n\n"
    "כללים:\n"
    "- כל ארוחה צריכה להיות מתחת ליתרת הקלוריות.\n"
    "- כל ארוחה צריכה לכסות את יתרת החלבון.\n"
    "- הצע ארוחות ריאליסטיות וקלות להכנה.\n"
    "- ענה בעברית.\n"
)

QA_SYSTEM_PROMPT = (
    "אתה יועץ תזונה. ענה על שאלות בהתבסס על היסטוריית האכילה.\n"
    "הנתונים מוצגים בפורמט CSV: תאריך, שעה, תיאור, קלוריות, חלבון.\n"
    "ענה בעברית. היה תמציתי וברור."
)

TARGET_SUGGESTION_SYSTEM_PROMPT = (
    "אתה יועץ תזונה מקצועי. בהתבסס על נתוני הגוף של המשתמש, "
    "הצע יעדי קלוריות וחלבון יומיים.\n"
    "החזר JSON עם target_calories ו-target_protein.\n"
    "התבסס על נוסחאות מקובלות כמו Mifflin-St Jeor.\n"
)

BULK_CORRECTION_SYSTEM_PROMPT = (
    "אתה מערכת תיקון רשומות תזונה. המשתמש מתאר טעות חוזרת ברשומות שלו.\n"
    "תפקידך לזהות את כל הרשומות שמתאימות לתיאור הטעות ולהחזיר ערכים מתוקנים.\n\n"
    "כללים:\n"
    "- סרוק את כל הרשומות וזהה את אלו שמתאימות לתיאור הטעות.\n"
    "- עבור כל רשומה שמתאימה, החזר: row_index (מספר השורה ברשימה, מתחיל מ-0), "
    "original_description, corrected_description, corrected_calories, corrected_protein.\n"
    "- אם אין רשומות שמתאימות, החזר רשימה ריקה.\n"
    "- חשב את הקלוריות והחלבון המתוקנים לפי התיקון שהמשתמש מתאר.\n"
)


class FoodAnalyzer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def analyze_food_text(self, text: str, today_str: str) -> FoodAnalysisResult | None:
        system = FOOD_TEXT_SYSTEM_PROMPT + f"\nהתאריך של היום: {today_str}\n"
        try:
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=FoodAnalysisResult,
                temperature=0,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT food analysis returned None for: %s", text[:80])
                return None
            return result
        except Exception:
            logger.exception("GPT food analysis failed for: %s", text[:80])
            return None

    def parse_message(
        self, text: str, today_str: str, last_entry: dict | None = None,
    ) -> MessageParseResult:
        """Classify a message as new food or correction to last entry."""
        system = PARSE_MESSAGE_SYSTEM_PROMPT + f"\nהתאריך של היום: {today_str}\n"
        if last_entry:
            system += (
                f"\nהרשומה האחרונה שנרשמה:\n"
                f"תיאור: {last_entry.get('description', '')}\n"
                f"קלוריות: {last_entry.get('calories', 0)}\n"
                f"חלבון: {last_entry.get('protein', 0)}\n"
            )
        else:
            system += "\nאין רשומה קודמת. התייחס לכל הודעה כ-food חדש.\n"

        try:
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=MessageParseResult,
                temperature=0,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT parse_message returned None for: %s", text[:80])
                return MessageParseResult(type="unknown")
            return result
        except Exception:
            logger.exception("GPT parse_message failed for: %s", text[:80])
            return MessageParseResult(type="unknown")

    def analyze_food_photo(
        self, base64_image: str, today_str: str, caption: str = "",
    ) -> FoodAnalysisResult | None:
        system = FOOD_PHOTO_SYSTEM_PROMPT + f"\nהתאריך של היום: {today_str}\n"
        user_content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
        ]
        if caption:
            user_content.append({"type": "text", "text": caption})

        try:
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                response_format=FoodAnalysisResult,
                temperature=0,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT photo analysis returned None")
                return None
            return result
        except Exception:
            logger.exception("GPT photo analysis failed")
            return None

    def generate_weekly_feedback(
        self,
        week_csv: str,
        targets: dict,
        past_feedbacks: list[str],
        user_insights: list[str],
    ) -> dict | None:
        feedbacks_block = "\n".join(f"- {f}" for f in past_feedbacks) if past_feedbacks else "(אין משובים קודמים)"
        insights_block = "\n".join(f"- {i}" for i in user_insights) if user_insights else "(אין תובנות קודמות)"

        user_msg = (
            f"היסטוריית אכילה של 7 ימים:\n{week_csv}\n\n"
            f"יעדים: {targets.get('calories', 0)} קלוריות, {targets.get('protein', 0)}g חלבון\n\n"
            f"המשובים האחרונים שלך:\n{feedbacks_block}\n\n"
            f"תובנות על תגובת המשתמש:\n{insights_block}"
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": WEEKLY_FEEDBACK_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_tokens=500,
            )
            content = response.choices[0].message.content.strip()
            return json.loads(content)
        except Exception:
            logger.exception("GPT weekly feedback failed")
            return None

    def suggest_meals(
        self,
        remaining_calories: int,
        remaining_protein: int,
        today_entries: str,
    ) -> str:
        user_msg = (
            f"נותרו היום: {remaining_calories} קלוריות, {remaining_protein}g חלבון\n"
            f"מה שנאכל היום:\n{today_entries}"
        )
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": MEAL_SUGGESTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_tokens=1000,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("GPT meal suggestions failed")
            return ""

    def answer_question(
        self,
        question: str,
        week_csv: str,
        targets: dict,
    ) -> str:
        user_msg = (
            f"הנתונים:\n{week_csv}\n\n"
            f"יעדים: {targets.get('calories', 0)} קלוריות, {targets.get('protein', 0)}g חלבון\n\n"
            f"שאלה: {question}"
        )
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": QA_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                max_tokens=1000,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("GPT Q&A failed for: %s", question)
            return ""

    def suggest_targets(self, height_cm: int, weight_kg: int, age: int) -> dict | None:
        user_msg = f"גובה: {height_cm} ס\"מ\nמשקל: {weight_kg} ק\"ג\nגיל: {age}"
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

    def analyze_bulk_correction(
        self, correction_text: str, entries_csv: str,
    ) -> list[BulkCorrectionItem]:
        user_msg = (
            f"רשומות האכילה:\n{entries_csv}\n\n"
            f"תיקון מהמשתמש: {correction_text}"
        )
        try:
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": BULK_CORRECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format=BulkCorrectionResult,
                temperature=0,
            )
            result = response.choices[0].message.parsed
            if result is None:
                return []
            return result.corrections
        except Exception:
            logger.exception("GPT bulk correction failed")
            return []
