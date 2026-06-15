from __future__ import annotations

import contextvars
import json
import logging
from typing import Callable, Literal

from openai import OpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TokenCallback = Callable[[str, int, int], None]  # (model, prompt_tokens, completion_tokens)

# Context-scoped token callback. Set once at handler entry point;
# _parse/_create pick it up automatically for all downstream GPT calls.
_token_callback_var: contextvars.ContextVar[TokenCallback | None] = contextvars.ContextVar(
    "_token_callback_var", default=None,
)


class FoodItem(BaseModel):
    description: str
    estimated_grams: int
    calories: int
    protein: int


class FoodAnalysisResult(BaseModel):
    items: list[FoodItem]
    total_calories: int
    total_protein: int


class TimedFoodGroup(BaseModel):
    temporal_label: str
    date: str
    time: str
    items: list[FoodItem]
    total_calories: int
    total_protein: int


class TimedFoodAnalysisResult(BaseModel):
    groups: list[TimedFoodGroup]


class FoodPhotoResult(BaseModel):
    items: list[FoodItem]
    total_calories: int
    total_protein: int
    photo_tips: list[str]
    unidentified_items: list[str] = Field(default_factory=list)


class CorrectionFoodItem(FoodItem):
    change_type: Literal["unchanged", "modified", "added", "removed"] = "unchanged"


class CorrectionResult(BaseModel):
    items: list[CorrectionFoodItem]
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


class WeeklyFeedbackResult(BaseModel):
    feedback_text: str
    discovered_pattern: str | None = None
    pattern_summary: str | None = None


class NormalizedActivity(BaseModel):
    """GPT output for self-care activity normalization."""
    activity_name: str


class HabitEntry(BaseModel):
    """A single habit log entry with temporal context.

    Used for multi-entry and mixed-type messages, e.g.,
    "שלשום התאמנתי, אתמול הלכתי לישון ב-22:00, והיום אכלתי צ'יזבורגר"
    """
    habit_type: Literal["sleep", "workout", "self_care"]
    temporal_label: str
    date: str
    sleep_time: str | None = None
    workout_note: str | None = None
    self_care_description: str | None = None


class MessageClassification(BaseModel):
    type: Literal[
        "meal", "correction", "sleep", "workout", "self_care",
        "help", "answer_question", "feedback_request",
        "feedback_reaction",
        "toggle_cancel", "toggle_activate",
        "conversation_reply", "name_declaration", "gender_declaration",
        "emotional",
        "unrelated",
        "none",  # internal only: error/timeout fallback, never returned by LLM
    ]
    meal: TimedFoodAnalysisResult | None = None
    correction: CorrectionResult | None = None
    sleep_time: str | None = None
    workout_note: str | None = None
    self_care_description: str | None = None
    habit_entries: list[HabitEntry] | None = None
    question_text: str | None = None
    toggle_name: str | None = None
    declared_name: str | None = None
    declared_gender: Literal["male", "female", "other"] | None = None
    freeform_response: str | None = None
    refusal_tone: Literal["sharp", "soft"] | None = None
    emotional_context: bool = False
    empathy_reflection: str | None = None


class RouterClassification(BaseModel):
    """Slim Router output - classifies message type and extracts meal data inline.

    The Router's job is to classify AND extract food data for meals (80% of traffic).
    For all non-meal types, only the type and optional toggle_name are populated.
    No emotion detection, no habit extraction, no empathy generation.
    """
    type: Literal[
        "meal", "opt_in", "correction",
        "name_declaration", "gender_declaration", "sleep", "workout", "self_care", "emotional",
        "feedback_request", "feedback_reaction", "conversational",
        "inappropriate",
    ]
    meal: TimedFoodAnalysisResult | None = None  # populated only for type=meal
    toggle_name: str | None = None  # for opt_in, when Router can identify which habit
    declared_gender: Literal["male", "female", "other"] | None = None  # for gender_declaration


from prompts import (
    BULK_CORRECTION_SYSTEM_PROMPT,
    CLASSIFIER_SYSTEM_PROMPT,
    CORRECTION_PHOTO_ADDENDUM,
    CORRECTION_SYSTEM_PROMPT,
    EXTRACT_BODY_STATS_PROMPT,
    EXTRACT_EATING_WINDOW_PROMPT,
    EXTRACT_NUTRITION_TARGETS_PROMPT,
    EXTRACT_SLEEP_TIME_PROMPT,
    EXTRACT_WORKOUT_COUNT_PROMPT,
    FOOD_PHOTO_SYSTEM_PROMPT,
    FOOD_TEXT_SYSTEM_PROMPT,
    GEM_DRESSING_PROMPT,
    MEAL_SUGGESTION_SYSTEM_PROMPT,
    PARSE_MESSAGE_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    TARGET_SUGGESTION_SYSTEM_PROMPT,
    ENHANCED_WEEKLY_SUMMARY_PROMPT,
    NORMALIZE_SELF_CARE_PROMPT,
)

_EXTRACTION_PROMPTS = {
    "body_stats": EXTRACT_BODY_STATS_PROMPT,
    "sleep_time": EXTRACT_SLEEP_TIME_PROMPT,
    "workout_count": EXTRACT_WORKOUT_COUNT_PROMPT,
    "eating_window": EXTRACT_EATING_WINDOW_PROMPT,
    "nutrition_targets": EXTRACT_NUTRITION_TARGETS_PROMPT,
}


class FoodAnalyzer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def _parse(self, *, on_usage: TokenCallback | None = None, **kwargs):
        """Wrapper for client.beta.chat.completions.parse with usage reporting."""
        response = self.client.beta.chat.completions.parse(**kwargs)
        cb = on_usage or _token_callback_var.get(None)
        if cb and response.usage:
            cb(kwargs["model"], response.usage.prompt_tokens, response.usage.completion_tokens)
        return response

    def _create(self, *, on_usage: TokenCallback | None = None, **kwargs):
        """Wrapper for client.chat.completions.create with usage reporting."""
        response = self.client.chat.completions.create(**kwargs)
        cb = on_usage or _token_callback_var.get(None)
        if cb and response.usage:
            cb(kwargs["model"], response.usage.prompt_tokens, response.usage.completion_tokens)
        return response

    def normalize_self_care_activity(self, raw_description: str,
                                     on_usage: TokenCallback | None = None) -> str | None:
        """Normalize a free-text self-care description to a canonical activity name.

        Returns a noun-form Hebrew string (e.g. "הליכה לים"), or None on failure.
        """
        try:
            response = self._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": NORMALIZE_SELF_CARE_PROMPT},
                    {"role": "user", "content": raw_description},
                ],
                response_format=NormalizedActivity,
                temperature=0,
                on_usage=on_usage,
            )
            return response.choices[0].message.parsed.activity_name
        except Exception:
            logger.warning("Failed to normalize self-care activity", exc_info=True)
            return None

    def analyze_food_text(self, text: str, today_str: str, day_name: str = "",
                          on_usage: TokenCallback | None = None) -> TimedFoodAnalysisResult | None:
        date_line = f"\nהתאריך של היום: {today_str}"
        if day_name:
            date_line += f" (יום {day_name})"
        date_line += "\n"
        system = FOOD_TEXT_SYSTEM_PROMPT + date_line
        try:
            response = self._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=TimedFoodAnalysisResult,
                temperature=0,
                on_usage=on_usage,
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
        on_usage: TokenCallback | None = None,
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
            response = self._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=MessageParseResult,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT parse_message returned None for: %s", text[:80])
                return MessageParseResult(type="unknown")
            return result
        except Exception:
            logger.exception("GPT parse_message failed for: %s", text[:80])
            return MessageParseResult(type="unknown")

    def classify_message(
        self, text: str, today_str: str, last_entry: dict | None = None,
        recent_messages: list[dict] | None = None,
        toggle_state: str | None = None,
        reply_context: str | None = None,
        day_name: str = "",
        on_usage: TokenCallback | None = None,
    ) -> MessageClassification:
        """Classify a message using GPT. This is the ONLY entry point for all user messages."""
        system = ""

        # Telegram reply context (user swiped left on a specific message)
        if reply_context:
            system += f"ההודעה הנוכחית היא תגובה ישירה להודעת הבוט:\n\"{reply_context}\"\n\n"

        # Toggle state (always present - gives the classifier the full picture)
        if toggle_state:
            system += f"מצב ההרגלים של המשתמש:\n{toggle_state}\n\n"

        system += CLASSIFIER_SYSTEM_PROMPT
        date_line = f"\nהתאריך של היום: {today_str}"
        if day_name:
            date_line += f" (יום {day_name})"
        system += date_line + "\n"

        if last_entry:
            system += (
                f"\nהרשומה האחרונה שנרשמה:\n"
                f"תיאור: {last_entry.get('description', '')}\n"
                f"קלוריות: {last_entry.get('calories', 0)}\n"
                f"חלבון: {last_entry.get('protein', 0)}\n"
            )
        else:
            system += "\nאין רשומה קודמת. תיקון → food חדש.\n"

        if recent_messages:
            system += "\nתזכורת: לצורך סיווג רגשות - התעלם מההיסטוריה. סווג רק לפי תוכן ההודעה הנוכחית.\n"
            system += "היסטוריית שיחה אחרונה (מהישנה לחדשה):\n"
            for msg in recent_messages:
                role_label = "בוט" if msg.get("role") == "bot" else "משתמש"
                system += f"[{role_label}]: {msg.get('text', '')}\n"
            system += "\nההודעה הנוכחית של המשתמש מופיעה למטה. השתמש בהיסטוריה כדי להבין את ההקשר.\nחשוב: אם ההודעה הנוכחית מזכירה מאכל/שתייה ספציפיים - סווג כ-meal עם emotional_context=true, לא כ-emotional, ללא קשר להיסטוריה.\n"

        try:
            response = self._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=MessageClassification,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT classifier returned None for: %s", text[:80])
                return MessageClassification(type="none")
            return result
        except Exception:
            logger.exception("GPT classifier failed for: %s", text[:80])
            return MessageClassification(type="none")

    def route_message(
        self, text: str, today_str: str, last_entry: dict | None = None,
        recent_messages: list[dict] | None = None,
        toggle_state: str | None = None,
        reply_context: str | None = None,
        day_name: str = "",
        on_usage: TokenCallback | None = None,
    ) -> RouterClassification:
        """Route a message using the slim Router prompt.

        Classifies message type and extracts meal data inline for type=meal.
        For all other types, only type and optional toggle_name are returned.
        """
        system = ""

        if reply_context:
            if "קל׳" in reply_context and "חלבון" in reply_context:
                system += (
                    "ההודעה הנוכחית היא תגובה לאישור רישום אוכל קודם של הבוט:\n"
                    f"\"{reply_context}\"\n"
                    "המשתמש מגיב על רשומה קיימת - זה אף פעם לא רישום חוזר של אותה ארוחה.\n\n"
                )
            else:
                system += f"ההודעה הנוכחית היא תגובה ישירה להודעת הבוט:\n\"{reply_context}\"\n\n"

        if toggle_state:
            system += f"מצב ההרגלים של המשתמש:\n{toggle_state}\n\n"

        system += ROUTER_SYSTEM_PROMPT
        date_line = f"\nהתאריך של היום: {today_str}"
        if day_name:
            date_line += f" (יום {day_name})"
        system += date_line + "\n"

        if last_entry:
            system += (
                f"\nהרשומה האחרונה שנרשמה:\n"
                f"תיאור: {last_entry.get('description', '')}\n"
                f"קלוריות: {last_entry.get('calories', 0)}\n"
                f"חלבון: {last_entry.get('protein', 0)}\n"
            )
        else:
            system += "\nאין רשומה קודמת. תיקון → food חדש.\n"

        if recent_messages:
            system += "\nהיסטוריית שיחה אחרונה (מהישנה לחדשה):\n"
            for msg in recent_messages:
                role_label = "בוט" if msg.get("role") == "bot" else "משתמש"
                system += f"[{role_label}]: {msg.get('text', '')}\n"
            system += "\nההודעה הנוכחית של המשתמש מופיעה למטה. השתמש בהיסטוריה כדי להבין את ההקשר.\n"

        try:
            response = self._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=RouterClassification,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT router returned None for: %s", text[:80])
                return RouterClassification(type="conversational")
            return result
        except Exception:
            logger.exception("GPT router failed for: %s", text[:80])
            return RouterClassification(type="conversational")

    def analyze_correction(
        self,
        original_description: str,
        original_calories: int,
        original_protein: int,
        correction_history: list[str],
        new_correction: str,
        today_str: str,
        photo_base64: str | None = None,
        on_usage: TokenCallback | None = None,
    ) -> CorrectionResult | None:
        """Re-analyze a food entry given the original + chain of corrections.

        When photo_base64 is provided, the photo is included in the prompt
        so the LLM can visually verify items the user mentions (e.g. overlooked
        items). In that case gpt-4o is used instead of gpt-4o-mini.
        """
        system = CORRECTION_SYSTEM_PROMPT + f"\nהתאריך של היום: {today_str}\n"
        if photo_base64:
            system += CORRECTION_PHOTO_ADDENDUM

        user_parts = [
            f"הרשומה המקורית: {original_description}",
            f"קלוריות: {original_calories} | חלבון: {original_protein}",
        ]
        for i, prev in enumerate(correction_history, 1):
            user_parts.append(f"\nתיקון {i}: {prev}")
        user_parts.append(f"\nתיקון חדש: {new_correction}")
        user_text = "\n".join(user_parts)

        if photo_base64:
            user_content: str | list = [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_base64}"}},
                {"type": "text", "text": user_text},
            ]
        else:
            user_content = user_text

        model = "gpt-4o" if photo_base64 else "gpt-4o-mini"

        try:
            response = self._parse(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                response_format=CorrectionResult,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT correction analysis returned None")
                return None
            return result
        except Exception:
            logger.exception("GPT correction analysis failed")
            return None

    def analyze_food_photo(
        self, base64_image: str, today_str: str, caption: str = "",
        on_usage: TokenCallback | None = None,
    ) -> FoodPhotoResult | None:
        system = FOOD_PHOTO_SYSTEM_PROMPT + f"\nהתאריך של היום: {today_str}\n"
        user_content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
        ]
        if caption:
            user_content.append({"type": "text", "text": caption})

        try:
            response = self._parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                response_format=FoodPhotoResult,
                temperature=0,
                on_usage=on_usage,
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
        month_stats: dict,
        past_feedbacks: list[str],
        past_patterns: list[str] | None = None,
        steering_prompt: str | None = None,
        on_usage: TokenCallback | None = None,
    ) -> dict | None:
        import json

        feedbacks_block = "\n".join(f"- {f}" for f in past_feedbacks) if past_feedbacks else "(אין משובים קודמים)"
        patterns_block = "\n".join(f"- {p}" for p in (past_patterns or [])) if past_patterns else "(אין דפוסים קודמים)"
        steering_block = steering_prompt or "(אין היגוי - פידבק ראשון)"

        user_msg = (
            f"## נתונים גולמיים (30 יום)\n"
            f"{json.dumps(month_stats.get('raw_entries', {}), ensure_ascii=False, indent=1)}\n\n"
            f"## סיכומים מחושבים\n"
            f"{json.dumps(month_stats.get('summaries', {}), ensure_ascii=False, indent=1)}\n\n"
            f"## יעדים\n"
            f"{json.dumps(month_stats.get('targets', {}), ensure_ascii=False)}\n\n"
            f"## מתגים פעילים\n"
            f"{', '.join(month_stats.get('active_toggles', []))}\n\n"
            f"## חלון אכילה\n"
            f"{json.dumps(month_stats.get('eating_window'), ensure_ascii=False) if month_stats.get('eating_window') else 'לא מוגדר'}\n\n"
            f"## המשובים האחרונים שלך\n{feedbacks_block}\n\n"
            f"## דפוסים שכבר גילינו\n{patterns_block}\n\n"
            f"## היגוי משתמש\n{steering_block}"
        )

        try:
            response = self._parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": ENHANCED_WEEKLY_SUMMARY_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format=WeeklyFeedbackResult,
                temperature=0.3,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT weekly feedback returned None")
                return None
            return {
                "feedback_text": result.feedback_text,
                "discovered_pattern": result.discovered_pattern,
                "pattern_summary": result.pattern_summary,
            }
        except Exception:
            logger.exception("GPT weekly feedback failed")
            return None

    def dress_wisdom_gem(
        self,
        gem_text: str,
        category: str,
        mode: str,
        context: dict | None,
        name: str,
        gender: str,
        on_usage: TokenCallback | None = None,
    ) -> str:
        """Dress a wisdom gem with personal context. Returns Hebrew text.

        mode: "pattern" (ties to detected behavior) or "general" (neutral hook).
        The engine chose the gem; GPT only personalizes the text.
        """
        gender_suffix = "ה" if gender == "female" else ""
        context_str = json.dumps(context, ensure_ascii=False) if context else "אין"
        user_msg = (
            f"הפנינה: {gem_text}\n"
            f"קטגוריה: {category}\n"
            f"מצב: {mode}\n"
            f"שם: {name or 'לא ידוע'}\n"
            f"סיומת מגדר: {gender_suffix}\n"
            f"הקשר: {context_str}"
        )
        try:
            response = self._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": GEM_DRESSING_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_tokens=300,
                on_usage=on_usage,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("GPT gem dressing failed")
            return gem_text  # fallback to raw gem text

    def suggest_meals(
        self,
        remaining_calories: int,
        remaining_protein: int,
        today_entries: str,
        on_usage: TokenCallback | None = None,
    ) -> str:
        user_msg = (
            f"נותרו היום: {remaining_calories} קלוריות, {remaining_protein}g חלבון\n"
            f"מה שנאכל היום:\n{today_entries}"
        )
        try:
            response = self._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": MEAL_SUGGESTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_tokens=1000,
                on_usage=on_usage,
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
        today_str: str | None = None,
        on_usage: TokenCallback | None = None,
    ) -> str:
        system = QA_SYSTEM_PROMPT
        if today_str:
            system += f"\nהתאריך של היום: {today_str}\n"
        user_msg = (
            f"הנתונים:\n{week_csv}\n\n"
            f"יעדים: {targets.get('calories', 0)} קלוריות, {targets.get('protein', 0)}g חלבון\n\n"
            f"שאלה: {question}"
        )
        try:
            response = self._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                max_tokens=1000,
                on_usage=on_usage,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("GPT Q&A failed for: %s", question)
            return ""

    def suggest_targets(self, height_cm: int, weight_kg: int, age: int, weight_goal: str = "",
                         on_usage: TokenCallback | None = None) -> dict | None:
        """Calculate nutrition targets using GPT. Retries 3 times on failure."""
        import time as _time

        user_msg = f"גובה: {height_cm} ס\"מ\nמשקל: {weight_kg} ק\"ג\nגיל: {age}"
        if weight_goal:
            user_msg += f"\nמטרת המשתמש: {weight_goal}"

        for attempt in range(3):
            try:
                response = self._create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": TARGET_SUGGESTION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0,
                    max_tokens=200,
                    on_usage=on_usage,
                )
                content = response.choices[0].message.content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                return json.loads(content)
            except Exception:
                logger.warning("suggest_targets attempt %d/3 failed", attempt + 1)
                if attempt < 2:
                    _time.sleep(attempt + 1)

        logger.error("FATAL ERROR CONVERSATION BREAKER: suggest_targets failed after 3 attempts")
        return None

    def extract_goal_value(self, text: str, goal_type: str,
                           recent_messages: list[dict] | None = None,
                           on_usage: TokenCallback | None = None) -> dict | None:
        """Extract structured goal data from natural Hebrew text using GPT.

        goal_type: "body_stats", "sleep_time", "workout_count",
                   "eating_window", "nutrition_targets"
        recent_messages: optional conversation history for context-aware
            extraction (e.g. resolving "כן!" from a bot-proposed value).
        Returns parsed dict or None on failure.
        """
        prompt = _EXTRACTION_PROMPTS.get(goal_type)
        if not prompt:
            logger.warning("Unknown goal_type for extraction: %s", goal_type)
            return None

        # Build context-aware user content when history is available
        if recent_messages:
            lines = []
            for msg in recent_messages[-4:]:
                role = "בוט" if msg.get("role") == "bot" else "משתמש"
                lines.append(f"{role}: {msg.get('text', '')}")
            lines.append(f"משתמש: {text}")
            user_content = "\n".join(lines)
        else:
            user_content = text

        try:
            response = self._create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                max_tokens=100,
                on_usage=on_usage,
            )
            content = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return json.loads(content)
        except Exception:
            logger.exception("GPT extraction failed for %s: %s", goal_type, text[:80])
            return None

    def analyze_bulk_correction(
        self, correction_text: str, entries_csv: str,
        on_usage: TokenCallback | None = None,
    ) -> list[BulkCorrectionItem]:
        user_msg = (
            f"רשומות האכילה:\n{entries_csv}\n\n"
            f"תיקון מהמשתמש: {correction_text}"
        )
        try:
            response = self._parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": BULK_CORRECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format=BulkCorrectionResult,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                return []
            return result.corrections
        except Exception:
            logger.exception("GPT bulk correction failed")
            return []

    # ------------------------------------------------------------------
    # Public wrappers for external callers (feedback_service, help_service, internal_api)
    # ------------------------------------------------------------------

    def rewrite_steering(self, prompt: str, response_format,
                         on_usage: TokenCallback | None = None):
        """Steering rewrite for feedback reactions."""
        return self._parse(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            response_format=response_format,
            temperature=0,
            on_usage=on_usage,
        )

    def answer_help(self, messages: list[dict], response_format,
                    max_tokens: int = 1000, on_usage: TokenCallback | None = None):
        """Self-knowledge Q&A for help_service."""
        return self._parse(
            model="gpt-4o-mini",
            messages=messages,
            response_format=response_format,
            temperature=0,
            max_tokens=max_tokens,
            on_usage=on_usage,
        )

    def converse(self, messages: list[dict], max_tokens: int = 1000,
                 on_usage: TokenCallback | None = None,
                 tools: list[dict] | None = None):
        """Free-form conversational response.

        When *tools* is provided, returns the raw ChatCompletionMessage so the
        caller can inspect tool_calls.  Without tools, returns a plain string
        (backward-compatible with existing callers).
        """
        kwargs: dict = dict(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        response = self._create(on_usage=on_usage, **kwargs)
        msg = response.choices[0].message

        if tools:
            return msg  # caller handles tool_calls / .content
        return msg.content or ""

    def generate_target_change_message(self, prompt: str,
                                       on_usage: TokenCallback | None = None) -> str | None:
        """Target change notification for internal_api."""
        response = self._create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
            on_usage=on_usage,
        )
        return response.choices[0].message.content
