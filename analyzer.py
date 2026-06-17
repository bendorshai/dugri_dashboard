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


# Models are defined in models/analyzer_models.py.
# Re-export here for backward compatibility (many files do `from analyzer import FoodItem`).
from models.analyzer_models import (  # noqa: E402, F401
    FoodItem,
    FoodAnalysisResult,
    MealGroup,
    MealResult,
    FoodPhotoResult,
    CorrectionFoodItem,
    CorrectionResult,
    WeeklyFeedbackResult,
    NormalizedActivity,
    HabitEntry,
    RouterClassification,
    MainClassifierResult,
    HabitLoggerResult,
    GoalsTalkResult,
    OtherResult,
)


from prompts import (
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
    QA_SYSTEM_PROMPT,
    MAIN_CLASSIFIER_PROMPT,
    HABIT_LOGGER_PROMPT,
    GOALS_TALK_PROMPT,
    OTHER_PROMPT,
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
                          on_usage: TokenCallback | None = None) -> MealResult | None:
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
                response_format=MealResult,
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

    def main_classifier(
        self, text: str, today_str: str, last_entry: dict | None = None,
        recent_messages: list[dict] | None = None,
        reply_context: str | None = None,
        day_name: str = "",
        on_usage: TokenCallback | None = None,
    ) -> MainClassifierResult:
        """Main classifier - broad category classification.

        Purely contextual: uses message text and conversation history.
        NO toggle state. Returns one of: meal, habit_logger, goals_talk, other.
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

        system += MAIN_CLASSIFIER_PROMPT
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
            system += "\nאין רשומה קודמת. תיקון → לא רלוונטי.\n"

        if recent_messages:
            system += "\nהיסטוריית שיחה אחרונה (מהישנה לחדשה):\n"
            for msg in recent_messages:
                role_label = "בוט" if msg.get("role") == "bot" else "משתמש"
                system += f"[{role_label}]: {msg.get('text', '')}\n"
            system += "\nההודעה הנוכחית של המשתמש מופיעה למטה. השתמש בהיסטוריה כדי להבין את ההקשר.\n"

        try:
            response = self._parse(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=MainClassifierResult,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                logger.warning("GPT main classifier returned None for: %s", text[:80])
                return MainClassifierResult(type="conversation_or_question_or_feedback_or_feature_request_or_emotion_or_anything_else")
            return result
        except Exception:
            logger.exception("GPT main classifier failed for: %s", text[:80])
            return MainClassifierResult(type="conversation_or_question_or_feedback_or_feature_request_or_emotion_or_anything_else")

    def classify_habit(
        self, text: str,
        recent_messages: list[dict] | None = None,
        last_entry: dict | None = None,
        today_str: str = "",
        day_name: str = "",
        on_usage: TokenCallback | None = None,
    ) -> HabitLoggerResult:
        """Habit logger - sub-classify into sleep/workout/self_care/correction."""
        system = HABIT_LOGGER_PROMPT
        system = system.replace("{today_str}", today_str or "")
        system = system.replace("{day_name}", day_name or "")

        if last_entry:
            system += (
                f"\nהרשומה האחרונה שנרשמה:\n"
                f"תיאור: {last_entry.get('description', '')}\n"
                f"קלוריות: {last_entry.get('calories', 0)}\n"
                f"חלבון: {last_entry.get('protein', 0)}\n"
            )

        if recent_messages:
            system += "\nהיסטוריית שיחה אחרונה:\n"
            for msg in recent_messages:
                role_label = "בוט" if msg.get("role") == "bot" else "משתמש"
                system += f"[{role_label}]: {msg.get('text', '')}\n"

        try:
            response = self._parse(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=HabitLoggerResult,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                return HabitLoggerResult(type="correction")
            return result
        except Exception:
            logger.exception("GPT classify_habit failed for: %s", text[:80])
            return HabitLoggerResult(type="correction")

    def classify_goals_talk(
        self, text: str,
        recent_messages: list[dict] | None = None,
        toggle_state: str | None = None,
        on_usage: TokenCallback | None = None,
    ) -> GoalsTalkResult:
        """Goals talk - sub-classify into accept/refuse/goal_value/cancel/hesitation."""
        system = GOALS_TALK_PROMPT.replace("{toggle_state}", toggle_state or "לא זמין")

        if recent_messages:
            system += "\nהיסטוריית שיחה אחרונה:\n"
            for msg in recent_messages:
                role_label = "בוט" if msg.get("role") == "bot" else "משתמש"
                system += f"[{role_label}]: {msg.get('text', '')}\n"

        try:
            response = self._parse(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=GoalsTalkResult,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                return GoalsTalkResult(type="accept")
            return result
        except Exception:
            logger.exception("GPT classify_goals_talk failed for: %s", text[:80])
            return GoalsTalkResult(type="accept")

    def classify_other(
        self, text: str,
        recent_messages: list[dict] | None = None,
        on_usage: TokenCallback | None = None,
    ) -> OtherResult:
        """Other - sub-classify into conversational/emotional/name/etc."""
        system = OTHER_PROMPT

        if recent_messages:
            system += "\nהיסטוריית שיחה אחרונה:\n"
            for msg in recent_messages:
                role_label = "בוט" if msg.get("role") == "bot" else "משתמש"
                system += f"[{role_label}]: {msg.get('text', '')}\n"

        try:
            response = self._parse(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=OtherResult,
                temperature=0,
                on_usage=on_usage,
            )
            result = response.choices[0].message.parsed
            if result is None:
                return OtherResult(type="conversational")
            return result
        except Exception:
            logger.exception("GPT classify_other failed for: %s", text[:80])
            return OtherResult(type="conversational")

    def classify_message(
        self, text: str, today_str: str, last_entry: dict | None = None,
        recent_messages: list[dict] | None = None,
        toggle_state: str | None = None,
        reply_context: str | None = None,
        day_name: str = "",
        on_usage: TokenCallback | None = None,
    ) -> RouterClassification:
        """Classify a user message through the full pipeline.

        Main classifier determines broad category, then the appropriate
        sub-classifier extracts details. Returns unified RouterClassification.
        """
        t1 = self.main_classifier(
            text, today_str, last_entry=last_entry,
            recent_messages=recent_messages,
            reply_context=reply_context,
            day_name=day_name,
            on_usage=on_usage,
        )

        if t1.type == "meal":
            meal_result = self.analyze_food_text(text, today_str, day_name, on_usage=on_usage)
            return RouterClassification(
                type="meal", meal=meal_result,
                emotional_context=meal_result.emotional_context if meal_result else False,
                empathy_reflection=meal_result.empathy_reflection if meal_result else None,
            )

        if t1.type == "habit_logger":
            t2 = self.classify_habit(
                text, recent_messages=recent_messages,
                last_entry=last_entry,
                today_str=today_str, day_name=day_name,
                on_usage=on_usage,
            )
            result = RouterClassification(
                type=t2.type,
                workout_note=t2.workout_note,
                self_care_description=t2.self_care_description,
                sleep_time=t2.sleep_time,
                resolved_date=t2.resolved_date,
                emotional_context=t2.emotional_context,
                empathy_reflection=t2.empathy_reflection,
            )
            return result

        if t1.type == "goals_talk":
            t2 = self.classify_goals_talk(
                text, recent_messages=recent_messages,
                toggle_state=toggle_state, on_usage=on_usage,
            )
            # Map to opt_in for dispatch
            return RouterClassification(type="opt_in", toggle_name=t2.toggle_name)

        if t1.type == "conversation_or_question_or_feedback_or_feature_request_or_emotion_or_anything_else":
            t2 = self.classify_other(
                text, recent_messages=recent_messages,
                on_usage=on_usage,
            )
            return RouterClassification(
                type=t2.type, declared_gender=t2.declared_gender,
            )

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
            temperature=0.6,
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
