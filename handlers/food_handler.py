"""
food_handler.py - Food logging, photo handling, and correction flow.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from models.food import FoodEntry
from models.profile import UserProfile
from parsing import get_user_now
from keyboards import (
    OK_HAND, THUMBS_UP,
    make_food_entry_keyboard, make_daily_summary_keyboard, format_daily_status,
    make_main_menu_keyboard,
)
from handlers.utils import PENDING_STATE_TTL, safe_react
from handlers.context import HandlerContext

logger = logging.getLogger(__name__)


class FoodHandler:
    def __init__(self, ctx: HandlerContext):
        self.ctx = ctx

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.photo:
            return

        tid = update.effective_user.id
        self.ctx._setup_token_tracking(tid)

        profile = self.ctx._get_profile(tid)
        if profile is None:
            await message.reply_text(f"צריך להירשם קודם: {self.ctx.landing_page_url}")
            return

        # Trial gating for photos
        if self.ctx.trial_service:
            self.ctx.trial_service.check_and_expire(
                profile, get_user_now(profile.timezone),
            )
            if self.ctx.trial_service.is_blocked(profile):
                if self.ctx.conversational_service:
                    is_first = not getattr(profile, "trial_end_acknowledged", False)
                    trial_ctx = self.ctx.conversational_service.get_trial_over_context()
                    response = self.ctx.conversational_service.respond(
                        user_text="[המשתמש שלח תמונה לתיעוד אוכל]",
                        user_context="",
                        toggle_state="",
                        today_date="",
                        trial_over_context=trial_ctx,
                        is_first_post_trial=is_first,
                    )
                    if is_first:
                        self.ctx.user_repo.update_fields(tid, {"trial_end_acknowledged": True})
                    await self.ctx._send(response, tid=tid, message=message)
                return

        now = get_user_now(profile.timezone)
        calendar_today = now.strftime("%d/%m/%Y")
        time_str = self.ctx._get_time_str(profile)
        within_window = self.ctx._is_within_window(profile)

        photo = message.photo[-1]
        file = await photo.get_file()
        photo_bytes = await file.download_as_bytearray()
        b64 = base64.b64encode(photo_bytes).decode("utf-8")

        caption = message.caption or ""

        result = self.ctx.analyzer.analyze_food_photo(b64, calendar_today, caption=caption)
        if result is None or not result.items:
            await self.ctx._send("לא הצלחתי לזהות מאכל בתמונה. נסה לתאר מה אכלת בטקסט.", tid=tid, message=message, save=False)
            return

        combined_desc = ", ".join(item.description for item in result.items)
        total_cal = result.total_calories
        total_prot = result.total_protein

        entry = FoodEntry(
            telegram_user_id=tid,
            date=calendar_today,
            time=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            within_window=within_window,
            photo_file_id=photo.file_id,
        )
        saved = self.ctx.food_repo.add(entry)

        context.chat_data["last_entry"] = {
            "description": combined_desc,
            "calories": total_cal,
            "protein": total_prot,
            "entry_id": saved.id,
            "photo_file_id": photo.file_id,
        }

        stats_date = self.ctx.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        new_daily_cal, new_daily_prot = self.ctx.eating_day_svc.get_eating_day_totals(profile, stats_date)
        prev_cal = new_daily_cal - total_cal
        prev_protein = new_daily_prot - total_prot

        items_text = self.ctx._format_items_text(result.items, total_cal, total_prot)

        alerts = self.ctx._check_crossing_alerts(prev_cal, prev_protein, new_daily_cal, new_daily_prot, profile)
        response = self.ctx._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)
        if alerts:
            response = f"{alerts}\n\n{response}"

        if result.photo_tips:
            response += f"\n\n💡 {result.photo_tips[0]}"

        if result.unidentified_items:
            response += "\n\n❓ " + ", ".join(result.unidentified_items) + "\nמה זה? שלח תיאור או תקן דרך הכפתור ✏️"

        await self.ctx._send(response, tid=tid, message=message, reply_markup=make_food_entry_keyboard(saved.id))
        await safe_react(message, OK_HAND)

    async def handle_correction(
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

        orig_desc = last_entry.get("original_description") or old_desc
        orig_cal = last_entry.get("original_calories") or old_cal
        orig_prot = last_entry.get("original_protein") or old_prot

        updated_history = context.chat_data.get("correction_histories", {}).get(entry_id, [])
        updated_history = updated_history + [message.text]

        self.ctx.food_repo.update(entry_id, {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
            "original_description": orig_desc,
            "original_calories": orig_cal,
            "original_protein": orig_prot,
            "correction_history": updated_history,
            "edit_expires_at": datetime.now(tz.utc) + timedelta(hours=48),
        })

        # Move entry to a different date/time if correction includes a date change
        if correction.corrected_date:
            new_within = True  # past dates are always "within window"
            if correction.corrected_date == today_str:
                new_within = self.ctx._is_within_window(profile)
            self.ctx.food_repo.move(
                entry_id, correction.corrected_date,
                new_time=correction.corrected_time,
                within_window=new_within,
            )

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

        stats_date = self.ctx.eating_day_svc.get_stats_date(profile, get_user_now(profile.timezone))
        final_cal, final_prot = self.ctx.eating_day_svc.get_eating_day_totals(profile, stats_date)

        response = self.format_correction_response(
            correction, orig_desc, orig_cal, orig_prot, new_cal, new_prot,
        )
        status = format_daily_status(
            final_cal, final_prot, self.ctx._target_cal(profile), self.ctx._target_prot(profile),
        )
        response += status

        await self.ctx._send(response, tid=tid, message=message, reply_markup=make_food_entry_keyboard(entry_id), save=False)
        await safe_react(message, OK_HAND)

    @staticmethod
    def format_correction_response(
        correction, orig_desc: str, orig_cal: int, orig_prot: int,
        new_cal: int, new_prot: int,
    ) -> str:
        parts = []

        parts.append(f"📋 רשומה מקורית: {orig_desc}")
        parts.append(f"סה\"כ: {orig_cal} קל׳ | {orig_prot} גרם חלבון")

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

    async def recompute_eating_window(self, context, tid: int, profile: UserProfile):
        if not profile.toggles or profile.toggles.eating_window.status != "active":
            return

        new_window = self.ctx.eating_day_svc.compute_eating_window(tid)
        if not new_window:
            return

        old = profile.eating_window
        if old and old.start == new_window.start and old.end == new_window.end:
            return

        self.ctx.user_repo.update_fields(tid, {
            "eating_window.start": new_window.start,
            "eating_window.end": new_window.end,
        })
