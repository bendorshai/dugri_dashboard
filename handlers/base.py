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
from parsing import get_user_now, hebrew_day_name, is_within_eating_window
from repositories.food_repository import FoodRepository
from repositories.user_repository import UserRepository
from repositories.feedback_repository import WeeklyFeedbackRepository
from services.eating_day_service import EatingDayService
from services.onboarding_service import OnboardingService
from services.message_router_service import MessageRouterService
from services.trial_service import TrialService
from services.feedback_service import FeedbackService
from services.toggle_service import ToggleService
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

class HealthHandlers:
    def __init__(
        self,
        analyzer: FoodAnalyzer,
        user_repo: UserRepository,
        food_repo: FoodRepository,
        feedback_repo: WeeklyFeedbackRepository,
        eating_day_service: EatingDayService,
        onboarding_service: OnboardingService | None = None,
        message_router: MessageRouterService | None = None,
        trial_service: TrialService | None = None,
        feedback_service: FeedbackService | None = None,
        toggle_service: ToggleService | None = None,
        goal_service=None,
        landing_page_url: str = "https://www.dugri.life",
    ):
        self.landing_page_url = landing_page_url
        self.analyzer = analyzer
        self.user_repo = user_repo
        self.food_repo = food_repo
        self.feedback_repo = feedback_repo
        self.eating_day_svc = eating_day_service
        self.onboarding_service = onboarding_service
        self.message_router = message_router
        self.trial_service = trial_service
        self.feedback_service = feedback_service
        self.toggle_service = toggle_service
        self.goal_service = goal_service

    # ------------------------------------------------------------------
    # Conversation history helpers
    # ------------------------------------------------------------------

    def _save_bot_message(self, tid: int, text: str) -> None:
        """Save a bot message to conversation history."""
        from constants import MAX_RECENT_MESSAGES
        from datetime import timezone as tz
        msg = {
            "role": "bot",
            "text": text[:500],
            "timestamp": datetime.now(tz.utc).isoformat(),
        }
        self.user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)

    # ------------------------------------------------------------------
    # Profile helpers
    # ------------------------------------------------------------------

    def _get_profile(self, telegram_user_id: int) -> UserProfile | None:
        return self.user_repo.get(telegram_user_id)

    def _get_today_str(self, profile: UserProfile) -> str:
        now = get_user_now(profile.timezone)
        return self.eating_day_svc.get_stats_date(profile, now)

    def _get_time_str(self, profile: UserProfile) -> str:
        now = get_user_now(profile.timezone)
        return now.strftime("%H:%M")

    def _is_within_window(self, profile: UserProfile) -> bool:
        now = get_user_now(profile.timezone)
        ws = profile.eating_window.start if profile.eating_window else "00:00"
        we = profile.eating_window.end if profile.eating_window else "23:59"
        return is_within_eating_window(now, ws, we)

    def _target_cal(self, profile: UserProfile) -> int:
        nv = profile.toggles.nutrition.goal_value
        if nv and "calories" in nv:
            return nv["calories"]
        return profile.targets.calories or 2000

    def _target_prot(self, profile: UserProfile) -> int:
        nv = profile.toggles.nutrition.goal_value
        if nv and "protein" in nv:
            return nv["protein"]
        return profile.targets.protein or 150

    def _get_education_intro(self, tid: int, toggle_name: str, profile: UserProfile) -> str | None:
        """Return education intro if not yet shown for this toggle. Mark as shown."""
        toggle = getattr(profile.toggles, toggle_name, None)
        if toggle is None or toggle.edu_intro_shown:
            return None
        from dugri_messages import EDU_INTRO_FIRST_LOG
        text = EDU_INTRO_FIRST_LOG.get(toggle_name)
        if text:
            self.user_repo.update_fields(tid, {f"toggles.{toggle_name}.edu_intro_shown": True})
        return text

    def _process_habit_entries(self, tid: int, entries, today_str: str) -> str | None:
        """Process multi-type habit entries and return combined confirmation text."""
        if not entries:
            return None
        lines = []
        for entry in entries:
            if entry.habit_type == "sleep" and entry.sleep_time and self.message_router:
                self.message_router.route_sleep(tid, entry.sleep_time, entry.date or today_str)
                lines.append(f"שינה {entry.temporal_label}: {entry.sleep_time}")
            elif entry.habit_type == "workout" and self.message_router:
                self.message_router.route_workout(tid, entry.date or today_str, entry.workout_note)
                label = f"אימון {entry.temporal_label}"
                if entry.workout_note:
                    label += f" ({entry.workout_note})"
                lines.append(label)
            elif entry.habit_type == "self_care" and entry.self_care_description and self.message_router:
                from datetime import datetime as dt
                date_str = entry.date or today_str
                try:
                    week_id = dt.strptime(date_str, "%d/%m/%Y").strftime("%G-W%V")
                except ValueError:
                    week_id = dt.now().strftime("%G-W%V")
                self.message_router.route_self_care(tid, entry.self_care_description, week_id)
                lines.append(f"משהו לעצמך {entry.temporal_label}: {entry.self_care_description}")
        if not lines:
            return None
        if len(lines) == 1:
            return f"רשמתי: {lines[0]}"
        return "רשמתי:\n" + "\n".join(f"- {l}" for l in lines)

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

    @staticmethod
    def _format_grouped_items_text(groups, today_str: str) -> str:
        """Format food items grouped by temporal label.

        Shows a 📅 header for each group when there are multiple groups or
        when a single group is not for today (retroactive).
        """
        show_labels = len(groups) > 1 or (len(groups) == 1 and groups[0].date != today_str)
        sections = []
        for group in groups:
            lines = []
            if show_labels:
                lines.append(f"📅 {group.temporal_label}:")
            for item in group.items:
                lines.append(f"• {item.description}")
                lines.append(f"  ~{item.estimated_grams} גרם | {item.calories} קל׳ | {item.protein} גרם חלבון")
            if len(groups) > 1 and len(group.items) > 1:
                lines.append(f"  סה\"כ: {group.total_calories} קל׳ | {group.total_protein} גרם חלבון")
            sections.append("\n".join(lines))
        text = "\n\n".join(sections)
        # Grand total across all groups (like _format_items_text for multi-item)
        all_items = [item for g in groups for item in g.items]
        if len(all_items) > 1 and len(groups) == 1:
            total_cal = groups[0].total_calories
            total_prot = groups[0].total_protein
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
    # Conversation reply handler (toggle-state + history based routing)
    # ------------------------------------------------------------------

    async def _handle_conversation_reply(
        self, message, context, tid: int, profile: UserProfile, classification,
    ):
        """Handle a message classified as conversation_reply by GPT.

        Routes based on toggle_state + conversation history. No pending_state.
        conversation_reply = cooperation. The user is responding positively
        to whatever the bot asked.
        """
        text = message.text.strip()
        response = None

        # Check which toggle is in an active flow
        # Priority: active_goal_pending flows first, then offered toggles

        # Nutrition goal flow (multi-step: body stats -> weight goal -> confirm)
        nt = profile.toggles.nutrition
        if nt.status == "active" and nt.goal_status == "pending" and nt.goal_offered_at and self.goal_service:
            response = self._route_nutrition_goal_flow(tid, text, profile)
            if response:
                await message.reply_text(response)
                self._save_bot_message(tid, response)
                return

        # Other habit goal flows (sleep, workouts, eating_window)
        for name in ("sleep", "eating_window", "workouts"):
            toggle = getattr(profile.toggles, name, None)
            if toggle and toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
                if self.goal_service:
                    response = self.goal_service.handle_goal_value(tid, name, text)
                    if response:
                        await message.reply_text(response)
                        self._save_bot_message(tid, response)
                        return

        # Remind pending: user is answering "want me to remind you?"
        for name in ("nutrition", "sleep", "eating_window", "workouts"):
            toggle = getattr(profile.toggles, name, None)
            if toggle and toggle.goal_status == "remind_pending":
                if self.goal_service:
                    response = self.goal_service.handle_remind_accept(tid, name)
                    if response:
                        await message.reply_text(response)
                        self._save_bot_message(tid, response)
                        return

        # Offered but not activated: user is accepting the offer
        for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care"):
            toggle = getattr(profile.toggles, name, None)
            if toggle and toggle.revealed_at and toggle.status == "dormant":
                self.toggle_service.activate_toggle(tid, name)
                if self.goal_service and self.goal_service.should_offer_goal(profile, name):
                    response = self.goal_service.offer_goal_with_shortcut(tid, name, text)
                else:
                    import messages as M
                    loop_close = M.LOOP_CLOSE_ACTIVATION.get(name, "")
                    response = "יפה, נרשמתי." + loop_close
                await message.reply_text(response)
                self._save_bot_message(tid, response)
                return

        # Feedback reaction: check if recent bot message was feedback
        if self.feedback_service:
            recent = self.user_repo.get_recent_messages(tid, 3)
            for msg in reversed(recent):
                if msg.get("role") == "bot" and "💬" in msg.get("text", ""):
                    steering = profile.feedback_steering_prompt if profile else None
                    response = self.feedback_service.process_reaction(tid, text, steering)
                    if response:
                        await message.reply_text(response)
                        self._save_bot_message(tid, response)
                        return
                if msg.get("role") == "user":
                    break

        # Safety net: no route matched - don't silently fail
        logger.warning("conversation_reply matched no route for tid=%d, text=%r", tid, text)
        fallback = "לא הבנתי על מה אתה עונה. אפשר לנסות שוב?"
        await message.reply_text(fallback)
        self._save_bot_message(tid, fallback)

    def _route_nutrition_goal_flow(self, tid: int, text: str, profile: UserProfile) -> str | None:
        """Route within the nutrition multi-step goal flow.

        Uses structural signals instead of keyword matching:
        - goal_value set by handle_weight_goal -> step 3 (confirm)
        - last bot message in NUTRITION_WEIGHT_GOAL_ASK pool -> step 2
        - default -> step 1 (body stats)
        """
        import messages as M

        nt = profile.toggles.nutrition

        # Step 3: suggestion was presented (goal_value stored by handle_weight_goal)
        if nt.goal_value:
            return self.goal_service.handle_nutrition_confirm(tid, text)

        # Step 2: bot asked about weight goal direction
        recent = self.user_repo.get_recent_messages(tid, 5)
        last_bot_msg = ""
        for msg in reversed(recent):
            if msg.get("role") == "bot":
                last_bot_msg = msg.get("text", "")
                break

        if last_bot_msg in M.NUTRITION_WEIGHT_GOAL_ASK:
            return self.goal_service.handle_weight_goal(tid, text, self._get_profile(tid))

        # Step 1 (default): collect body stats
        return self.goal_service.handle_body_stats(tid, text)

    # ------------------------------------------------------------------
    # Toggle cancel handler (context-aware refusal)
    # ------------------------------------------------------------------

    async def _handle_toggle_cancel(
        self, message, context, tid: int, profile: UserProfile, classification,
    ):
        """Handle toggle_cancel with context-aware behavior.

        Distinguishes:
        - Decline during remind_pending -> permanent decline (GOAL_DECLINED_FOREVER)
        - Decline during goal-setting -> keep habit active, skip goal, ask remind
        - Decline during offer (not yet activated) -> ask remind
        - Cancel an active habit (no flow) -> full cancel (EXIT_DOOR_CANCELLED)

        refusal_tone (sharp/soft) affects the message but not the flow.
        """
        import messages as M
        import random

        if not self.toggle_service:
            return

        toggle_name = classification.toggle_name
        if not toggle_name:
            # Infer from offered toggle or active goal-pending toggle
            for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care"):
                toggle = getattr(profile.toggles, name, None)
                if toggle and toggle.revealed_at and toggle.status == "dormant":
                    toggle_name = name
                    break
            if not toggle_name:
                for name in ("nutrition", "sleep", "eating_window", "workouts"):
                    toggle = getattr(profile.toggles, name, None)
                    if toggle and toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
                        toggle_name = name
                        break

        if not toggle_name or toggle_name not in {"sleep", "eating_window", "workouts", "self_care", "nutrition", "weekly_summary"}:
            return

        toggle = getattr(profile.toggles, toggle_name, None)
        tone = classification.refusal_tone or "sharp"

        # Case 1: Decline during remind_pending -> permanent decline
        if toggle and toggle.goal_status == "remind_pending":
            self.toggle_service.cancel_toggle(tid, toggle_name)
            response = random.choice(M.GOAL_DECLINED_FOREVER)
            await message.reply_text(response)
            self._save_bot_message(tid, response)
            return

        # Case 2: Decline during goal-setting (active + goal pending)
        if toggle and toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
            if self.goal_service:
                self.goal_service.skip_goal(tid, toggle_name)

                # Per-habit soft decline message
                soft_pools = {
                    "nutrition": M.GOAL_SOFT_DECLINE_NUTRITION,
                    "sleep": M.GOAL_SOFT_DECLINE_SLEEP,
                    "workouts": M.GOAL_SOFT_DECLINE_WORKOUTS,
                    "eating_window": M.GOAL_SOFT_DECLINE_EATING_WINDOW,
                }
                pool = soft_pools.get(toggle_name)
                if pool:
                    decline_msg = random.choice(pool)
                    remind_msg = self.goal_service.ask_remind(tid, toggle_name)
                    response = decline_msg + "\n\n" + remind_msg
                else:
                    response = self.goal_service.ask_remind(tid, toggle_name)

                await message.reply_text(response)
                self._save_bot_message(tid, response)
            return

        # Case 3: Decline during offer (dormant + revealed, not yet activated)
        if toggle and toggle.revealed_at and toggle.status == "dormant":
            if tone == "soft":
                response = random.choice(M.OFFER_SOFT_DECLINE)
            else:
                response = random.choice(M.OFFER_SHARP_DECLINE)
            # Set remind_pending so the handler catches the user's next answer
            if self.goal_service:
                self.goal_service.ask_remind(tid, toggle_name)
            await message.reply_text(response)
            self._save_bot_message(tid, response)
            return

        # Case 4: Cancel an active habit (no pending flow) -> full cancel
        self.toggle_service.cancel_toggle(tid, toggle_name)
        await message.reply_text(M.EXIT_DOOR_CANCELLED)
        self._save_bot_message(tid, M.EXIT_DOOR_CANCELLED)

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
                f"כדי להתחיל, הירשם כאן: {self.landing_page_url}"
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
            await message.reply_text(f"צריך להירשם קודם: {self.landing_page_url}")
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
            await message.reply_text(f"צריך להירשם קודם: {self.landing_page_url}")
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

        today_str = self._get_today_str(profile)
        time_str = self._get_time_str(profile)
        within_window = self._is_within_window(profile)
        day_name = hebrew_day_name(get_user_now(profile.timezone))

        last_entry = context.chat_data.get("last_entry")

        # Save user message and fetch conversation history
        from constants import MAX_RECENT_MESSAGES
        from datetime import timezone as tz

        # Capture Telegram reply-to-message context (user swiped left on a message)
        reply_context = None
        if message.reply_to_message and message.reply_to_message.text:
            reply_context = message.reply_to_message.text[:300]

        # Save user message (including reply context if present)
        user_msg = {
            "role": "user",
            "text": message.text[:500],
            "timestamp": datetime.now(tz.utc).isoformat(),
        }
        if reply_context:
            user_msg["replying_to"] = reply_context
        self.user_repo.push_messages(tid, [user_msg], MAX_RECENT_MESSAGES)
        recent_messages = self.user_repo.get_recent_messages(tid, MAX_RECENT_MESSAGES)

        # Build toggle state summary (always present - gives classifier the full picture)
        toggle_labels = {
            "nutrition": "תזונה", "sleep": "שינה", "eating_window": "חלון אכילה",
            "workouts": "אימונים", "self_care": "משהו לעצמי", "weekly_summary": "סיכום שבועי",
        }
        toggle_lines = []
        for name, label in toggle_labels.items():
            toggle = getattr(profile.toggles, name, None)
            if not toggle:
                continue
            if toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
                toggle_lines.append(f"- {label}: פעיל, בתהליך הגדרת יעד")
            elif toggle.status == "active":
                goal = f", יעד: {toggle.goal_value}" if toggle.goal_value else ", בלי יעד"
                toggle_lines.append(f"- {label}: פעיל{goal}")
            elif toggle.goal_status == "remind_pending":
                toggle_lines.append(f"- {label}: סירב, שאלנו אם להזכיר")
            elif toggle.revealed_at and toggle.status == "dormant":
                toggle_lines.append(f"- {label}: הוצע, ממתין לתשובה")
            elif toggle.status == "dormant":
                toggle_lines.append(f"- {label}: לא הוצע עדיין")
            elif toggle.status == "cancelled":
                toggle_lines.append(f"- {label}: בוטל")
        toggle_state = "\n".join(toggle_lines) if toggle_lines else None

        # Classifier is the SINGLE entry point for ALL messages.
        classification = self.analyzer.classify_message(
            message.text, today_str, last_entry,
            recent_messages=recent_messages[:-1],
            toggle_state=toggle_state,
            reply_context=reply_context,
            day_name=day_name,
        )

        # conversation_reply: user is responding to something the bot asked
        if classification.type == "conversation_reply":
            await self._handle_conversation_reply(
                message, context, tid, profile, classification,
            )
            return

        # Route non-food types through MessageRouterService
        if classification.type == "correction" and classification.correction and last_entry:
            await self._handle_correction(message, context, classification.correction, last_entry, profile, today_str, tid)
            return

        if classification.type == "sleep" and self.message_router:
            if classification.habit_entries:
                text = self._process_habit_entries(tid, classification.habit_entries, today_str)
            else:
                result = self.message_router.route_sleep(tid, classification.sleep_time or time_str, today_str)
                text = result.response_text
            edu = self._get_education_intro(tid, "sleep", profile)
            text = f"{text}\n\n{edu}" if edu else text
            await message.reply_text(text)
            self._save_bot_message(tid, text)
            return

        if classification.type == "workout" and self.message_router:
            if classification.habit_entries:
                text = self._process_habit_entries(tid, classification.habit_entries, today_str)
            else:
                result = self.message_router.route_workout(tid, today_str, classification.workout_note)
                text = result.response_text
            edu = self._get_education_intro(tid, "workouts", profile)
            text = f"{text}\n\n{edu}" if edu else text
            await message.reply_text(text)
            self._save_bot_message(tid, text)
            return

        if classification.type == "self_care" and self.message_router:
            if classification.habit_entries:
                text = self._process_habit_entries(tid, classification.habit_entries, today_str)
            else:
                from datetime import datetime as dt
                week_id = dt.strptime(today_str, "%d/%m/%Y").strftime("%G-W%V")
                result = self.message_router.route_self_care(tid, classification.self_care_description or message.text, week_id)
                text = result.response_text
            edu = self._get_education_intro(tid, "self_care", profile)
            text = f"{text}\n\n{edu}" if edu else text
            await message.reply_text(text)
            self._save_bot_message(tid, text)
            return

        if classification.type == "help" and self.message_router:
            result = self.message_router.route_help(
                classification.question_text or message.text,
                recent_messages=recent_messages,
                telegram_user_id=tid,
            )
            await send_long_text(message, result.response_text, reply_markup=make_daily_summary_keyboard())
            self._save_bot_message(tid, result.response_text)
            return

        if classification.type == "answer_question" and self.message_router:
            result = self.message_router.route_answer_question(
                tid, classification.question_text or message.text,
                today_str, self._target_cal(profile), self._target_prot(profile),
            )
            await send_long_text(message, result.response_text, reply_markup=make_daily_summary_keyboard())
            return

        if classification.type == "toggle_cancel":
            await self._handle_toggle_cancel(message, context, tid, profile, classification)
            return

        if classification.type == "toggle_activate" and self.toggle_service:
            toggle_name = classification.toggle_name
            if toggle_name and toggle_name in {"sleep", "eating_window", "workouts", "self_care", "nutrition", "weekly_summary"}:
                self.toggle_service.activate_toggle(tid, toggle_name)
                if self.goal_service and self.goal_service.should_offer_goal(profile, toggle_name):
                    response = self.goal_service.offer_goal_with_shortcut(tid, toggle_name, text)
                    await message.reply_text(response)
                    self._save_bot_message(tid, response)
                else:
                    import messages as M
                    loop_close = M.LOOP_CLOSE_ACTIVATION.get(toggle_name, "")
                    response = "יפה, נרשמתי. מעכשיו אני עוקב." + loop_close
                    await message.reply_text(response)
            else:
                await message.reply_text("לא הבנתי איזה מעקב להדליק. נסה שוב?")
            return

        if classification.type == "name_declaration" and self.onboarding_service:
            name = classification.declared_name or message.text.strip()
            # Late = greeting is NOT the last bot message (user has been chatting)
            recent = self.user_repo.get_recent_messages(tid, 5)
            last_bot = next((m for m in reversed(recent) if m.get("role") == "bot"), None)
            late = not (last_bot and "איך אתה רוצה שאקרא לך?" in last_bot.get("text", ""))
            response = self.onboarding_service.handle_name_response(tid, name, late=late)
            if response:
                await message.reply_text(response)
                self._save_bot_message(tid, response)
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

        if classification.type == "none":
            response = classification.freeform_response or "מה נשמע?"
            await message.reply_text(response)
            self._save_bot_message(tid, response)
            return

        # Default: treat as food (meal type or fallback)
        from analyzer import TimedFoodAnalysisResult, TimedFoodGroup

        if classification.type == "meal" and classification.meal and classification.meal.groups:
            food_result = classification.meal
        else:
            food_result = self.analyzer.analyze_food_text(message.text, today_str, day_name)

        if food_result is None or not food_result.groups:
            await message.reply_text("לא הצלחתי לזהות מאכל בהודעה. נסה שוב?")
            return

        # Create one FoodEntry per temporal group
        saved_entries: list[tuple[TimedFoodGroup, FoodEntry]] = []
        for group in food_result.groups:
            combined_desc = ", ".join(item.description for item in group.items)
            entry = FoodEntry(
                telegram_user_id=tid,
                date=group.date,
                time=group.time,
                description=combined_desc,
                calories=group.total_calories,
                protein=group.total_protein,
                within_window=within_window if group.date == today_str else True,
            )
            saved = self.food_repo.add(entry)
            saved_entries.append((group, saved))
            logger.info("Recorded: %s [%s %s] (%d cal, %dg protein) -> id %s",
                        combined_desc, group.date, group.time,
                        group.total_calories, group.total_protein, saved.id)

        # last_entry = chronologically latest (last group)
        last_group, last_saved = saved_entries[-1]
        last_desc = ", ".join(item.description for item in last_group.items)
        context.chat_data["last_entry"] = {
            "description": last_desc,
            "calories": last_group.total_calories,
            "protein": last_group.total_protein,
            "entry_id": last_saved.id,
        }

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        items_text = self._format_grouped_items_text(food_result.groups, stats_date)

        # Check if any group lands on today
        today_groups = [g for g in food_result.groups if g.date == stats_date]
        if today_groups:
            today_cal = sum(g.total_calories for g in today_groups)
            today_prot = sum(g.total_protein for g in today_groups)
            new_daily_cal, new_daily_prot = self.eating_day_svc.get_eating_day_totals(profile, stats_date)
            prev_cal = new_daily_cal - today_cal
            prev_protein = new_daily_prot - today_prot
            alerts = self._check_crossing_alerts(prev_cal, prev_protein, new_daily_cal, new_daily_prot, profile)
            response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)
            if alerts:
                response = f"{alerts}\n\n{response}"
        else:
            # All entries are retroactive - no daily summary
            retro_labels = [g.temporal_label for g in food_result.groups]
            response = f"{items_text}\n\n✅ נרשם ({', '.join(retro_labels)})"

        last_entry_id = last_saved.id
        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(last_entry_id))
        await safe_react(message, OK_HAND)
        self._save_bot_message(tid, response)

        # Mixed-type: process habit entries that came alongside the meal
        if classification.habit_entries:
            habit_text = self._process_habit_entries(tid, classification.habit_entries, today_str)
            if habit_text:
                await message.reply_text(habit_text)
                self._save_bot_message(tid, habit_text)

        # Protein education on first meal ever
        if len(self.food_repo.get_all_for_user(tid)) == 1:
            from dugri_messages import EDU_INTRO_FIRST_LOG
            edu = EDU_INTRO_FIRST_LOG.get("protein")
            if edu:
                await message.reply_text(edu)

        # Recompute eating window from actual meal history
        await self._recompute_eating_window(context, tid, profile)

        # Inline conversation hooks: check if any hooks should fire after this meal
        await self._check_inline_hooks(message, tid, profile)

    # ------------------------------------------------------------------
    # Eating window auto-computation
    # ------------------------------------------------------------------

    async def _recompute_eating_window(self, context, tid: int, profile: UserProfile):
        """Recompute eating window from food entries if toggle is active."""
        if not profile.toggles or profile.toggles.eating_window.status != "active":
            return

        new_window = self.eating_day_svc.compute_eating_window(tid)
        if not new_window:
            return

        old = profile.eating_window
        if old and old.start == new_window.start and old.end == new_window.end:
            return

        self.user_repo.update_fields(tid, {
            "eating_window.start": new_window.start,
            "eating_window.end": new_window.end,
        })
        # No PTB job rescheduling needed - the global poller reads
        # fresh data from MongoDB each tick.

    # ------------------------------------------------------------------
    # Piggyback hooks - fire pending hooks after a meal
    # ------------------------------------------------------------------

    async def _check_inline_hooks(self, message, tid: int, profile: UserProfile):
        """After a meal is logged, check if any hooks should inline hook.

        Waits INLINE_HOOK_DELAY_SECONDS before sending, so the bot feels
        like it's pausing before bringing up a new topic.
        """
        if not self.toggle_service:
            return

        import asyncio
        from scheduler import should_fire_inline
        from user_clock import UserClock
        import messages as M
        import random
        from constants import (
            WORKOUTS_ANCHOR_DAY, SELF_CARE_ANCHOR_DAY, WEEKLY_SUMMARY_ANCHOR_DAY,
            INLINE_HOOK_DELAY_SECONDS,
        )

        # Single delay: pause between the food response and whatever comes next.
        # This makes it feel like Dugri is thinking before changing topic.
        await asyncio.sleep(INLINE_HOOK_DELAY_SECONDS)

        clock = UserClock(profile.timezone)
        day_number = self.toggle_service.get_day_number(profile)
        weekday = clock.weekday()

        # Goal reminders (due reminders fire first)
        if self.goal_service:
            due = self.goal_service.check_goal_reminders(profile)
            if due:
                text = self.goal_service.fire_goal_reminder(tid, due[0])
                await message.reply_text(text)
                self._save_bot_message(tid, text)
                return

        # Nutrition reveal (after first meal, gate_days=0)
        if self.toggle_service.should_reveal_nutrition(profile):
            self.toggle_service.reveal_toggle(tid, "nutrition")
            await message.reply_text(M.REVEAL_NUTRITION)
            self._save_bot_message(tid, M.REVEAL_NUTRITION)
            return

        # Day 16 dashboard intro
        if self.toggle_service.should_show_dashboard_intro(profile, day_number):
            self.user_repo.update_fields(tid, {"dashboard_intro_shown": True})
            await message.reply_text(M.DASHBOARD_INTRO)

        # Toggle reveals (one-time offers)
        reveals = [
            ("sleep", self.toggle_service.should_reveal_sleep(profile), M.REVEAL_SLEEP),
            ("eating_window", self.toggle_service.should_reveal_eating_window(profile), M.REVEAL_EATING_WINDOW),
            ("workouts", self.toggle_service.should_reveal_workouts(profile, weekday), M.REVEAL_WORKOUTS),
            ("self_care", self.toggle_service.should_reveal_self_care(profile, weekday), M.REVEAL_SELF_CARE),
        ]

        for toggle_name, should_reveal, reveal_msg in reveals:
            if should_reveal:
                self.toggle_service.reveal_toggle(tid, toggle_name)
                await message.reply_text(reveal_msg)
                self._save_bot_message(tid, reveal_msg)
                return

        # Recurring hooks inline hook (with anchor day check for weekly hooks)
        inline_hooks = [
            ("sleep", M.HOOK_SLEEP_PROMPTS, None),
            ("workouts", M.HOOK_WORKOUTS_PROMPTS, WORKOUTS_ANCHOR_DAY),
            ("self_care", M.HOOK_SELF_CARE_PROMPTS, SELF_CARE_ANCHOR_DAY),
        ]

        for toggle_name, pool, anchor_day in inline_hooks:
            if anchor_day is not None and weekday != anchor_day:
                continue
            if should_fire_inline(profile, toggle_name, clock):
                text = random.choice(pool)
                if self.toggle_service.should_show_exit_door(profile, toggle_name):
                    habit_names = {
                        "sleep": "שינה", "eating_window": "חלון אכילה",
                        "workouts": "אימונים", "self_care": "משהו לעצמי",
                    }
                    text += "\n\n" + random.choice(M.EXIT_DOOR_PROMPTS).format(
                        habit=habit_names.get(toggle_name, "")
                    )
                self.toggle_service.record_asked(tid, toggle_name)
                self.toggle_service.increment_unanswered(tid, profile, toggle_name)
                await message.reply_text(text)
                self._save_bot_message(tid, text)
                return

        # Weekly summary inline hook (Sunday only)
        if weekday == WEEKLY_SUMMARY_ANCHOR_DAY and should_fire_inline(profile, "weekly_summary", clock):
            self.toggle_service.record_asked(tid, "weekly_summary")
            self.toggle_service.increment_unanswered(tid, profile, "weekly_summary")
            await message.reply_text(M.WEEKLY_SUMMARY_OFFER)
            self._save_bot_message(tid, M.WEEKLY_SUMMARY_OFFER)

    async def _handle_correction(
        self, message, context, correction, last_entry: dict,
        profile: UserProfile, today_str: str, tid: int,
    ):
        from datetime import timezone as tz

        entry_id = last_entry["entry_id"]
        old_cal = last_entry["calories"]
        old_prot = last_entry["protein"]
        old_desc = last_entry["description"]

        new_desc = correction.corrected_description
        new_cal = correction.corrected_calories
        new_prot = correction.corrected_protein

        # Preserve originals on first correction; keep existing originals on subsequent ones
        orig_desc = last_entry.get("original_description") or old_desc
        orig_cal = last_entry.get("original_calories") or old_cal
        orig_prot = last_entry.get("original_protein") or old_prot

        updated_history = context.chat_data.get("correction_histories", {}).get(entry_id, [])
        updated_history = updated_history + [message.text]

        self.food_repo.update(entry_id, {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
            "original_description": orig_desc,
            "original_calories": orig_cal,
            "original_protein": orig_prot,
            "correction_history": updated_history,
            "edit_expires_at": datetime.now(tz.utc) + timedelta(hours=48),
        })

        context.chat_data["last_entry"] = {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
            "entry_id": entry_id,
            "photo_file_id": last_entry.get("photo_file_id"),
            "original_description": orig_desc,
            "original_calories": orig_cal,
            "original_protein": orig_prot,
        }

        stats_date = self.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        final_cal, final_prot = self.eating_day_svc.get_eating_day_totals(profile, stats_date)

        # Build 3-section response: original -> edits -> updated
        response = self._format_correction_response(
            correction, orig_desc, orig_cal, orig_prot, new_cal, new_prot,
        )
        status = format_daily_status(
            final_cal, final_prot, self._target_cal(profile), self._target_prot(profile),
        )
        response += status

        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(entry_id))
        await safe_react(message, OK_HAND)

    @staticmethod
    def _format_correction_response(
        correction, orig_desc: str, orig_cal: int, orig_prot: int,
        new_cal: int, new_prot: int,
    ) -> str:
        """Format the 3-section correction response: original -> edits -> updated."""
        parts = []

        # Section 1: Original entry
        parts.append(f"📋 רשומה מקורית: {orig_desc}")
        parts.append(f"סה\"כ: {orig_cal} קל׳ | {orig_prot} גרם חלבון")

        # Section 2: What changed
        edit_lines = []
        for item in correction.items:
            if item.change_type == "modified":
                edit_lines.append(f"• {item.description}: ~{item.estimated_grams} גרם | {item.calories} קל׳ | {item.protein} גרם חלבון")
            elif item.change_type == "added":
                edit_lines.append(f"• {item.description}: חדש (~{item.estimated_grams} גרם | {item.calories} קל׳ | {item.protein} גרם חלבון)")
            elif item.change_type == "removed":
                edit_lines.append(f"• {item.description}: הוסר")
        if edit_lines:
            parts.append("")
            parts.append("✏️ עריכה:")
            parts.extend(edit_lines)

        # Section 3: Updated entry (all non-removed items)
        active_items = [i for i in correction.items if i.change_type != "removed"]
        if active_items:
            parts.append("")
            parts.append("✅ רשומה מעודכנת:")
            for item in active_items:
                parts.append(f"• {item.description}")
                parts.append(f"  ~{item.estimated_grams} גרם | {item.calories} קל׳ | {item.protein} גרם חלבון")
            if len(active_items) > 1:
                parts.append(f"\nסה\"כ: {new_cal} קל׳ | {new_prot} גרם חלבון")

        return "\n".join(parts)

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
            await message.reply_text(f"צריך להירשם קודם: {self.landing_page_url}")
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
            photo_file_id=photo.file_id,
        )
        saved = self.food_repo.add(entry)

        context.chat_data["last_entry"] = {
            "description": combined_desc,
            "calories": total_cal,
            "protein": total_prot,
            "entry_id": saved.id,
            "photo_file_id": photo.file_id,
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

        if result.unidentified_items:
            response += "\n\n❓ " + ", ".join(result.unidentified_items) + "\nמה זה? שלח תיאור או תקן דרך הכפתור ✏️"

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
            if field == "target_calories":
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

        except ValueError:
            await message.reply_text("ערך לא תקין. נסה שוב.")
        except Exception:
            logger.exception("Failed to update profile field %s", field)

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

        # Re-download photo if available so the LLM has visual context
        photo_b64 = None
        photo_file_id = entry.get("photo_file_id")
        if photo_file_id:
            try:
                file = await context.bot.get_file(photo_file_id)
                photo_bytes = await file.download_as_bytearray()
                photo_b64 = base64.b64encode(photo_bytes).decode("utf-8")
            except Exception:
                logger.warning("Failed to re-download photo %s for correction", photo_file_id)

        correction = self.analyzer.analyze_correction(
            original_description=entry["description"],
            original_calories=entry["calories"],
            original_protein=entry["protein"],
            correction_history=correction_history,
            new_correction=message.text,
            today_str=today_str,
            photo_base64=photo_b64,
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

            existing_history = food_entry.correction_history or \
                context.chat_data.get("correction_histories", {}).get(entry_id, [])
            context.chat_data["pending_correction"] = {
                "entry": {
                    "description": food_entry.description,
                    "calories": food_entry.calories,
                    "protein": food_entry.protein,
                    "entry_id": entry_id,
                    "photo_file_id": food_entry.photo_file_id,
                    "original_description": food_entry.original_description,
                    "original_calories": food_entry.original_calories,
                    "original_protein": food_entry.original_protein,
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
