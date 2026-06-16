"""
base.py - HealthHandlers facade + main message router.

Thin layer that wires sub-handlers and dispatches text messages.
All shared state/utilities live in HandlerContext.
"""

from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from models.food import FoodEntry
from models.profile import UserProfile
from parsing import get_user_now, hebrew_day_name
from keyboards import (
    OK_HAND,
    make_daily_summary_keyboard, make_main_menu_keyboard,
    make_food_entry_keyboard, format_daily_status,
    make_emotional_support_keyboard, make_emotional_creator_keyboard,
    make_sleep_entry_keyboard, make_workout_entry_keyboard, make_self_care_entry_keyboard,
)
from handlers.utils import safe_react, send_long_text, send_long_bot
from handlers.context import HandlerContext
from handlers.callback_handler import CallbackHandler
from handlers.food_handler import FoodHandler
from handlers.toggle_handler import ToggleHandler
from handlers.hook_handler import HookHandler
from handlers.pending_handler import PendingHandler

logger = logging.getLogger(__name__)


def _validate_resolved_date(date_str: str | None) -> str | None:
    """Return date_str if valid DD/MM/YYYY and not in the future, else None."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        if dt.date() > datetime.now().date():
            return None
        return date_str
    except ValueError:
        return None


class HealthHandlers:
    def __init__(
        self,
        analyzer,
        user_repo,
        food_repo,
        feedback_repo,
        eating_day_service,
        onboarding_service=None,
        message_router=None,
        trial_service=None,
        feedback_service=None,
        toggle_service=None,
        goal_service=None,
        emotional_support_service=None,
        conversational_service=None,
        re_engagement_service=None,
        landing_page_url: str = "https://www.dugri.life",
        admin_chat_id: int = 0,
        token_log_repo=None,
        sleep_repo=None,
        workout_repo=None,
        self_care_repo=None,
    ):
        # Shared context for all sub-handlers
        self.ctx = HandlerContext(
            analyzer=analyzer,
            user_repo=user_repo,
            food_repo=food_repo,
            feedback_repo=feedback_repo,
            eating_day_service=eating_day_service,
            onboarding_service=onboarding_service,
            message_router=message_router,
            trial_service=trial_service,
            feedback_service=feedback_service,
            toggle_service=toggle_service,
            goal_service=goal_service,
            emotional_support_service=emotional_support_service,
            conversational_service=conversational_service,
            re_engagement_service=re_engagement_service,
            landing_page_url=landing_page_url,
            admin_chat_id=admin_chat_id,
            token_log_repo=token_log_repo,
            sleep_repo=sleep_repo,
            workout_repo=workout_repo,
            self_care_repo=self_care_repo,
        )

        # Sub-handlers
        self._cb = CallbackHandler(self.ctx)
        self._food = FoodHandler(self.ctx)
        self._toggle = ToggleHandler(self.ctx, parent=self)
        self._hooks = HookHandler(self.ctx)
        self._pending = PendingHandler(self.ctx)

        self._wire_callback_delegation()

    def _wire_callback_delegation(self):
        """Wire callback handlers to sub-handler instances."""
        self.handle_debug_callback = self._cb.handle_debug_callback
        self.handle_gem_callback = self._cb.handle_gem_callback
        self.handle_menu_callback = self._cb.handle_menu_callback
        self.handle_profile_callback = self._cb.handle_profile_callback
        self.handle_edit_field_callback = self._cb.handle_edit_field_callback
        self.handle_suggest_callback = self._cb.handle_suggest_callback
        self.handle_ask_callback = self._cb.handle_ask_callback
        self.handle_feature_request_callback = self._cb.handle_feature_request_callback
        self.handle_food_delete_callback = self._cb.handle_food_delete_callback
        self.handle_food_edit_callback = self._cb.handle_food_edit_callback
        self.handle_food_again_callback = self._cb.handle_food_again_callback
        self.handle_daily_callback = self._cb.handle_daily_callback
        self.handle_weekly_callback = self._cb.handle_weekly_callback
        self.handle_back_callback = self._cb.handle_back_callback
        self.handle_feedback_callback = self._cb.handle_feedback_callback
        self.handle_emotional_callback = self._cb.handle_emotional_callback
        self.handle_sleep_edit_callback = self._cb.handle_sleep_edit_callback
        self.handle_sleep_delete_callback = self._cb.handle_sleep_delete_callback
        self.handle_workout_edit_callback = self._cb.handle_workout_edit_callback
        self.handle_workout_delete_callback = self._cb.handle_workout_delete_callback
        self.handle_selfcare_edit_callback = self._cb.handle_selfcare_edit_callback
        self.handle_selfcare_delete_callback = self._cb.handle_selfcare_delete_callback
        self.handle_photo = self._food.handle_photo

    def __getattr__(self, name):
        """Fallback attribute lookup: check ctx, then sub-handlers.

        This makes HealthHandlers backward-compatible with tests that use
        __new__ and set attributes directly (no __init__), AND with production
        code that delegates through ctx and sub-handlers.
        """
        # Avoid infinite recursion for 'ctx' itself
        if name == "ctx":
            raise AttributeError(name)
        # Try ctx (services, repos, utility methods)
        ctx = self.__dict__.get("ctx")
        if ctx is not None:
            try:
                return getattr(ctx, name)
            except AttributeError:
                pass
        # Lazily create sub-handlers for __new__ test pattern
        if name.startswith("handle_") and name.endswith("_callback"):
            cb = self.__dict__.get("_cb")
            if cb is None:
                cb = CallbackHandler(self)
                self._cb = cb
            try:
                return getattr(cb, name)
            except AttributeError:
                pass
        if name == "handle_photo":
            food = self.__dict__.get("_food")
            if food is None:
                food = FoodHandler(self)
                self._food = food
            return food.handle_photo
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # ------------------------------------------------------------------
    # Core methods (kept on HealthHandlers for backward compat with tests)
    # ------------------------------------------------------------------

    def _find_entry_by_message_id(self, tid: int, message_id: int) -> dict | None:
        """Search all entry collections for an entry linked to a Telegram message ID.

        Checks both user_message_id and bot_message_id across food_entries,
        sleep_logs, workout_logs, and self_care_logs. Returns a last_entry-
        compatible dict if found, or None.
        """
        query = {
            "telegram_user_id": tid,
            "$or": [
                {"user_message_id": message_id},
                {"bot_message_id": message_id},
            ],
        }

        # Check food entries
        if self.food_repo:
            doc = self.food_repo._collection.find_one(query)
            if doc:
                entry_id = str(doc["_id"])
                return {
                    "entry_id": entry_id,
                    "description": doc.get("description", ""),
                    "calories": doc.get("calories", 0),
                    "protein": doc.get("protein", 0),
                    "photo_file_id": doc.get("photo_file_id"),
                    "entry_type": "food",
                }

        # Check habit logs
        for repo, entry_type in [
            (getattr(self, "sleep_repo", None), "sleep"),
            (getattr(self, "workout_repo", None), "workout"),
            (getattr(self, "self_care_repo", None), "self_care"),
        ]:
            if not repo:
                continue
            doc = repo._collection.find_one(query)
            if doc:
                entry_id = str(doc["_id"])
                return {
                    "entry_id": entry_id,
                    "entry_type": entry_type,
                    "description": doc.get("note") or doc.get("description") or doc.get("sleep_time", ""),
                    "calories": 0,
                    "protein": 0,
                }

        return None

    def _store_message_ids(self, repo, entry_id: str | None, user_msg_id: int | None, bot_msg_id: int | None) -> None:
        """Store Telegram message IDs on an entry for reply-based correction lookup."""
        if not repo or not entry_id:
            return
        fields = {}
        if user_msg_id is not None:
            fields["user_message_id"] = user_msg_id
        if bot_msg_id is not None:
            fields["bot_message_id"] = bot_msg_id
        if fields:
            from bson import ObjectId
            try:
                repo.update_by_id(ObjectId(entry_id), fields)
            except Exception:
                logger.debug("Failed to store message IDs on entry %s", entry_id)

    def _save_bot_message(self, tid: int, text: str) -> None:
        from constants import MAX_RECENT_MESSAGES
        from datetime import timezone as tz
        msg = {
            "role": "bot",
            "text": text[:500],
            "timestamp": datetime.now(tz.utc).isoformat(),
        }
        classification = getattr(self, "_current_classification", None)
        if classification:
            msg["classification"] = classification
        self.user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)

    async def _send(self, text: str, *, tid: int, message=None, context=None,
                    reply_markup=None, save=True) -> int | None:
        if save:
            self._save_bot_message(tid, text)

        send_text, final_markup = self._prepare_debug(tid, text, reply_markup)

        if message:
            return await send_long_text(message, send_text, reply_markup=final_markup)
        elif context:
            return await send_long_bot(context.bot, tid, send_text, reply_markup=final_markup)
        return None

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
        key = __import__("secrets").token_hex(4)
        self._debug_store[key] = metadata
        while len(self._debug_store) > 200:
            self._debug_store.popitem(last=False)
        return text, inject_debug_button(reply_markup, key)

    def _get_profile(self, telegram_user_id: int):
        return self.user_repo.get(telegram_user_id)

    def _get_today_str(self, profile):
        now = get_user_now(profile.timezone)
        return self.eating_day_svc.get_stats_date(profile, now)

    def _get_time_str(self, profile):
        now = get_user_now(profile.timezone)
        return now.strftime("%H:%M")

    def _is_within_window(self, profile):
        from parsing import is_within_eating_window
        now = get_user_now(profile.timezone)
        ws = profile.eating_window.start if profile.eating_window else "00:00"
        we = profile.eating_window.end if profile.eating_window else "23:59"
        return is_within_eating_window(now, ws, we)

    def _target_cal(self, profile):
        nv = profile.toggles.nutrition.goal_value
        if nv and "calories" in nv:
            return nv["calories"]
        return profile.targets.calories or 2000

    def _target_prot(self, profile):
        nv = profile.toggles.nutrition.goal_value
        if nv and "protein" in nv:
            return nv["protein"]
        return profile.targets.protein or 150

    def _setup_token_tracking(self, tid: int) -> None:
        ctx = self.__dict__.get("ctx")
        if ctx:
            ctx._setup_token_tracking(tid)

    def _get_education_intro(self, tid, toggle_name, profile):
        ctx = self.__dict__.get("ctx")
        if ctx:
            return ctx._get_education_intro(tid, toggle_name, profile)
        return None

    def _build_food_response(self, items_text, total_cal, total_protein, profile):
        status = format_daily_status(
            total_cal, total_protein, self._target_cal(profile), self._target_prot(profile),
        )
        return f"{items_text}{status}"

    @staticmethod
    def _format_items_text(items, total_cal, total_prot):
        return HandlerContext._format_items_text(items, total_cal, total_prot)

    @staticmethod
    def _format_grouped_items_text(groups, today_str):
        return HandlerContext._format_grouped_items_text(groups, today_str)

    def _check_crossing_alerts(self, prev_cal, prev_protein, new_cal, new_protein, profile):
        ctx = self.__dict__.get("ctx")
        if ctx:
            return ctx._check_crossing_alerts(prev_cal, prev_protein, new_cal, new_protein, profile)
        alerts = []
        target_cal = self._target_cal(profile)
        target_prot = self._target_prot(profile)
        if prev_protein < target_prot <= new_protein:
            alerts.append("🎉 כל הכבוד! הגעת ליעד גרם החלבון היומי!")
        if prev_cal <= target_cal < new_cal:
            alerts.append("⚠️ שים לב — עברת את יעד הקלוריות היומי.")
        return "\n".join(alerts)

    def _process_habit_entries(self, tid, entries, today_str):
        ctx = self.__dict__.get("ctx")
        if ctx:
            return ctx._process_habit_entries(tid, entries, today_str)
        return None

    def _get_food_handler(self):
        f = self.__dict__.get("_food")
        if f is None:
            f = FoodHandler(self)
            self._food = f
        return f

    async def _recompute_eating_window(self, context, tid, profile):
        await self._get_food_handler().recompute_eating_window(context, tid, profile)

    async def _check_inline_hooks(self, message, tid, profile):
        hooks = self.__dict__.get("_hooks")
        if hooks:
            await hooks.check_inline_hooks(message, tid, profile)

    async def _handle_correction(self, message, context, correction, last_entry, profile, today_str, tid):
        await self._get_food_handler().handle_correction(message, context, correction, last_entry, profile, today_str, tid)

    def _get_toggle_handler(self):
        t = self.__dict__.get("_toggle")
        if t is None:
            t = ToggleHandler(self, parent=self)
            self._toggle = t
        return t

    async def _handle_conversation_reply(self, message, context, tid, profile, classification):
        await self._get_toggle_handler().handle_conversation_reply(message, context, tid, profile, classification)

    async def _handle_toggle_cancel(self, message, context, tid, profile, classification):
        await self._get_toggle_handler().handle_toggle_cancel(message, context, tid, profile, classification)

    async def _handle_opt_in(self, message, context, tid, profile, router_result):
        toggle_handler = self._get_toggle_handler()
        if toggle_handler.ctx is not None:
            await toggle_handler.handle_opt_in(message, context, tid, profile, router_result)
            return
        # Fallback for __new__ test pattern: inline logic
        text = message.text.strip()
        toggle_name = router_result.toggle_name
        if not toggle_name:
            for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care"):
                if self._is_toggle_in_flow(profile, name):
                    toggle_name = name
                    break
        if toggle_name:
            toggle = getattr(profile.toggles, toggle_name, None)
            if toggle:
                if toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
                    await self._handle_conversation_reply(message, context, tid, profile, router_result)
                    return
                if toggle.goal_status == "remind_pending":
                    await self._handle_conversation_reply(message, context, tid, profile, router_result)
                    return
                if toggle.revealed_at and toggle.status == "dormant":
                    await self._handle_conversation_reply(message, context, tid, profile, router_result)
                    return
                if toggle.goal_status == "set" and self.goal_service:
                    response = self.goal_service.handle_goal_update(tid, toggle_name, text, profile)
                    if response:
                        await self._send(response, tid=tid, message=message)
                        return
        if toggle_name and self.toggle_service:
            toggle = getattr(profile.toggles, toggle_name, None)
            if toggle and toggle.status in ("dormant", "cancelled"):
                self.toggle_service.activate_toggle(tid, toggle_name)
                if self.goal_service and self.goal_service.should_offer_goal(profile, toggle_name):
                    response = self.goal_service.offer_goal_with_shortcut(tid, toggle_name, text)
                    await self._send(response, tid=tid, message=message)
                else:
                    import messages as M
                    loop_close = M.LOOP_CLOSE_ACTIVATION.get(toggle_name, "")
                    response = "יפה, נרשמתי. מעכשיו אני עוקב." + loop_close
                    await self._send(response, tid=tid, message=message)
                return
        await self._handle_conversation_reply(message, context, tid, profile, router_result)

    def _is_toggle_in_flow(self, profile, toggle_name):
        toggle = self.__dict__.get("_toggle")
        if toggle:
            return toggle.is_toggle_in_flow(profile, toggle_name)
        return False

    def _any_toggle_in_flow(self, profile):
        toggle = self.__dict__.get("_toggle")
        if toggle:
            return toggle.any_toggle_in_flow(profile)
        return False

    def _get_pending_handler(self):
        p = self.__dict__.get("_pending")
        if p is None:
            p = PendingHandler(self)
            self._pending = p
        return p

    async def _handle_pending_edit(self, message, context, tid, profile):
        return await self._get_pending_handler().handle_pending_edit(message, context, tid, profile)

    async def _handle_pending_question(self, message, context, tid, profile):
        return await self._get_pending_handler().handle_pending_question(message, context, tid, profile)

    async def _handle_pending_correction(self, message, context, tid, profile):
        return await self._get_pending_handler().handle_pending_correction(message, context, tid, profile)

    async def _handle_pending_habit_correction(self, message, context, tid, profile):
        return await self._get_pending_handler().handle_pending_habit_correction(message, context, tid, profile)

    async def _handle_pending_feature_request(self, message, context, tid):
        return await self._get_pending_handler().handle_pending_feature_request(message, context, tid)

    @staticmethod
    def _format_correction_response(correction, orig_desc, orig_cal, orig_prot, new_cal, new_prot):
        return FoodHandler.format_correction_response(correction, orig_desc, orig_cal, orig_prot, new_cal, new_prot)

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
        await self._send(text, tid=tid, message=message, reply_markup=make_main_menu_keyboard(self.landing_page_url), save=False)

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
        await self._send(
            f"📋 תפריט ראשי{status}",
            tid=tid, message=message, reply_markup=make_main_menu_keyboard(self.landing_page_url), save=False,
        )

    # ------------------------------------------------------------------
    # Text message handler
    # ------------------------------------------------------------------

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.text:
            return

        tid = update.effective_user.id
        self._setup_token_tracking(tid)

        profile = self._get_profile(tid)
        if profile is None:
            await message.reply_text(f"צריך להירשם קודם: {self.landing_page_url}")
            return

        # Trial start: first real message starts the trial clock
        if (profile.subscription_status == "trial_active"
                and profile.trial_started_at is None):
            from datetime import timezone as _tz
            self.user_repo.update_fields(tid, {
                "trial_started_at": datetime.now(_tz.utc).isoformat(),
            })

        # Trial gating: check expiry, mark flag for dispatch override
        _trial_ended = False
        _is_first_post_trial = False
        if self.trial_service:
            self.trial_service.check_and_expire(
                profile, get_user_now(profile.timezone),
            )
            if self.trial_service.is_blocked(profile):
                _trial_ended = True
                _is_first_post_trial = not getattr(profile, "trial_end_acknowledged", False)

        now = get_user_now(profile.timezone)
        calendar_today = now.strftime("%d/%m/%Y")
        day_name = hebrew_day_name(now)
        stats_date = self.eating_day_svc.resolve_eating_day(profile, now)
        time_str = self._get_time_str(profile)
        within_window = self._is_within_window(profile)

        last_entry = context.chat_data.get("last_entry")

        from constants import MAX_RECENT_MESSAGES
        from datetime import timezone as tz

        reply_context = None
        reply_message_id = None
        if message.reply_to_message and message.reply_to_message.text:
            reply_context = message.reply_to_message.text[:300]
            reply_message_id = message.reply_to_message.message_id

        # If replying to a specific message and no last_entry in memory,
        # try to find the entry by the replied-to message's Telegram ID.
        if reply_message_id and not last_entry:
            found = self._find_entry_by_message_id(tid, reply_message_id)
            if found:
                last_entry = found
                context.chat_data["last_entry"] = found

        # Track last user message and handle re-engagement return
        self.user_repo.update_fields(tid, {
            "last_user_message_at": datetime.now(tz.utc).isoformat(),
        })
        if self.re_engagement_service and profile.re_engagement_stage != "none":
            welcome_back_msg = self.re_engagement_service.handle_return(profile, tid)
            if welcome_back_msg:
                await self._send(welcome_back_msg, tid=tid, context=context)

        # Fetch history BEFORE pushing current user message (so it doesn't
        # include the current message - classifier and guardrails need the
        # prior context only). The current message is pushed after
        # classification, with the classification type as metadata.
        recent_messages = self.user_repo.get_recent_messages(tid, MAX_RECENT_MESSAGES)

        # Build toggle state summary
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
                toggle_lines.append(f"- {label}: active_goal_pending")
            elif toggle.status == "active":
                goal = f", goal: {toggle.goal_value}" if toggle.goal_value else ""
                toggle_lines.append(f"- {label}: active{goal}")
            elif toggle.goal_status == "remind_pending":
                toggle_lines.append(f"- {label}: remind_pending")
            elif toggle.revealed_at and toggle.status == "dormant":
                toggle_lines.append(f"- {label}: offered")
            elif toggle.status == "dormant":
                toggle_lines.append(f"- {label}: dormant")
            elif toggle.status == "cancelled":
                toggle_lines.append(f"- {label}: cancelled")
        toggle_state = "\n".join(toggle_lines) if toggle_lines else None

        # Pending feature request from menu button
        if await self._handle_pending_feature_request(message, context, tid):
            return

        # Pending correction from edit flow (must check before Router)
        if await self._handle_pending_correction(message, context, tid, profile):
            return

        # Pending habit correction (sleep/workout/self_care edit flow)
        if await self._handle_pending_habit_correction(message, context, tid, profile):
            return

        # Classify via Tiered Router
        self._debug_classification = None
        self._debug_router_type = None

        router_result = self.analyzer.route_tiered(
            message.text, calendar_today, last_entry,
            recent_messages=recent_messages,
            toggle_state=toggle_state,
            reply_context=reply_context,
            day_name=day_name,
        )
        self._debug_router_type = router_result.type
        self._debug_classification = router_result.type
        self._current_classification = router_result.type

        # Now push the user message with classification metadata
        user_msg = {
            "role": "user",
            "text": message.text[:500],
            "timestamp": datetime.now(tz.utc).isoformat(),
            "classification": router_result.type,
        }
        if reply_context:
            user_msg["replying_to"] = reply_context
        self.user_repo.push_messages(tid, [user_msg], MAX_RECENT_MESSAGES)

        await self._dispatch_v2(
            message, context, tid, profile, router_result,
            calendar_today, day_name, stats_date, time_str, within_window,
            last_entry, recent_messages, toggle_state, reply_context,
            trial_ended=_trial_ended, is_first_post_trial=_is_first_post_trial,
        )

    # ------------------------------------------------------------------
    # Router v2 dispatch
    # ------------------------------------------------------------------

    async def _dispatch_v2(
        self, message, context, tid, profile, router_result,
        calendar_today, day_name, stats_date, time_str, within_window,
        last_entry, recent_messages, toggle_state, reply_context,
        trial_ended: bool = False, is_first_post_trial: bool = False,
    ):
        rtype = router_result.type

        # Trial ended: force all routes to conversational
        if trial_ended and rtype != "conversational":
            rtype = "conversational"

        # Apply context-aware guardrails
        if not trial_ended:
            from classification_guardrails import validate_classification
            validated = validate_classification(
                router_result,
                recent_messages=recent_messages,
                last_entry=last_entry,
                reply_context=reply_context,
                name=profile.name if profile else None,
                gender=profile.gender if profile else None,
            )
            if validated.type != rtype:
                self._current_classification = validated.type
                rtype = validated.type

        if rtype == "opt_in":
            # Check for log-confirmation misclassification: when toggle is
            # dormant and the bot suggested logging a specific activity, the
            # router says opt_in but it should be workout/sleep/self_care.
            # Use a second LLM call (LoggerService) to disambiguate.
            rtype = await self._check_log_confirmation_override(
                rtype, router_result, message, tid, profile, recent_messages,
            )

        if rtype == "opt_in":
            await self._handle_opt_in(message, context, tid, profile, router_result)
            return

        if rtype == "conversational":
            await self._handle_conversational(
                message, tid, profile, toggle_state, recent_messages,
                calendar_today, day_name,
                trial_ended=trial_ended, is_first_post_trial=is_first_post_trial,
            )
            return

        if rtype == "inappropriate":
            await self._send("אני פה בשביל הרגלי בריאות. בוא נדבר על זה.", tid=tid, message=message)
            return

        if rtype == "correction" and last_entry:
            import base64 as b64_mod
            entry_id = last_entry["entry_id"]
            correction_history = context.chat_data.get("correction_histories", {}).get(entry_id, [])

            photo_b64 = None
            photo_file_id = last_entry.get("photo_file_id")
            if photo_file_id:
                try:
                    file = await context.bot.get_file(photo_file_id)
                    photo_bytes = await file.download_as_bytearray()
                    photo_b64 = b64_mod.b64encode(photo_bytes).decode("utf-8")
                except Exception:
                    logger.warning("Failed to re-download photo %s for correction", photo_file_id)

            correction = self.analyzer.analyze_correction(
                original_description=last_entry["description"],
                original_calories=last_entry["calories"],
                original_protein=last_entry["protein"],
                correction_history=correction_history,
                new_correction=message.text,
                today_str=calendar_today,
                photo_base64=photo_b64,
            )
            if correction:
                await self._handle_correction(
                    message, context, correction, last_entry,
                    profile, calendar_today, tid,
                )
                context.chat_data.setdefault("correction_histories", {})[entry_id] = correction_history + [message.text]
                return

        if rtype == "correction" and not last_entry:
            # Defense-in-depth: guardrail should have caught this, but if a
            # reply-based correction passed the guardrail yet last_entry is
            # missing (e.g. bot restarted), fall back to conversational.
            logger.warning("Correction without last_entry for tid=%s, falling back to conversational", tid)
            await self._handle_conversational(
                message, tid, profile, toggle_state, recent_messages,
                calendar_today, day_name,
            )
            return

        if rtype == "sleep" and self.message_router:
            effective_date = _validate_resolved_date(router_result.resolved_date) or stats_date
            date_label = None
            if effective_date != stats_date:
                date_label = hebrew_day_name(datetime.strptime(effective_date, "%d/%m/%Y"))
            result = self.message_router.route_sleep(tid, time_str, effective_date, date_label=date_label)
            text = result.response_text
            edu = self._get_education_intro(tid, "sleep", profile)
            text = f"{text}\n\n{edu}" if edu else text
            kb = make_sleep_entry_keyboard(result.entry_id) if result.entry_id else None
            bot_msg_id = await self._send(text, tid=tid, message=message, reply_markup=kb)
            self._store_message_ids(self.sleep_repo, result.entry_id, message.message_id, bot_msg_id)
            return

        if rtype == "workout" and self.message_router:
            effective_date = _validate_resolved_date(router_result.resolved_date) or stats_date
            date_label = None
            if effective_date != stats_date:
                date_label = hebrew_day_name(datetime.strptime(effective_date, "%d/%m/%Y"))
            result = self.message_router.route_workout(tid, effective_date, router_result.workout_note, date_label=date_label)
            text = result.response_text
            edu = self._get_education_intro(tid, "workouts", profile)
            text = f"{text}\n\n{edu}" if edu else text
            kb = make_workout_entry_keyboard(result.entry_id) if result.entry_id else None
            bot_msg_id = await self._send(text, tid=tid, message=message, reply_markup=kb)
            self._store_message_ids(self.workout_repo, result.entry_id, message.message_id, bot_msg_id)
            return

        if rtype == "self_care" and self.message_router:
            effective_date = _validate_resolved_date(router_result.resolved_date) or stats_date
            date_label = None
            if effective_date != stats_date:
                date_label = hebrew_day_name(datetime.strptime(effective_date, "%d/%m/%Y"))
            result = self.message_router.route_self_care(tid, message.text, effective_date, date_label=date_label)
            text = result.response_text
            edu = self._get_education_intro(tid, "self_care", profile)
            text = f"{text}\n\n{edu}" if edu else text
            kb = make_self_care_entry_keyboard(result.entry_id) if result.entry_id else None
            bot_msg_id = await self._send(text, tid=tid, message=message, reply_markup=kb)
            self._store_message_ids(self.self_care_repo, result.entry_id, message.message_id, bot_msg_id)
            return

        if rtype == "name_declaration" and self.onboarding_service:
            name = message.text.strip()
            for prefix in ["קוראים לי", "השם שלי", "אני"]:
                if name.startswith(prefix):
                    name = name[len(prefix):].strip()
                    break
            recent = self.user_repo.get_recent_messages(tid, 5)
            last_bot = next((m for m in reversed(recent) if m.get("role") == "bot"), None)
            late = not (last_bot and "איך אתה רוצה שאקרא לך?" in last_bot.get("text", ""))
            response = self.onboarding_service.handle_name_response(tid, name, late=late)
            if response:
                await self._send(response, tid=tid, message=message)
            return

        if rtype == "gender_declaration" and self.onboarding_service:
            gender = router_result.declared_gender if router_result.declared_gender else None
            if gender:
                response = self.onboarding_service.handle_gender_response(tid, gender)
                if response:
                    await self._send(response, tid=tid, message=message)
            return

        if rtype == "feedback_request":
            if self.feedback_service:
                is_first = self.feedback_service.is_first_feedback(tid)
                feedback_text = self.feedback_service.give_feedback(
                    tid, stats_date, profile, is_first,
                )
                await self._send(feedback_text, tid=tid, message=message, reply_markup=make_main_menu_keyboard(self.landing_page_url))
            return

        if rtype == "feedback_reaction":
            if self.feedback_service:
                steering = profile.feedback_steering_prompt if profile else None
                response = self.feedback_service.process_reaction(tid, message.text, steering)
                if response:
                    await self._send(response, tid=tid, message=message)
            return

        if rtype == "feature_request" and self.message_router:
            from services.logger_service import LoggerService
            logger_svc = LoggerService(self.analyzer)
            classification = logger_svc.classify_feature_request(message.text)
            self.message_router.route_feature_request(
                telegram_user_id=tid,
                message_text=message.text,
                request_type=classification.request_type,
                bot_response=classification.ack_text,
                message_id=message.message_id,
                chat_id=message.chat_id,
                chat_history=recent_messages,
            )
            await self._send(classification.ack_text, tid=tid, message=message)
            return

        if rtype == "emotional" and self.emotional_support_service:
            from services.logger_service import LoggerService
            logger_svc = LoggerService(self.analyzer)
            empathy_result = logger_svc.generate_empathy(message.text)
            reflection = empathy_result.empathy_reflection
            boundary = self.emotional_support_service.get_empathy_response()
            empathy = f"{reflection}\n\n{boundary}" if reflection else boundary

            emo_mode = self.emotional_support_service.mode
            if emo_mode == "creator":
                keyboard = make_emotional_creator_keyboard(
                    self.emotional_support_service.creator_username,
                )
            else:
                context.chat_data["emotional_message"] = message.text
                keyboard = make_emotional_support_keyboard()

            await self._send(
                empathy, tid=tid, message=message,
                reply_markup=keyboard,
            )
            return

        # Default: meal (with inline extraction from Router)
        from analyzer import TimedFoodAnalysisResult

        if rtype == "meal" and router_result.meal and router_result.meal.groups:
            food_result = router_result.meal
        else:
            food_result = self.analyzer.analyze_food_text(message.text, calendar_today, day_name)

        if food_result is None or not food_result.groups:
            await self._send("לא הצלחתי לזהות מאכל בהודעה. נסה שוב?", tid=tid, message=message, save=False)
            return

        saved_entries = []
        for group in food_result.groups:
            combined_desc = ", ".join(item.description for item in group.items)
            entry = FoodEntry(
                telegram_user_id=tid,
                date=group.date,
                time=group.time,
                description=combined_desc,
                calories=group.total_calories,
                protein=group.total_protein,
                within_window=within_window if group.date == calendar_today else True,
            )
            saved = self.food_repo.add(entry)
            saved_entries.append((group, saved))

        last_group, last_saved = saved_entries[-1]
        last_desc = ", ".join(item.description for item in last_group.items)
        context.chat_data["last_entry"] = {
            "description": last_desc,
            "calories": last_group.total_calories,
            "protein": last_group.total_protein,
            "entry_id": last_saved.id,
        }

        items_text = self._format_grouped_items_text(food_result.groups, calendar_today)

        today_groups = [g for g in food_result.groups if g.date == calendar_today]
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
            retro_labels = [g.temporal_label for g in food_result.groups]
            response = f"{items_text}\n\n✅ נרשם ({', '.join(retro_labels)})"

        last_entry_id = last_saved.id
        bot_msg_id = await self._send(response, tid=tid, message=message, reply_markup=make_food_entry_keyboard(last_entry_id))
        self._store_message_ids(self.food_repo, last_entry_id, message.message_id, bot_msg_id)
        await safe_react(message, OK_HAND)

        # Protein education on first meal ever
        if len(self.food_repo.get_all_for_user(tid)) == 1:
            from dugri_messages import EDU_INTRO_FIRST_LOG
            edu = EDU_INTRO_FIRST_LOG.get("protein")
            if edu:
                await self._send(edu, tid=tid, message=message, save=False)

        await self._recompute_eating_window(context, tid, profile)
        await self._check_inline_hooks(message, tid, profile)

    async def _check_log_confirmation_override(
        self, rtype, router_result, message, tid, profile, recent_messages,
    ):
        """Check if opt_in is actually a log confirmation (second LLM call).

        Runs for every opt_in classification. Uses a lightweight GPT call
        to determine from conversation context alone whether the user is
        confirming a habit log or responding to a goal-setting flow.
        """
        if rtype != "opt_in":
            return rtype

        # Get the bot's last message from recent history
        bot_messages = [m for m in (recent_messages or []) if m.get("role") == "bot"]
        if not bot_messages:
            return rtype
        last_bot_text = bot_messages[-1].get("text", "")

        from services.logger_service import LoggerService
        logger_svc = LoggerService(self.analyzer)
        check = logger_svc.check_log_confirmation(last_bot_text, message.text)

        if check.is_log_confirmation and check.habit_type:
            logger.info("Log-confirmation override: opt_in -> %s", check.habit_type)
            return check.habit_type
        return rtype

    async def _handle_conversational(
        self, message, tid, profile, toggle_state, recent_messages,
        calendar_today="", day_name="",
        trial_ended: bool = False, is_first_post_trial: bool = False,
    ):
        if not self.conversational_service:
            await self._send("מה נשמע?", tid=tid, message=message)
            return

        user_context_parts = []
        if profile.name:
            user_context_parts.append(f"שם: {profile.name}")
        if profile.height_cm:
            user_context_parts.append(f"גובה: {profile.height_cm} ס\"מ")
        if profile.weight_kg:
            user_context_parts.append(f"משקל: {profile.weight_kg} ק\"ג")
        if profile.birth_year:
            from datetime import datetime as dt
            age = dt.now().year - profile.birth_year
            user_context_parts.append(f"גיל: {age}")
        tc = self._target_cal(profile)
        tp = self._target_prot(profile)
        if tc:
            user_context_parts.append(f"יעד קלוריות: {tc}")
        if tp:
            user_context_parts.append(f"יעד חלבון: {tp}")
        user_context = "\n".join(user_context_parts) if user_context_parts else "לא זמין"

        today_date = calendar_today
        if day_name:
            today_date += f" (יום {day_name})"

        def fetch_history(days: int) -> str:
            from datetime import datetime, timedelta
            today = datetime.strptime(calendar_today, "%d/%m/%Y").date()
            dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(days + 1)]
            entries = self.food_repo.get_by_user_and_dates(tid, dates)
            if not entries:
                return "אין נתונים לתקופה המבוקשת."
            heb_days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
            day_labels = {}
            for offset in range(days + 1):
                d = today - timedelta(days=offset)
                ds = d.strftime("%d/%m/%Y")
                if offset == 0:
                    day_labels[ds] = "היום"
                elif offset == 1:
                    day_labels[ds] = "אתמול"
                else:
                    day_labels[ds] = f"יום {heb_days[d.weekday()]}"
            lines = ["תאריך,יום,שעה,תיאור,קלוריות,חלבון"]
            for e in entries:
                label = day_labels.get(e.date, e.date)
                lines.append(f"{e.date},{label},{e.time},{e.description},{e.calories},{e.protein}")
            return "\n".join(lines)

        trial_over_context = ""
        if trial_ended and self.conversational_service:
            trial_over_context = self.conversational_service.get_trial_over_context()

        response = self.conversational_service.respond(
            user_text=message.text,
            user_context=user_context,
            toggle_state=toggle_state or "",
            today_date=today_date or "לא זמין",
            recent_messages=recent_messages[:-1] if recent_messages else None,
            fetch_history=fetch_history,
            trial_over_context=trial_over_context,
            is_first_post_trial=is_first_post_trial,
        )

        if is_first_post_trial:
            self.user_repo.update_fields(tid, {"trial_end_acknowledged": True})

        await self._send(response, tid=tid, message=message)

