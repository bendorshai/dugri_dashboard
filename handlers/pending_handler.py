"""
pending_handler.py - Pending edit/question/correction/bulk-fix/feature-request state handlers.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta

from models.profile import UserProfile
from parsing import get_user_now
from keyboards import (
    THUMBS_UP, OK_HAND,
    make_daily_summary_keyboard, make_main_menu_keyboard,
    make_food_entry_keyboard,
)
from handlers.utils import PENDING_STATE_TTL, safe_react
from handlers.context import HandlerContext, FIELD_LABELS

logger = logging.getLogger(__name__)


class PendingHandler:
    def __init__(self, ctx: HandlerContext):
        self.ctx = ctx

    async def handle_pending_edit(self, message, context, tid: int, profile: UserProfile) -> bool:
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
                self.ctx.user_repo.update_fields(tid, {"targets.calories": value})
            elif field == "target_protein":
                value = int(text)
                self.ctx.user_repo.update_fields(tid, {"targets.protein": value})
            elif field in ("age", "height_cm", "weight_kg"):
                value = int(text)
                self.ctx.user_repo.update_fields(tid, {field: value})
            elif field == "timezone":
                self.ctx.user_repo.update_fields(tid, {"timezone": text})
            else:
                await self.ctx._send("שדה לא מוכר.", tid=tid, message=message, save=False)
                return True

            await safe_react(message, OK_HAND)
            await self.ctx._send(f"✅ {FIELD_LABELS.get(field, field)} עודכן!", tid=tid, message=message, save=False)

        except ValueError:
            await self.ctx._send("ערך לא תקין. נסה שוב.", tid=tid, message=message, save=False)
        except Exception:
            logger.exception("Failed to update profile field %s", field)

        return True

    async def handle_pending_feature_request(self, message, context, tid: int) -> bool:
        pending = context.chat_data.get("pending_feature_request")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_feature_request"]
            return False

        del context.chat_data["pending_feature_request"]
        request_type = pending.get("request_type", "feature_request")

        from services.logger_service import LoggerService
        logger_svc = LoggerService(self.ctx.analyzer)
        classification = logger_svc.classify_feature_request(message.text)
        # Menu button overrides the sub-type
        final_type = request_type
        ack_text = classification.ack_text

        if self.ctx.message_router:
            from constants import MAX_RECENT_MESSAGES
            chat_history = self.ctx.user_repo.get_recent_messages(tid, MAX_RECENT_MESSAGES)
            self.ctx.message_router.route_feature_request(
                telegram_user_id=tid,
                message_text=message.text,
                request_type=final_type,
                bot_response=ack_text,
                message_id=message.message_id,
                chat_id=message.chat_id,
                chat_history=chat_history,
            )
        await self.ctx._send(ack_text, tid=tid, message=message)
        return True

    async def handle_pending_question(self, message, context, tid: int, profile: UserProfile) -> bool:
        pending = context.chat_data.get("pending_question")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_question"]
            return False

        del context.chat_data["pending_question"]
        question = message.text.strip()

        await safe_react(message, THUMBS_UP)

        calendar_today = get_user_now(profile.timezone).strftime("%d/%m/%Y")
        today = datetime.strptime(calendar_today, "%d/%m/%Y").date()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]

        entries = self.ctx.food_repo.get_by_user_and_dates(tid, dates)
        csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון"]
        for e in entries:
            csv_lines.append(f"{e.date},{e.time},{e.description},{e.calories},{e.protein}")
        week_csv = "\n".join(csv_lines)

        targets = {
            "calories": self.ctx._target_cal(profile),
            "protein": self.ctx._target_prot(profile),
        }

        answer = self.ctx.analyzer.answer_question(question, week_csv, targets)
        if answer:
            await self.ctx._send(answer, tid=tid, message=message, reply_markup=make_daily_summary_keyboard(), save=False)
        else:
            await self.ctx._send("לא הצלחתי לענות. נסה שוב.", tid=tid, message=message, save=False)

        return True

    async def handle_pending_correction(self, message, context, tid: int, profile: UserProfile) -> bool:
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
        calendar_today = get_user_now(profile.timezone).strftime("%d/%m/%Y")
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

        correction = self.ctx.analyzer.analyze_correction(
            original_description=entry["description"],
            original_calories=entry["calories"],
            original_protein=entry["protein"],
            correction_history=correction_history,
            new_correction=message.text,
            today_str=calendar_today,
            photo_base64=photo_b64,
        )

        if correction:
            # Delegate to FoodHandler for correction processing
            from handlers.food_handler import FoodHandler
            food_handler = FoodHandler(self.ctx)
            await food_handler.handle_correction(message, context, correction, entry, profile, calendar_today, tid)
            updated_history = correction_history + [message.text]
            context.chat_data.setdefault("correction_histories", {})[entry_id] = updated_history
        else:
            await self.ctx._send("לא הצלחתי להבין את התיקון. נסה שוב.", tid=tid, message=message, save=False)

        # Restore keyboard on the original edit-prompt message.
        # Menu must be preserved on every food entry message - it's the
        # user's only way to edit/delete/duplicate that entry.
        await self._restore_edit_message_keyboard(context, pending, entry_id)

        return True

    @staticmethod
    async def _restore_edit_message_keyboard(context, pending: dict, entry_id: str) -> None:
        """Restore the food entry keyboard on the original edit-prompt message."""
        msg_id = pending.get("edit_message_id")
        chat_id = pending.get("edit_chat_id")
        if not msg_id or not chat_id:
            return
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=make_food_entry_keyboard(entry_id),
            )
        except Exception:
            logger.debug("Could not restore keyboard on message %s", msg_id)

    async def handle_pending_bulk_fix(self, message, context, tid: int, profile: UserProfile) -> bool:
        pending = context.chat_data.get("pending_bulk_fix")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_bulk_fix"]
            return False

        del context.chat_data["pending_bulk_fix"]
        await safe_react(message, THUMBS_UP)

        correction_text = message.text.strip()

        all_entries = self.ctx.food_repo.get_all_for_user(tid)
        if not all_entries:
            await self.ctx._send("אין רשומות לתיקון.", tid=tid, message=message, save=False)
            return True

        csv_lines = ["row_index,תאריך,שעה,תיאור,קלוריות,חלבון"]
        for i, e in enumerate(all_entries):
            csv_lines.append(f"{i},{e.date},{e.time},{e.description},{e.calories},{e.protein}")
        entries_csv = "\n".join(csv_lines)

        await self.ctx._send("🔍 מחפש רשומות לתיקון...", tid=tid, message=message, save=False)

        corrections = self.ctx.analyzer.analyze_bulk_correction(correction_text, entries_csv)

        if not corrections:
            await self.ctx._send("לא מצאתי רשומות שמתאימות לתיקון.", tid=tid, message=message, reply_markup=make_main_menu_keyboard(), save=False)
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

            self.ctx.food_repo.update(old_entry.id, {
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

        await self.ctx._send(report, tid=tid, message=message, reply_markup=make_main_menu_keyboard(), save=False)
        await safe_react(message, OK_HAND)
        return True
