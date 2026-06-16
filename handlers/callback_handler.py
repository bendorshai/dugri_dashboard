"""
callback_handler.py - All inline keyboard callback handlers.

Handles button presses from menus, profiles, food entries, feedback, etc.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from models.food import FoodEntry
from parsing import get_user_now
from keyboards import (
    make_daily_summary_keyboard, make_main_menu_keyboard,
    make_profile_keyboard, make_settings_keyboard,
    make_food_entry_keyboard, format_daily_status,
    make_emotional_support_keyboard, make_emotional_creator_keyboard,
    CB_MENU, CB_PROFILE, CB_EDIT_FIELD, CB_SUGGEST,
    CB_ASK, CB_FOOD_EDIT, CB_FOOD_DELETE, CB_FOOD_AGAIN, CB_WEEKLY, CB_DAILY, CB_BACK,
    CB_FEEDBACK, CB_EMOTIONAL, CB_FEATURE,
    CB_SLEEP_EDIT, CB_SLEEP_DELETE,
    CB_WORKOUT_EDIT, CB_WORKOUT_DELETE,
    CB_SELFCARE_EDIT, CB_SELFCARE_DELETE,
)
from handlers.utils import safe_answer

from handlers.context import HandlerContext, FIELD_LABELS

logger = logging.getLogger(__name__)


def _sleep_within_goal(actual: str, target: str) -> bool:
    """Check if actual sleep time is within 30 minutes of target."""
    def _to_minutes(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    actual_min = _to_minutes(actual)
    target_min = _to_minutes(target)
    diff = abs(actual_min - target_min)
    # Handle wrap-around midnight (e.g., 23:50 vs 00:10)
    diff = min(diff, 1440 - diff)
    return diff <= 30


class CallbackHandler:
    def __init__(self, ctx: HandlerContext):
        self.ctx = ctx

    async def handle_debug_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)
        debug_key = query.data.removeprefix("dbg_")
        metadata = self.ctx._debug_store.get(debug_key)
        if metadata is None:
            await query.message.reply_text("Debug info expired.")
            return
        await query.message.reply_text(metadata)

    async def handle_gem_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        data = query.data.removeprefix("gem_")

        if not self.ctx.gem_service:
            return

        if data.startswith("like_"):
            gem_id = data.removeprefix("like_")
            self.ctx.gem_service.handle_feedback(tid, gem_id, "like")
            import messages as M
            await query.message.reply_text(M.GEM_LIKE_ACK)
        elif data.startswith("dislike_"):
            gem_id = data.removeprefix("dislike_")
            self.ctx.gem_service.handle_feedback(tid, gem_id, "dislike")
            import messages as M
            await query.message.reply_text(M.GEM_DISLIKE_ACK)

    async def handle_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        data = query.data.removeprefix(CB_MENU)

        if data == "profile":
            profile = self.ctx._get_profile(tid)
            if profile is None:
                return
            text = (
                "👤 הפרופיל שלך:\n\n"
                f"גיל: {getattr(profile, 'age', '-') or '-'}\n"
                f"גובה: {getattr(profile, 'height_cm', '-') or '-'} ס\"מ\n"
                f"משקל: {getattr(profile, 'weight_kg', '-') or '-'} ק\"ג\n\n"
                f"🎯 יעדים:\n"
                f"קלוריות: {self.ctx._target_cal(profile)}\n"
                f"גרם חלבון: {self.ctx._target_prot(profile)}\n\n"
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
            profile = self.ctx._get_profile(tid)
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

            suggestion = self.ctx.analyzer.suggest_targets(height, weight, age)
            if suggestion:
                cal = suggestion.get("target_calories", 2000)
                prot = suggestion.get("target_protein", 150)
                self.ctx.user_repo.update_fields(tid, {
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
        self.ctx._setup_token_tracking(tid)

        profile = self.ctx._get_profile(tid)
        if profile is None:
            return

        stats_date = self.ctx.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        total_cal, total_protein = self.ctx.eating_day_svc.get_eating_day_totals(profile, stats_date)
        entries = self.ctx.eating_day_svc.get_eating_day_entries(profile, stats_date)

        target_cal = self.ctx._target_cal(profile)
        target_prot = self.ctx._target_prot(profile)
        remaining_cal = max(0, target_cal - total_cal)
        remaining_prot = max(0, target_prot - total_protein)

        today_text = "\n".join(
            f"- {e.description}: {e.calories} קל׳, {e.protein} גרם חלבון"
            for e in entries
        ) or "עדיין לא אכלת היום"

        await query.edit_message_text("🤔 מחפש הצעות...")

        suggestions = self.ctx.analyzer.suggest_meals(remaining_cal, remaining_prot, today_text)
        if suggestions:
            await query.edit_message_text(
                f"🍽 הצעות ארוחה:\n\n{suggestions}",
                reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url),
            )
        else:
            await query.edit_message_text(
                "לא הצלחתי להציע ארוחות. נסה שוב.",
                reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url),
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

    async def handle_feature_request_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        import messages as M
        data = query.data.removeprefix(CB_FEATURE)
        request_type = "bug_report" if data == "bug" else "feature_request"

        context.chat_data["pending_feature_request"] = {
            "timestamp": time.time(),
            "request_type": request_type,
        }

        prompt = M.FEATURE_REQUEST_PROMPT_BUG if data == "bug" else M.FEATURE_REQUEST_PROMPT_SUGGESTION
        await query.edit_message_text(prompt)

    async def handle_food_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        entry_id = query.data.removeprefix(CB_FOOD_DELETE)
        try:
            self.ctx.food_repo.delete(entry_id)
            import random
            import messages as M
            await query.edit_message_text(random.choice(M.FOOD_DELETED), reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url))
        except Exception:
            logger.exception("Failed to delete food entry %s", entry_id)
            # Menu must be preserved - send error with keyboard so user can retry
            await query.edit_message_text(
                "❌ לא הצלחתי למחוק את הרשומה.",
                reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url),
            )

    async def handle_food_edit_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        entry_id = query.data.removeprefix(CB_FOOD_EDIT)
        try:
            food_entry = self.ctx.food_repo.get(entry_id)
            if food_entry is None:
                await query.edit_message_text("❌ הרשומה לא נמצאה.", reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url))
                return

            existing_history = food_entry.correction_history or \
                context.chat_data.get("correction_histories", {}).get(entry_id, [])
            # Store message coordinates so the keyboard can be restored
            # after correction completes. Menu must be preserved on every
            # food entry message - it's the user's only way to interact.
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
                    "date": food_entry.date,
                    "time": food_entry.time,
                },
                "correction_history": existing_history,
                "timestamp": time.time(),
                "edit_message_id": query.message.message_id,
                "edit_chat_id": query.message.chat_id,
            }

            await query.edit_message_text(
                f"✏️ עריכת רשומה: {food_entry.description}\n"
                f"קלוריות: {food_entry.calories} | גרם חלבון: {food_entry.protein}\n\n"
                "שלח תיאור של התיקון (למשל: 'זה היה 300 גרם לא 150'):"
            )
        except Exception:
            logger.exception("Failed to read entry for edit, id %s", entry_id)
            # Menu must be preserved - send error with keyboard so user can retry
            await query.edit_message_text(
                "❌ לא הצלחתי לטעון את הרשומה.",
                reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url),
            )

    async def handle_food_again_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        entry_id = query.data.removeprefix(CB_FOOD_AGAIN)
        try:
            food_entry = self.ctx.food_repo.get(entry_id)
            if food_entry is None:
                await self.ctx._send("❌ הרשומה לא נמצאה.", tid=tid, context=context, reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url), save=False)
                return

            profile = self.ctx._get_profile(tid)
            if profile is None:
                return
            calendar_today = get_user_now(profile.timezone).strftime("%d/%m/%Y")
            time_str = self.ctx._get_time_str(profile)
            within_window = self.ctx._is_within_window(profile)

            new_entry = FoodEntry(
                telegram_user_id=tid,
                date=calendar_today,
                time=time_str,
                description=food_entry.description,
                calories=food_entry.calories,
                protein=food_entry.protein,
                within_window=within_window,
            )
            saved = self.ctx.food_repo.add(new_entry)

            stats_date = self.ctx.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
            new_daily_cal, new_daily_prot = self.ctx.eating_day_svc.get_eating_day_totals(profile, stats_date)

            items_text = f"🔁 {food_entry.description}: {food_entry.calories} קל׳ | {food_entry.protein} גרם חלבון"
            response = self.ctx._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)

            await self.ctx._send(response, tid=tid, context=context, reply_markup=make_food_entry_keyboard(saved.id))
        except Exception:
            logger.exception("Failed to duplicate food entry %s", entry_id)
            # Menu must be preserved - send error with keyboard so user can retry
            await self.ctx._send(
                "❌ לא הצלחתי לשכפל את הרשומה.",
                tid=tid, context=context,
                reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url),
                save=False,
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
        profile = self.ctx._get_profile(tid)
        if profile is None:
            return

        stats_date = self.ctx.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        entries = self.ctx.eating_day_svc.get_eating_day_entries(profile, stats_date)

        if not entries:
            await query.edit_message_text(
                "📋 אין רשומות להיום.",
                reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url),
            )
            return

        total_cal = 0
        total_prot = 0
        lines = ["📋 סיכום יומי מפורט:\n"]
        for i, e in enumerate(entries, 1):
            total_cal += e.calories
            total_prot += e.protein
            lines.append(f"{i}. {e.description} — {e.calories} קל׳ | {e.protein} גרם חלבון ({e.time})")

        status = format_daily_status(total_cal, total_prot, self.ctx._target_cal(profile), self.ctx._target_prot(profile))
        text = "\n".join(lines) + status

        await self.ctx._send(text, tid=tid, message=query.message, reply_markup=make_daily_summary_keyboard(self.ctx.landing_page_url), save=False)

    async def handle_weekly_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        profile = self.ctx._get_profile(tid)
        if profile is None:
            return

        target_cal = self.ctx._target_cal(profile)
        target_prot = self.ctx._target_prot(profile)
        window_start = profile.eating_window.start if profile.eating_window else "08:00"
        window_end = profile.eating_window.end if profile.eating_window else "20:00"
        show_window = getattr(profile.toggles, "eating_window", None) and \
            profile.toggles.eating_window.status == "active"
        sleep_target = getattr(profile.targets, "sleep_time", None)

        now = get_user_now(profile.timezone)
        today = now.date()

        dates = [(today - timedelta(days=i)) for i in range(7)]
        date_strings = [d.strftime("%d/%m/%Y") for d in dates]

        # Fetch habit data in bulk
        workout_by_date: dict[str, list] = {}
        if getattr(self.ctx, "workout_repo", None):
            for w in self.ctx.workout_repo.get_recent(tid, 7):
                workout_by_date.setdefault(w.date, []).append(w)

        sleep_by_date: dict[str, object] = {}
        if getattr(self.ctx, "sleep_repo", None):
            for s in self.ctx.sleep_repo.get_recent(tid, 7):
                if s.date not in sleep_by_date:
                    sleep_by_date[s.date] = s

        lines = ["📅 סיכום שבועי:\n"]
        for d, ds in zip(dates, date_strings):
            day_label = d.strftime("%a %d/%m")
            entries = self.ctx.eating_day_svc.get_eating_day_entries(profile, ds)

            if not entries and ds not in workout_by_date and ds not in sleep_by_date:
                lines.append(f"📆 {day_label}  —  אין נתונים")
                continue

            day_lines = [f"📆 {day_label}"]

            # Food data
            if entries:
                day_cal = sum(e.calories for e in entries)
                day_prot = sum(e.protein for e in entries)

                cal_pct = round(day_cal / target_cal * 100) if target_cal else 0
                prot_pct = round(day_prot / target_prot * 100) if target_prot else 0
                cal_icon = "✅" if day_cal <= target_cal else "⚠️"
                prot_icon = "✅" if day_prot >= target_prot else "⚠️"

                day_lines.append(f"  {cal_icon} קלוריות: {day_cal}/{target_cal} ({cal_pct}%)")
                day_lines.append(f"  {prot_icon} חלבון: {day_prot}/{target_prot} ({prot_pct}%)")

                # Eating window - only when toggle is active
                if show_window:
                    window_kept = all(
                        (not e.time or (window_start <= e.time < window_end))
                        for e in entries
                    )
                    window_icon = "✅" if window_kept else "🍽"
                    day_lines.append(
                        f"  {window_icon} חלון אכילה: {'נשמר' if window_kept else 'לא נשמר'}"
                    )

            # Workout data
            if ds in workout_by_date:
                for w in workout_by_date[ds]:
                    label = "  🏋️ אימון"
                    if w.note:
                        label += f": {w.note}"
                    day_lines.append(label)

            # Sleep data
            if ds in sleep_by_date:
                sl = sleep_by_date[ds]
                if sleep_target:
                    sleep_icon = "✅" if _sleep_within_goal(sl.sleep_time, sleep_target) else "⚠️"
                    day_lines.append(f"  {sleep_icon} שינה: {sl.sleep_time} (יעד: {sleep_target})")
                else:
                    day_lines.append(f"  😴 שינה: {sl.sleep_time}")

            lines.append("\n".join(day_lines))

        text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=make_main_menu_keyboard(
            self.ctx.landing_page_url))

    async def handle_back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        profile = self.ctx._get_profile(tid)
        if profile is None:
            return

        stats_date = self.ctx.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        total_cal, total_protein = self.ctx.eating_day_svc.get_eating_day_totals(profile, stats_date)

        status = format_daily_status(
            total_cal, total_protein, self.ctx._target_cal(profile), self.ctx._target_prot(profile),
        )
        await self.ctx._send(f"📋 תפריט ראשי{status}", tid=tid, context=context, reply_markup=make_main_menu_keyboard(self.ctx.landing_page_url), save=False)

    async def handle_feedback_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        self.ctx._setup_token_tracking(tid)

        await self.ctx._send("🤔 מכין משוב...", tid=tid, context=context, save=False)

        try:
            profile = self.ctx._get_profile(tid)
            if profile is None:
                return

            now = get_user_now(profile.timezone)
            stats_date = self.ctx.eating_day_svc.resolve_eating_day(profile, now)

            if self.ctx.feedback_service:
                is_first = self.ctx.feedback_service.is_first_feedback(tid)
                feedback_text = self.ctx.feedback_service.give_feedback(
                    tid, stats_date,
                    self.ctx._target_cal(profile),
                    self.ctx._target_prot(profile),
                    profile.feedback_steering_prompt,
                    is_first,
                )
                await self.ctx._send(feedback_text, tid=tid, context=context, reply_markup=make_main_menu_keyboard(self.ctx.landing_page_url))
            else:
                await self.ctx._send("לא הצלחתי לייצר משוב כרגע.", tid=tid, context=context, reply_markup=make_main_menu_keyboard(self.ctx.landing_page_url), save=False)
        except Exception:
            logger.exception("Failed to generate feedback")

    async def handle_emotional_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        tid = update.effective_user.id
        if not self.ctx.emotional_support_service:
            return

        user_message = context.chat_data.get("emotional_message", "")
        prompt = self.ctx.emotional_support_service.build_chatgpt_prompt(tid, user_message)
        await self.ctx._send(f"```\n{prompt}\n```", tid=tid, context=context)
        import messages as M
        await self.ctx._send(
            M.EMOTIONAL_CHATGPT_GUIDANCE,
            tid=tid, context=context,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("פתח ChatGPT", url="https://chatgpt.com")]
            ]),
        )

    # ------------------------------------------------------------------
    # Habit edit/delete callbacks (sleep, workout, self_care)
    # ------------------------------------------------------------------

    async def _handle_habit_edit(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
        prefix: str, habit_type: str, repo, display_fn,
    ):
        """Generic edit handler for any habit type."""
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        from bson import ObjectId
        entry_id = query.data.removeprefix(prefix)
        try:
            entry = repo.get_by_id(ObjectId(entry_id))
            if entry is None:
                await query.edit_message_text("❌ הרשומה לא נמצאה.")
                return

            context.chat_data["pending_habit_correction"] = {
                "habit_type": habit_type,
                "entry": display_fn(entry, entry_id),
                "timestamp": time.time(),
            }
            desc = display_fn(entry, entry_id).get("display", "")
            await query.edit_message_text(
                f"✏️ עריכת {desc}\n\nשלח תיאור של התיקון (למשל: 'זה היה אתמול'):"
            )
        except Exception:
            logger.exception("Failed to read %s entry for edit, id %s", habit_type, entry_id)

    async def _handle_habit_delete(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
        prefix: str, repo,
    ):
        """Generic delete handler for any habit type."""
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        from bson import ObjectId
        entry_id = query.data.removeprefix(prefix)
        try:
            repo.delete_by_id(ObjectId(entry_id))
            await query.edit_message_text("🗑 נמחק.")
        except Exception:
            logger.exception("Failed to delete habit entry %s", entry_id)
            await query.edit_message_text("❌ לא הצלחתי למחוק.")

    def _sleep_display(self, entry, entry_id):
        return {
            "entry_id": entry_id,
            "date": entry.date,
            "sleep_time": entry.sleep_time,
            "display": f"שינה ב-{entry.sleep_time} ({entry.date})",
        }

    def _workout_display(self, entry, entry_id):
        return {
            "entry_id": entry_id,
            "date": entry.date,
            "note": entry.note,
            "display": f"אימון ({entry.date})",
        }

    def _self_care_display(self, entry, entry_id):
        return {
            "entry_id": entry_id,
            "date": getattr(entry, "date", None),
            "description": entry.description,
            "display": f"משהו לעצמי: {entry.description}",
        }

    async def handle_sleep_edit_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_habit_edit(
            update, context, CB_SLEEP_EDIT, "sleep",
            self.ctx.sleep_repo, self._sleep_display,
        )

    async def handle_sleep_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_habit_delete(update, context, CB_SLEEP_DELETE, self.ctx.sleep_repo)

    async def handle_workout_edit_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_habit_edit(
            update, context, CB_WORKOUT_EDIT, "workout",
            self.ctx.workout_repo, self._workout_display,
        )

    async def handle_workout_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_habit_delete(update, context, CB_WORKOUT_DELETE, self.ctx.workout_repo)

    async def handle_selfcare_edit_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_habit_edit(
            update, context, CB_SELFCARE_EDIT, "self_care",
            self.ctx.self_care_repo, self._self_care_display,
        )

    async def handle_selfcare_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_habit_delete(update, context, CB_SELFCARE_DELETE, self.ctx.self_care_repo)
