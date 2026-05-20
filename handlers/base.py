"""
base.py — handlers ראשיים של דוגרי.

שכבה דקה שמתרגמת בין Update של טלגרם לבין קריאות ל-services ו-repositories.
אין כאן לוגיקה עסקית — היא ב-services.

תלוי ב: repositories, services, analyzer, keyboards.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from analyzer import FoodAnalyzer
from models.food import FoodEntry
from models.profile import UserProfile
from parsing import get_user_now, is_within_eating_window
from repositories.food_repository import FoodRepository
from repositories.user_repository import UserRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from services.eating_day_service import EatingDayService
from services.conversation_state_service import ConversationStateService
from services.onboarding_service import OnboardingService
from services.message_router_service import MessageRouterService
from services.trial_service import TrialService
from services.feedback_service import FeedbackService
from keyboards import (
    THUMBS_UP, OK_HAND,
    make_daily_summary_keyboard, make_main_menu_keyboard,
    make_profile_keyboard, make_settings_keyboard,
    make_food_edit_keyboard, make_food_entry_keyboard, format_daily_status,
    CB_MENU, CB_PROFILE, CB_EDIT_FIELD, CB_SUGGEST,
    CB_ASK, CB_FOOD_EDIT, CB_FOOD_DELETE, CB_FOOD_AGAIN, CB_BULK_FIX, CB_WEEKLY, CB_DAILY, CB_BACK,
    CB_FEEDBACK,
)
from handlers.utils import PENDING_STATE_TTL, safe_react, send_long_text, safe_answer

logger = logging.getLogger(__name__)

FIELD_LABELS = {
    "age": "גיל",
    "height_cm": "גובה (ס\"מ)",
    "weight_kg": "משקל (ק\"ג)",
    "target_calories": "יעד קלוריות",
    "target_protein": "יעד חלבון (גרם)",
    "eating_window": "חלון אכילה (HH:MM-HH:MM)",
    "timezone": "אזור זמן",
}

SIGNUP_URL = "https://dugri.co.il"


class HealthHandlers:
    def __init__(
        self,
        analyzer: FoodAnalyzer,
        user_repo: UserRepository,
        food_repo: FoodRepository,
        feedback_repo: WeeklyFeedbackRepository,
        eating_day_service: EatingDayService,
        state_service: ConversationStateService | None = None,
        onboarding_service: OnboardingService | None = None,
        message_router: MessageRouterService | None = None,
        trial_service: TrialService | None = None,
        feedback_service: FeedbackService | None = None,
    ):
        self.analyzer = analyzer
        self.user_repo = user_repo
        self.food_repo = food_repo
        self.feedback_repo = feedback_repo
        self.eating_day_svc = eating_day_service
        self.state_service = state_service
        self.onboarding_service = onboarding_service
        self.message_router = message_router
        self.trial_service = trial_service
        self.feedback_service = feedback_service

    # ------------------------------------------------------------------
    # Profile helpers
    # ------------------------------------------------------------------

    def _get_profile(self, telegram_user_id: int) -> UserProfile | None:
        return self.user_repo.get(telegram_user_id)

    def _get_today_str(self, profile: UserProfile) -> str:
        now = get_user_now(profile.timezone)
        return now.strftime("%d/%m/%Y")

    def _get_time_str(self, profile: UserProfile) -> str:
        now = get_user_now(profile.timezone)
        return now.strftime("%H:%M")

    def _is_within_window(self, profile: UserProfile) -> bool:
        now = get_user_now(profile.timezone)
        ws = profile.eating_window.start if profile.eating_window else "08:00"
        we = profile.eating_window.end if profile.eating_window else "20:00"
        return is_within_eating_window(now, ws, we)

    def _target_cal(self, profile: UserProfile) -> int:
        return profile.targets.calories or 2000

    def _target_prot(self, profile: UserProfile) -> int:
        return profile.targets.protein or 150

    def _build_food_response(
        self, items_text: str, total_cal: int, total_protein: int, profile: UserProfile,
    ) -> str:
        status = format_daily_status(
            total_cal, total_protein, self._target_cal(profile), self._target_prot(profile),
        )
        return f"{items_text}{status}"

    @staticmethod
    def _format_items_text(items, total_cal: int, total_prot: int) -> str:
        lines = []
        for item in items:
            lines.append(f"• {item.description}")
            lines.append(f"  ~{item.estimated_grams} גרם | {item.calories} קל׳ | {item.protein} גרם חלבון")
        text = "\n".join(lines)
        if len(items) > 1:
            text += f"\n\nסה\"כ: {total_cal} קל׳ | {total_prot} גרם חלבון"
        return text

    def _check_crossing_alerts(
        self, prev_cal: int, prev_protein: int, new_cal: int, new_protein: int, profile: UserProfile,
    ) -> str:
        alerts = []
        target_cal = self._target_cal(profile)
        target_prot = self._target_prot(profile)

        if prev_protein < target_prot <= new_protein:
            alerts.append("🎉 כל הכבוד! הגעת ליעד גרם החלבון היומי!")
        if prev_cal <= target_cal < new_cal:
            alerts.append("⚠️ שים לב — עברת את יעד הקלוריות היומי.")

        return "\n".join(alerts)

    # ------------------------------------------------------------------
    # Dispatched state handler (profile-based pending states)
    # ------------------------------------------------------------------

    async def _handle_dispatched_state(
        self, message, context, tid: int, profile: UserProfile,
    ) -> bool:
        if self.state_service is None:
            return False
        dispatch = self.state_service.dispatch(profile, message.text)
        if dispatch is None:
            return False

        kind = dispatch.kind

        if kind == "awaiting_name" and self.onboarding_service:
            response = self.onboarding_service.handle_name_response(tid, message.text.strip())
            await message.reply_text(response)
            return True

        consent_kinds = {
            "awaiting_calorie_target_consent",
            "awaiting_eating_window_consent",
            "awaiting_sleep_consent",
            "awaiting_workouts_consent",
            "awaiting_self_care_consent",
        }
        if kind in consent_kinds and self.onboarding_service:
            text = message.text.strip().lower()
            accepted = text in ("כן", "yes", "כ", "y", "בטח", "יאללה", "אשמח")
            response = self.onboarding_service.handle_consent_response(tid, kind, accepted)
            if response:
                await message.reply_text(response)
            return True

        if kind == "awaiting_body_stats" and self.onboarding_service:
            parts = [p.strip() for p in message.text.split(",")]
            if len(parts) == 3:
                try:
                    height, weight, age = int(parts[0]), int(parts[1]), int(parts[2])
                    self.user_repo.update_fields(tid, {
                        "height_cm": height,
                        "weight_kg": weight,
                        "age": age,
                    })
                    suggestion = self.analyzer.suggest_targets(height, weight, age)
                    if suggestion:
                        cal = suggestion.get("target_calories", 2000)
                        prot = suggestion.get("target_protein", 150)
                        self.user_repo.update_fields(tid, {
                            "targets.calories": cal,
                            "targets.protein": prot,
                        })
                        self.state_service.clear_pending(tid)
                        await message.reply_text(
                            f"יעדים מומלצים:\nקלוריות: {cal}\nחלבון: {prot} גרם\n\n"
                            "עודכן. בוא נמשיך — מה אכלת?"
                        )
                    else:
                        self.state_service.clear_pending(tid)
                        await message.reply_text("לא הצלחתי לחשב יעדים. שלח ארוחה ונמשיך.")
                except ValueError:
                    await message.reply_text("פורמט לא תקין. שלח: גובה, משקל, גיל (מספרים מופרדים בפסיקים)")
            else:
                await message.reply_text("שלח: גובה, משקל, גיל (מופרדים בפסיקים, למשל: 175, 80, 30)")
            return True

        if kind == "awaiting_feedback_reaction" and self.feedback_service:
            profile_fresh = self._get_profile(tid)
            steering = profile_fresh.feedback_steering_prompt if profile_fresh else None
            response = self.feedback_service.process_reaction(tid, message.text.strip(), steering)
            await message.reply_text(response)
            return True

        if kind == "awaiting_eating_window":
            parts = message.text.strip().split("-")
            if len(parts) == 2:
                self.user_repo.update_fields(tid, {
                    "eating_window.start": parts[0].strip(),
                    "eating_window.end": parts[1].strip(),
                })
                self.state_service.clear_pending(tid)
                await message.reply_text("חלון אכילה עודכן.")
            else:
                await message.reply_text("פורמט: HH:MM-HH:MM (למשל: 08:00-20:00)")
            return True

        # Unknown dispatched state — clear and fall through
        self.state_service.clear_pending(tid)
        return False

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message:
            return

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            await message.reply_text(
                f"כדי להתחיל, הירשם כאן: {SIGNUP_URL}"
            )
            return

        text = (
            "שלום! 👋\n"
            "אני הבוט שלך למעקב תזונה.\n\n"
            "שלח לי תיאור של מה שאכלת (טקסט או תמונה) ואני אחשב קלוריות וגרם חלבון.\n\n"
            f"📊 היעדים שלך:\n"
            f"  קלוריות: {self._target_cal(profile)}\n"
            f"  גרם חלבון: {self._target_prot(profile)}\n"
            f"  חלון אכילה: {profile.eating_window.start if profile.eating_window else '08:00'}-{profile.eating_window.end if profile.eating_window else '20:00'}\n\n"
            "אפשר לשנות הגדרות דרך התפריט למטה."
        )
        await message.reply_text(text, reply_markup=make_main_menu_keyboard())

    async def handle_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message:
            return

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            await message.reply_text(f"צריך להירשם קודם: {SIGNUP_URL}")
            return

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        total_cal, total_protein = self.eating_day_svc.get_eating_day_totals(profile, stats_date)

        status = format_daily_status(
            total_cal, total_protein, self._target_cal(profile), self._target_prot(profile),
        )
        await message.reply_text(
            f"📋 תפריט ראשי{status}",
            reply_markup=make_main_menu_keyboard(),
        )

    # ------------------------------------------------------------------
    # Text message handler
    # ------------------------------------------------------------------

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.text:
            return

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            await message.reply_text(f"צריך להירשם קודם: {SIGNUP_URL}")
            return

        # Trial gating: check expiry on every message, block if ended
        if self.trial_service:
            just_expired = self.trial_service.check_and_expire(
                profile, get_user_now(profile.timezone),
            )
            if just_expired:
                await message.reply_text(self.trial_service.get_expiry_message())
                return
            if self.trial_service.is_blocked(profile):
                await message.reply_text(self.trial_service.get_blocked_message())
                return

        # Check profile-based pending state (dispatcher) first
        if await self._handle_dispatched_state(message, context, tid, profile):
            return

        # Check context-based pending states (legacy, will migrate in future)
        if await self._handle_pending_edit(message, context, tid, profile):
            return

        if await self._handle_pending_question(message, context, tid, profile):
            return

        if await self._handle_pending_correction(message, context, tid, profile):
            return

        if await self._handle_pending_bulk_fix(message, context, tid, profile):
            return

        today_str = self._get_today_str(profile)
        time_str = self._get_time_str(profile)
        within_window = self._is_within_window(profile)

        last_entry = context.chat_data.get("last_entry")

        # Heavy classifier (9 types) or fallback to old parse_message
        classification = self.analyzer.classify_message(message.text, today_str, last_entry)

        # Route non-food types through MessageRouterService
        if classification.type == "correction" and classification.correction and last_entry:
            await self._handle_correction(message, context, classification.correction, last_entry, profile, today_str, tid)
            return

        if classification.type == "sleep" and self.message_router:
            result = self.message_router.route_sleep(tid, classification.sleep_time or time_str, today_str)
            await message.reply_text(result.response_text)
            return

        if classification.type == "workout" and self.message_router:
            result = self.message_router.route_workout(tid, today_str, classification.workout_note)
            await message.reply_text(result.response_text)
            return

        if classification.type == "self_care" and self.message_router:
            from datetime import datetime as dt
            week_id = dt.strptime(today_str, "%d/%m/%Y").strftime("%G-W%V")
            result = self.message_router.route_self_care(tid, classification.self_care_description or message.text, week_id)
            await message.reply_text(result.response_text)
            return

        if classification.type == "help" and self.message_router:
            result = self.message_router.route_help(classification.question_text or message.text)
            await send_long_text(message, result.response_text, reply_markup=make_daily_summary_keyboard())
            return

        if classification.type == "answer_question" and self.message_router:
            result = self.message_router.route_answer_question(
                tid, classification.question_text or message.text,
                today_str, self._target_cal(profile), self._target_prot(profile),
            )
            await send_long_text(message, result.response_text, reply_markup=make_daily_summary_keyboard())
            return

        if classification.type == "feedback_request":
            if self.feedback_service:
                is_first = self.feedback_service.is_first_feedback(tid)
                feedback_text = self.feedback_service.give_feedback(
                    tid, today_str,
                    self._target_cal(profile),
                    self._target_prot(profile),
                    profile.feedback_steering_prompt,
                    is_first,
                )
                await send_long_text(message, feedback_text, reply_markup=make_main_menu_keyboard())
            elif self.message_router:
                result = self.message_router.route_feedback_request()
                await message.reply_text(result.response_text, reply_markup=make_main_menu_keyboard())
            return

        if classification.type == "none" and self.message_router:
            result = self.message_router.route_none()
            await message.reply_text(result.response_text)
            return

        # Default: treat as food (meal type or fallback)
        if classification.type == "meal" and classification.meal and classification.meal.items:
            food_result = classification.meal
        else:
            food_result = self.analyzer.analyze_food_text(message.text, today_str)

        if food_result is None or not food_result.items:
            await message.reply_text("לא הצלחתי לזהות מאכל בהודעה. נסה שוב?")
            return

        combined_desc = ", ".join(item.description for item in food_result.items)
        total_cal = food_result.total_calories
        total_prot = food_result.total_protein

        entry = FoodEntry(
            telegram_user_id=tid,
            date=today_str,
            time=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            within_window=within_window,
        )
        saved = self.food_repo.add(entry)

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        new_daily_cal, new_daily_prot = self.eating_day_svc.get_eating_day_totals(profile, stats_date)
        prev_cal = new_daily_cal - total_cal
        prev_protein = new_daily_prot - total_prot
        logger.info("Recorded: %s (%d cal, %dg protein) -> id %s",
                    combined_desc, total_cal, total_prot, saved.id)

        context.chat_data["last_entry"] = {
            "description": combined_desc,
            "calories": total_cal,
            "protein": total_prot,
            "entry_id": saved.id,
        }

        items_text = self._format_items_text(food_result.items, total_cal, total_prot)
        alerts = self._check_crossing_alerts(prev_cal, prev_protein, new_daily_cal, new_daily_prot, profile)

        response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)
        if alerts:
            response = f"{alerts}\n\n{response}"

        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(saved.id))
        await safe_react(message, OK_HAND)

    async def _handle_correction(
        self, message, context, correction, last_entry: dict,
        profile: UserProfile, today_str: str, tid: int,
    ):
        entry_id = last_entry["entry_id"]
        old_cal = last_entry["calories"]
        old_prot = last_entry["protein"]

        new_desc = correction.corrected_description
        new_cal = correction.corrected_calories
        new_prot = correction.corrected_protein

        self.food_repo.update(entry_id, {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
        })

        context.chat_data["last_entry"] = {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
            "entry_id": entry_id,
        }

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        final_cal, final_prot = self.eating_day_svc.get_eating_day_totals(profile, stats_date)

        cal_diff = new_cal - old_cal
        prot_diff = new_prot - old_prot

        items_text = self._format_items_text(correction.items, new_cal, new_prot)

        diff_parts = []
        if cal_diff != 0:
            diff_parts.append(f"קלוריות: {old_cal} → {new_cal}")
        if prot_diff != 0:
            diff_parts.append(f"חלבון: {old_prot} → {new_prot}")
        diff_line = f"\n({', '.join(diff_parts)})" if diff_parts else ""

        response = f"✏️ עודכן:\n{items_text}{diff_line}"
        status = format_daily_status(
            final_cal, final_prot, self._target_cal(profile), self._target_prot(profile),
        )
        response += status

        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(entry_id))
        await safe_react(message, OK_HAND)

    # ------------------------------------------------------------------
    # Photo handler
    # ------------------------------------------------------------------

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.photo:
            return

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            await message.reply_text(f"צריך להירשם קודם: {SIGNUP_URL}")
            return

        today_str = self._get_today_str(profile)
        time_str = self._get_time_str(profile)
        within_window = self._is_within_window(profile)

        photo = message.photo[-1]
        file = await photo.get_file()
        photo_bytes = await file.download_as_bytearray()
        b64 = base64.b64encode(photo_bytes).decode("utf-8")

        caption = message.caption or ""

        result = self.analyzer.analyze_food_photo(b64, today_str, caption=caption)
        if result is None or not result.items:
            await message.reply_text("לא הצלחתי לזהות מאכל בתמונה. נסה לתאר מה אכלת בטקסט.")
            return

        combined_desc = ", ".join(item.description for item in result.items)
        total_cal = result.total_calories
        total_prot = result.total_protein

        entry = FoodEntry(
            telegram_user_id=tid,
            date=today_str,
            time=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            within_window=within_window,
        )
        saved = self.food_repo.add(entry)

        context.chat_data["last_entry"] = {
            "description": combined_desc,
            "calories": total_cal,
            "protein": total_prot,
            "entry_id": saved.id,
        }

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        new_daily_cal, new_daily_prot = self.eating_day_svc.get_eating_day_totals(profile, stats_date)
        prev_cal = new_daily_cal - total_cal
        prev_protein = new_daily_prot - total_prot

        items_text = self._format_items_text(result.items, total_cal, total_prot)

        alerts = self._check_crossing_alerts(prev_cal, prev_protein, new_daily_cal, new_daily_prot, profile)
        response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)
        if alerts:
            response = f"{alerts}\n\n{response}"

        if result.photo_tips:
            response += f"\n\n💡 {result.photo_tips[0]}"

        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(saved.id))
        await safe_react(message, OK_HAND)

    # ------------------------------------------------------------------
    # Pending edit/question state
    # ------------------------------------------------------------------

    async def _handle_pending_edit(self, message, context, tid: int, profile: UserProfile) -> bool:
        pending = context.chat_data.get("pending_edit")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_edit"]
            return False

        del context.chat_data["pending_edit"]
        field = pending["field"]
        text = message.text.strip()

        try:
            if field == "eating_window":
                parts = text.split("-")
                if len(parts) != 2:
                    await message.reply_text("פורמט לא תקין. השתמש ב: HH:MM-HH:MM")
                    return True
                self.user_repo.update_fields(tid, {
                    "eating_window.start": parts[0].strip(),
                    "eating_window.end": parts[1].strip(),
                })
            elif field == "target_calories":
                value = int(text)
                self.user_repo.update_fields(tid, {"targets.calories": value})
            elif field == "target_protein":
                value = int(text)
                self.user_repo.update_fields(tid, {"targets.protein": value})
            elif field in ("age", "height_cm", "weight_kg"):
                value = int(text)
                self.user_repo.update_fields(tid, {field: value})
            elif field == "timezone":
                self.user_repo.update_fields(tid, {"timezone": text})
            else:
                await message.reply_text("שדה לא מוכר.")
                return True

            await safe_react(message, OK_HAND)
            await message.reply_text(f"✅ {FIELD_LABELS.get(field, field)} עודכן!")

            if field == "eating_window":
                from scheduler import schedule_eating_window_jobs
                updated_profile = self._get_profile(tid)
                schedule_eating_window_jobs(
                    context.job_queue, tid, updated_profile,
                    self.user_repo, self.food_repo, self.feedback_repo,
                    self.analyzer, self.eating_day_svc,
                )

        except ValueError:
            await message.reply_text("ערך לא תקין. נסה שוב.")
        except Exception:
            logger.exception("Failed to update profile field %s", field)
            await message.reply_text("❌ שגיאה בעדכון.")

        return True

    async def _handle_pending_question(self, message, context, tid: int, profile: UserProfile) -> bool:
        pending = context.chat_data.get("pending_question")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_question"]
            return False

        del context.chat_data["pending_question"]
        question = message.text.strip()

        await safe_react(message, THUMBS_UP)

        today_str = self._get_today_str(profile)
        today = datetime.strptime(today_str, "%d/%m/%Y").date()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]

        entries = self.food_repo.get_by_user_and_dates(tid, dates)
        csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון"]
        for e in entries:
            csv_lines.append(f"{e.date},{e.time},{e.description},{e.calories},{e.protein}")
        week_csv = "\n".join(csv_lines)

        targets = {
            "calories": self._target_cal(profile),
            "protein": self._target_prot(profile),
        }

        answer = self.analyzer.answer_question(question, week_csv, targets)
        if answer:
            await send_long_text(message, answer, reply_markup=make_daily_summary_keyboard())
        else:
            await message.reply_text("לא הצלחתי לענות. נסה שוב.")

        return True

    async def _handle_pending_correction(self, message, context, tid: int, profile: UserProfile) -> bool:
        pending = context.chat_data.get("pending_correction")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_correction"]
            return False

        del context.chat_data["pending_correction"]
        await safe_react(message, THUMBS_UP)

        entry = pending["entry"]
        correction_history = pending.get("correction_history", [])
        today_str = self._get_today_str(profile)
        entry_id = entry["entry_id"]

        correction = self.analyzer.analyze_correction(
            original_description=entry["description"],
            original_calories=entry["calories"],
            original_protein=entry["protein"],
            correction_history=correction_history,
            new_correction=message.text,
            today_str=today_str,
        )

        if correction:
            await self._handle_correction(message, context, correction, entry, profile, today_str, tid)
            updated_history = correction_history + [message.text]
            context.chat_data.setdefault("correction_histories", {})[entry_id] = updated_history
        else:
            await message.reply_text("לא הצלחתי להבין את התיקון. נסה שוב.")

        return True

    async def _handle_pending_bulk_fix(self, message, context, tid: int, profile: UserProfile) -> bool:
        pending = context.chat_data.get("pending_bulk_fix")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_bulk_fix"]
            return False

        del context.chat_data["pending_bulk_fix"]
        await safe_react(message, THUMBS_UP)

        correction_text = message.text.strip()

        all_entries = self.food_repo.get_all_for_user(tid)
        if not all_entries:
            await message.reply_text("אין רשומות לתיקון.")
            return True

        csv_lines = ["row_index,תאריך,שעה,תיאור,קלוריות,חלבון"]
        for i, e in enumerate(all_entries):
            csv_lines.append(f"{i},{e.date},{e.time},{e.description},{e.calories},{e.protein}")
        entries_csv = "\n".join(csv_lines)

        await message.reply_text("🔍 מחפש רשומות לתיקון...")

        corrections = self.analyzer.analyze_bulk_correction(correction_text, entries_csv)

        if not corrections:
            await message.reply_text("לא מצאתי רשומות שמתאימות לתיקון.", reply_markup=make_main_menu_keyboard())
            return True

        report_lines = []
        total_cal_diff = 0
        total_prot_diff = 0

        for c in corrections:
            if c.row_index >= len(all_entries):
                continue
            old_entry = all_entries[c.row_index]
            old_cal = old_entry.calories
            old_prot = old_entry.protein

            self.food_repo.update(old_entry.id, {
                "description": c.corrected_description,
                "calories": c.corrected_calories,
                "protein": c.corrected_protein,
            })

            cal_diff = c.corrected_calories - old_cal
            prot_diff = c.corrected_protein - old_prot
            total_cal_diff += cal_diff
            total_prot_diff += prot_diff

            report_lines.append(
                f"• {c.original_description} → {c.corrected_description} "
                f"({old_cal}→{c.corrected_calories} קל׳, {old_prot}→{c.corrected_protein} גרם חלבון)"
            )

        report = (
            f"✅ תוקנו {len(corrections)} רשומות:\n\n"
            + "\n".join(report_lines)
            + f"\n\nשינוי כולל: {'+' if total_cal_diff >= 0 else ''}{total_cal_diff} קל׳, "
            f"{'+' if total_prot_diff >= 0 else ''}{total_prot_diff} גרם חלבון"
        )

        await send_long_text(message, report, reply_markup=make_main_menu_keyboard())
        await safe_react(message, OK_HAND)
        return True

    # ------------------------------------------------------------------
    # Callback handlers
    # ------------------------------------------------------------------

    async def handle_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        data = query.data.removeprefix(CB_MENU)

        if data == "profile":
            profile = self._get_profile(tid)
            if profile is None:
                return
            text = (
                "👤 הפרופיל שלך:\n\n"
                f"גיל: {getattr(profile, 'age', '-') or '-'}\n"
                f"גובה: {getattr(profile, 'height_cm', '-') or '-'} ס\"מ\n"
                f"משקל: {getattr(profile, 'weight_kg', '-') or '-'} ק\"ג\n\n"
                f"🎯 יעדים:\n"
                f"קלוריות: {self._target_cal(profile)}\n"
                f"גרם חלבון: {self._target_prot(profile)}\n\n"
                f"⏰ חלון אכילה: {profile.eating_window.start if profile.eating_window else '08:00'}-{profile.eating_window.end if profile.eating_window else '20:00'}\n"
                f"🌍 אזור זמן: {profile.timezone}\n\n"
                "לחץ על שדה לעריכה:"
            )
            await query.edit_message_text(text, reply_markup=make_profile_keyboard())

        elif data == "settings":
            await query.edit_message_text("⚙️ הגדרות:", reply_markup=make_settings_keyboard())

    async def handle_profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        data = query.data.removeprefix(CB_PROFILE)

        if data == "suggest_targets":
            profile = self._get_profile(tid)
            if profile is None:
                return
            height = getattr(profile, "height_cm", 0) or 0
            weight = getattr(profile, "weight_kg", 0) or 0
            age = getattr(profile, "age", 0) or 0

            if not all([height, weight, age]):
                await query.edit_message_text(
                    "צריך למלא גיל, גובה ומשקל לפני שאפשר להציע יעדים.",
                    reply_markup=make_profile_keyboard(),
                )
                return

            suggestion = self.analyzer.suggest_targets(height, weight, age)
            if suggestion:
                cal = suggestion.get("target_calories", 2000)
                prot = suggestion.get("target_protein", 150)
                self.user_repo.update_fields(tid, {
                    "targets.calories": cal,
                    "targets.protein": prot,
                })
                await query.edit_message_text(
                    f"🎯 יעדים מומלצים עודכנו:\n"
                    f"קלוריות: {cal}\n"
                    f"גרם חלבון: {prot}",
                    reply_markup=make_profile_keyboard(),
                )
            else:
                await query.edit_message_text(
                    "לא הצלחתי לחשב יעדים. נסה שוב.",
                    reply_markup=make_profile_keyboard(),
                )

    async def handle_edit_field_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        field = query.data.removeprefix(CB_EDIT_FIELD)
        label = FIELD_LABELS.get(field, field)

        context.chat_data["pending_edit"] = {
            "field": field,
            "timestamp": time.time(),
        }

        await query.edit_message_text(f"שלח ערך חדש עבור {label}:")

    async def handle_suggest_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            return

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        total_cal, total_protein = self.eating_day_svc.get_eating_day_totals(profile, stats_date)
        entries = self.eating_day_svc.get_eating_day_entries(profile, stats_date)

        target_cal = self._target_cal(profile)
        target_prot = self._target_prot(profile)
        remaining_cal = max(0, target_cal - total_cal)
        remaining_prot = max(0, target_prot - total_protein)

        today_text = "\n".join(
            f"- {e.description}: {e.calories} קל׳, {e.protein} גרם חלבון"
            for e in entries
        ) or "עדיין לא אכלת היום"

        await query.edit_message_text("🤔 מחפש הצעות...")

        suggestions = self.analyzer.suggest_meals(remaining_cal, remaining_prot, today_text)
        if suggestions:
            await query.edit_message_text(
                f"🍽 הצעות ארוחה:\n\n{suggestions}",
                reply_markup=make_daily_summary_keyboard(),
            )
        else:
            await query.edit_message_text(
                "לא הצלחתי להציע ארוחות. נסה שוב.",
                reply_markup=make_daily_summary_keyboard(),
            )

    async def handle_ask_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        context.chat_data["pending_question"] = {
            "timestamp": time.time(),
        }

        await query.edit_message_text("❓ שאל אותי כל שאלה על תזונה:")

    async def handle_food_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        entry_id = query.data.removeprefix(CB_FOOD_DELETE)
        try:
            self.food_repo.delete(entry_id)
            await query.edit_message_text("🗑 הרשומה נמחקה.", reply_markup=make_daily_summary_keyboard())
        except Exception:
            logger.exception("Failed to delete food entry %s", entry_id)
            await query.edit_message_text("❌ שגיאה במחיקה.", reply_markup=make_daily_summary_keyboard())

    async def handle_food_edit_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        entry_id = query.data.removeprefix(CB_FOOD_EDIT)
        try:
            food_entry = self.food_repo.get(entry_id)
            if food_entry is None:
                await query.edit_message_text("❌ הרשומה לא נמצאה.", reply_markup=make_daily_summary_keyboard())
                return

            existing_history = context.chat_data.get("correction_histories", {}).get(entry_id, [])
            context.chat_data["pending_correction"] = {
                "entry": {
                    "description": food_entry.description,
                    "calories": food_entry.calories,
                    "protein": food_entry.protein,
                    "entry_id": entry_id,
                },
                "correction_history": existing_history,
                "timestamp": time.time(),
            }

            await query.edit_message_text(
                f"✏️ עריכת רשומה: {food_entry.description}\n"
                f"קלוריות: {food_entry.calories} | גרם חלבון: {food_entry.protein}\n\n"
                "שלח תיאור של התיקון (למשל: 'זה היה 300 גרם לא 150'):"
            )
        except Exception:
            logger.exception("Failed to read entry for edit, id %s", entry_id)
            await query.edit_message_text("❌ שגיאה בקריאת הרשומה.", reply_markup=make_daily_summary_keyboard())

    async def handle_food_again_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        entry_id = query.data.removeprefix(CB_FOOD_AGAIN)
        try:
            food_entry = self.food_repo.get(entry_id)
            if food_entry is None:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ הרשומה לא נמצאה.",
                    reply_markup=make_daily_summary_keyboard(),
                )
                return

            profile = self._get_profile(tid)
            if profile is None:
                return
            today_str = self._get_today_str(profile)
            time_str = self._get_time_str(profile)
            within_window = self._is_within_window(profile)

            new_entry = FoodEntry(
                telegram_user_id=tid,
                date=today_str,
                time=time_str,
                description=food_entry.description,
                calories=food_entry.calories,
                protein=food_entry.protein,
                within_window=within_window,
            )
            saved = self.food_repo.add(new_entry)

            stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
            new_daily_cal, new_daily_prot = self.eating_day_svc.get_eating_day_totals(profile, stats_date)

            items_text = f"🔁 {food_entry.description}: {food_entry.calories} קל׳ | {food_entry.protein} גרם חלבון"
            response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=response,
                reply_markup=make_food_entry_keyboard(saved.id),
            )
        except Exception:
            logger.exception("Failed to duplicate food entry %s", entry_id)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ שגיאה בשכפול הרשומה.",
                reply_markup=make_daily_summary_keyboard(),
            )

    async def handle_bulk_fix_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        context.chat_data["pending_bulk_fix"] = {
            "timestamp": time.time(),
        }

        await query.edit_message_text(
            "🔧 תיקון כללי\n\n"
            "תאר את הטעות שחוזרת על עצמה.\n"
            "למשל: 'כל פעם שכתבתי עוגת בננה זה היה פרוסה לא עוגה שלמה'\n"
            "או: 'הקפה שלי תמיד עם חלב שקד, לא חלב רגיל'\n\n"
            "הבוט יתקן את כל הרשומות שמתאימות."
        )

    async def handle_daily_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            return

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        entries = self.eating_day_svc.get_eating_day_entries(profile, stats_date)

        if not entries:
            await query.edit_message_text(
                "📋 אין רשומות להיום.",
                reply_markup=make_daily_summary_keyboard(),
            )
            return

        total_cal = 0
        total_prot = 0
        lines = ["📋 סיכום יומי מפורט:\n"]
        for i, e in enumerate(entries, 1):
            total_cal += e.calories
            total_prot += e.protein
            lines.append(f"{i}. {e.description} — {e.calories} קל׳ | {e.protein} גרם חלבון ({e.time})")

        status = format_daily_status(total_cal, total_prot, self._target_cal(profile), self._target_prot(profile))
        text = "\n".join(lines) + status

        await send_long_text(query.message, text, reply_markup=make_daily_summary_keyboard())

    async def handle_weekly_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            return

        target_cal = self._target_cal(profile)
        target_prot = self._target_prot(profile)
        window_start = profile.eating_window.start if profile.eating_window else "08:00"
        window_end = profile.eating_window.end if profile.eating_window else "20:00"

        now = get_user_now(profile.timezone)
        today = now.date()

        dates = [(today - timedelta(days=i)) for i in range(7)]

        lines = ["📅 סיכום שבועי:\n"]
        for d in dates:
            ds = d.strftime("%d/%m/%Y")
            day_label = d.strftime("%a %d/%m")
            entries = self.eating_day_svc.get_eating_day_entries(profile, ds)

            if not entries:
                lines.append(f"📆 {day_label}  —  אין נתונים")
                continue

            day_cal = sum(e.calories for e in entries)
            day_prot = sum(e.protein for e in entries)
            window_kept = all(
                (not e.time or (window_start <= e.time < window_end))
                for e in entries
            )

            cal_pct = round(day_cal / target_cal * 100) if target_cal else 0
            prot_pct = round(day_prot / target_prot * 100) if target_prot else 0
            cal_icon = "✅" if day_cal <= target_cal else "⚠️"
            prot_icon = "✅" if day_prot >= target_prot else "⚠️"
            window_icon = "✅" if window_kept else "🍽"

            lines.append(
                f"📆 {day_label}\n"
                f"  {cal_icon} קלוריות: {day_cal}/{target_cal} ({cal_pct}%)\n"
                f"  {prot_icon} גרם חלבון: {day_prot}/{target_prot} ({prot_pct}%)\n"
                f"  {window_icon} חלון אכילה: {'נשמר' if window_kept else 'לא נשמר'}"
            )

        text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=make_main_menu_keyboard())

    async def handle_back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        profile = self._get_profile(tid)
        if profile is None:
            return

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        total_cal, total_protein = self.eating_day_svc.get_eating_day_totals(profile, stats_date)

        status = format_daily_status(
            total_cal, total_protein, self._target_cal(profile), self._target_prot(profile),
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"📋 תפריט ראשי{status}",
            reply_markup=make_main_menu_keyboard(),
        )

    async def handle_feedback_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="🤔 מכין משוב...",
        )

        try:
            profile = self._get_profile(tid)
            if profile is None:
                return

            today_str = self._get_today_str(profile)

            if self.feedback_service:
                is_first = self.feedback_service.is_first_feedback(tid)
                feedback_text = self.feedback_service.give_feedback(
                    tid, today_str,
                    self._target_cal(profile),
                    self._target_prot(profile),
                    profile.feedback_steering_prompt,
                    is_first,
                )
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=feedback_text,
                    reply_markup=make_main_menu_keyboard(),
                )
            else:
                # Fallback without feedback service
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="לא הצלחתי לייצר משוב כרגע.",
                    reply_markup=make_main_menu_keyboard(),
                )
        except Exception:
            logger.exception("Failed to generate feedback")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ שגיאה ביצירת משוב.",
                reply_markup=make_main_menu_keyboard(),
            )
