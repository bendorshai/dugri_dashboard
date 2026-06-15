"""
context.py - HandlerContext: shared services, repos, and utility methods.

All handler modules receive a HandlerContext instance to access
services and common helpers like _send(), _get_profile(), etc.
"""

from __future__ import annotations

import logging
import secrets
from collections import OrderedDict
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from analyzer import FoodAnalyzer, _token_callback_var
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
    make_emotional_support_keyboard, make_emotional_creator_keyboard,
    CB_MENU, CB_PROFILE, CB_EDIT_FIELD, CB_SUGGEST,
    CB_ASK, CB_FOOD_EDIT, CB_FOOD_DELETE, CB_FOOD_AGAIN, CB_WEEKLY, CB_DAILY, CB_BACK,
    CB_FEEDBACK, CB_EMOTIONAL,
)
from handlers.utils import PENDING_STATE_TTL, safe_react, send_long_text, send_long_bot, safe_answer

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


class HandlerContext:
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
        emotional_support_service=None,
        conversational_service=None,
        re_engagement_service=None,
        landing_page_url: str = "https://www.dugri.life",
        admin_chat_id: int = 0,
        token_log_repo=None,
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
        self.emotional_support_service = emotional_support_service
        self.conversational_service = conversational_service
        self.re_engagement_service = re_engagement_service
        self.gem_service = None  # set externally after construction
        self.admin_chat_id = admin_chat_id
        self.token_log_repo = token_log_repo
        self._debug_classification = None
        self._debug_router_type = None
        self._debug_mode = False
        self._debug_store: OrderedDict = OrderedDict()

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def _setup_token_tracking(self, tid: int) -> None:
        if not getattr(self, "token_log_repo", None):
            return
        user_repo = self.user_repo
        token_log_repo = self.token_log_repo

        def _report(model: str, prompt_tokens: int, completion_tokens: int) -> None:
            date_str = get_user_now("Asia/Jerusalem").strftime("%Y-%m-%d")
            user_repo.increment_tokens(tid, model, prompt_tokens, completion_tokens)
            token_log_repo.log(tid, model, date_str, prompt_tokens, completion_tokens)

        _token_callback_var.set(_report)

    # ------------------------------------------------------------------
    # Conversation history helpers
    # ------------------------------------------------------------------

    def _save_bot_message(self, tid: int, text: str) -> None:
        from constants import MAX_RECENT_MESSAGES
        from datetime import timezone as tz
        msg = {
            "role": "bot",
            "text": text[:500],
            "timestamp": datetime.now(tz.utc).isoformat(),
        }
        self.user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)

    async def _send(self, text: str, *, tid: int, message=None, context=None,
                    reply_markup=None, save=True):
        if save:
            self._save_bot_message(tid, text)

        send_text, final_markup = self._prepare_debug(tid, text, reply_markup)

        if message:
            await send_long_text(message, send_text, reply_markup=final_markup)
        elif context:
            await send_long_bot(context.bot, tid, send_text, reply_markup=final_markup)

    def _prepare_debug(self, tid: int, text: str, reply_markup=None):
        if not self._debug_mode or tid != getattr(self, "admin_chat_id", 0):
            return text, reply_markup
        profile = self._get_profile(tid)
        if not profile:
            return text, reply_markup
        from handlers.utils import format_debug_metadata
        from keyboards import inject_debug_button
        metadata = format_debug_metadata(
            getattr(self, "_debug_classification", None), profile, self.toggle_service,
        )
        key = secrets.token_hex(4)
        self._debug_store[key] = metadata
        while len(self._debug_store) > 200:
            self._debug_store.popitem(last=False)
        return text, inject_debug_button(reply_markup, key)

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
        toggle = getattr(profile.toggles, toggle_name, None)
        if toggle is None or toggle.edu_intro_shown:
            return None
        from dugri_messages import EDU_INTRO_FIRST_LOG
        text = EDU_INTRO_FIRST_LOG.get(toggle_name)
        if text:
            self.user_repo.update_fields(tid, {f"toggles.{toggle_name}.edu_intro_shown": True})
        return text

    # ------------------------------------------------------------------
    # Habit entry processing
    # ------------------------------------------------------------------

    def _process_habit_entries(self, tid: int, entries, today_str: str) -> str | None:
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

    # ------------------------------------------------------------------
    # Food response formatting
    # ------------------------------------------------------------------

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
