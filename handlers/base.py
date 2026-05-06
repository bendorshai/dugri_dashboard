from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from sheets import SheetsClient
from analyzer import FoodAnalyzer
from storage import MongoStorage
from parsing import get_user_now, israel_today
from keyboards import (
    THUMBS_UP, OK_HAND,
    make_daily_summary_keyboard, make_main_menu_keyboard,
    make_profile_keyboard, make_settings_keyboard,
    make_food_edit_keyboard, make_food_entry_keyboard, format_daily_status,
    CB_MENU, CB_PROFILE, CB_EDIT_FIELD, CB_SUGGEST,
    CB_ASK, CB_FOOD_DELETE, CB_BACK,
)
from handlers.utils import PENDING_STATE_TTL, safe_react, send_long_text, safe_answer

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = {
    "age": 30,
    "height_cm": 175,
    "weight_kg": 80,
    "target_calories": 2000,
    "target_protein": 150,
    "eating_window_start": "08:00",
    "eating_window_end": "20:00",
    "timezone": "Asia/Jerusalem",
}

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
        chat_id: int,
        sheets_client: SheetsClient,
        analyzer: FoodAnalyzer,
        mongo_storage: MongoStorage,
    ):
        self.chat_id = chat_id
        self.sheets = sheets_client
        self.analyzer = analyzer
        self.mongo = mongo_storage

    def _get_profile(self) -> dict:
        profile = self.mongo.get_user_profile(self.chat_id)
        if profile is None:
            self.mongo.save_user_profile(self.chat_id, DEFAULT_PROFILE.copy())
            return DEFAULT_PROFILE.copy()
        return profile

    def _get_today_str(self, profile: dict) -> str:
        tz = profile.get("timezone", "Asia/Jerusalem")
        now = get_user_now(tz)
        return now.strftime("%d/%m/%Y")

    def _get_time_str(self, profile: dict) -> str:
        tz = profile.get("timezone", "Asia/Jerusalem")
        now = get_user_now(tz)
        return now.strftime("%H:%M")

    def _calculate_daily_totals(self, entries: list[dict]) -> tuple[int, int]:
        total_cal = sum(e.get("calories", 0) for e in entries)
        total_prot = sum(e.get("protein", 0) for e in entries)
        return total_cal, total_prot

    def _get_daily_totals_from_sheet(self, today_str: str) -> tuple[int, int]:
        """Read daily totals from Google Sheets as source of truth."""
        try:
            all_entries = self.sheets.get_all_entries()
            total_cal = 0
            total_prot = 0
            for entry in all_entries:
                if entry.get("תאריך") == today_str:
                    try:
                        total_cal += int(entry.get("קלוריות", 0) or 0)
                    except (ValueError, TypeError):
                        pass
                    try:
                        total_prot += int(entry.get("חלבון", 0) or 0)
                    except (ValueError, TypeError):
                        pass
            return total_cal, total_prot
        except Exception:
            logger.exception("Failed to read daily totals from sheet, falling back to MongoDB")
            entries = self.mongo.get_today_entries(self.chat_id, today_str)
            return self._calculate_daily_totals(entries)

    def _build_food_response(
        self,
        items_text: str,
        total_cal: int,
        total_protein: int,
        profile: dict,
    ) -> str:
        status = format_daily_status(
            total_cal, total_protein,
            profile.get("target_calories", 2000),
            profile.get("target_protein", 150),
        )
        return f"{items_text}{status}"

    def _check_crossing_alerts(
        self,
        prev_cal: int,
        prev_protein: int,
        new_cal: int,
        new_protein: int,
        profile: dict,
    ) -> str:
        alerts = []
        target_cal = profile.get("target_calories", 2000)
        target_prot = profile.get("target_protein", 150)

        if prev_protein < target_prot <= new_protein:
            alerts.append("🎉 כל הכבוד! הגעת ליעד החלבון היומי!")
        if prev_cal <= target_cal < new_cal:
            alerts.append("⚠️ שים לב — עברת את יעד הקלוריות היומי.")

        return "\n".join(alerts)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message:
            return

        profile = self._get_profile()
        text = (
            "שלום! 👋\n"
            "אני הבוט שלך למעקב תזונה.\n\n"
            "שלח לי תיאור של מה שאכלת (טקסט או תמונה) ואני אחשב קלוריות וחלבון.\n\n"
            f"📊 היעדים שלך:\n"
            f"  קלוריות: {profile.get('target_calories', 2000)}\n"
            f"  חלבון: {profile.get('target_protein', 150)}g\n"
            f"  חלון אכילה: {profile.get('eating_window_start', '08:00')}-{profile.get('eating_window_end', '20:00')}\n\n"
            "אפשר לשנות הגדרות דרך התפריט למטה."
        )
        await message.reply_text(text, reply_markup=make_main_menu_keyboard())

    async def handle_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message:
            return

        profile = self._get_profile()
        today_str = self._get_today_str(profile)
        total_cal, total_protein = self._get_daily_totals_from_sheet(today_str)

        status = format_daily_status(
            total_cal, total_protein,
            profile.get("target_calories", 2000),
            profile.get("target_protein", 150),
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
        if message.chat_id != self.chat_id:
            return

        # Check for pending profile edit
        if await self._handle_pending_edit(message, context):
            return

        # Check for pending question
        if await self._handle_pending_question(message, context):
            return

        await safe_react(message, THUMBS_UP)

        profile = self._get_profile()
        today_str = self._get_today_str(profile)
        time_str = self._get_time_str(profile)

        # Get previous totals from sheet
        prev_cal, prev_protein = self._get_daily_totals_from_sheet(today_str)

        # Get last entry context for correction detection
        last_entry = context.chat_data.get("last_entry")

        # Parse message: food or correction?
        parse_result = self.analyzer.parse_message(message.text, today_str, last_entry)

        if parse_result.type == "correction" and parse_result.correction and last_entry:
            await self._handle_correction(message, context, parse_result.correction, last_entry, profile, today_str)
            return

        # Treat as new food (use parsed food result, or fall back to analyze_food_text)
        if parse_result.type == "food" and parse_result.food and parse_result.food.items:
            result = parse_result.food
        else:
            result = self.analyzer.analyze_food_text(message.text, today_str)

        if result is None or not result.items:
            await message.reply_text("לא הצלחתי לזהות מאכל בהודעה. נסה שוב?")
            return

        # One row per message: consolidate all items
        combined_desc = ", ".join(item.description for item in result.items)
        total_cal = result.total_calories
        total_prot = result.total_protein

        new_daily_cal = prev_cal + total_cal
        new_daily_prot = prev_protein + total_prot

        row_number = self.sheets.append_food_entry(
            date_str=today_str,
            time_str=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            daily_total_cal=new_daily_cal,
            daily_total_protein=new_daily_prot,
        )
        self.mongo.save_food_entry(
            chat_id=self.chat_id,
            date_str=today_str,
            time_str=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            source="text",
            sheet_row=row_number,
        )
        logger.info("Recorded: %s (%d cal, %dg protein) -> row %d",
                    combined_desc, total_cal, total_prot, row_number)

        # Store last entry for correction context
        context.chat_data["last_entry"] = {
            "description": combined_desc,
            "calories": total_cal,
            "protein": total_prot,
            "sheet_row": row_number,
        }

        # Build response with item breakdown
        items_lines = [f"• {item.description}: {item.calories} קל׳ | {item.protein}g חלבון" for item in result.items]
        items_text = "\n".join(items_lines)
        if len(result.items) > 1:
            items_text += f"\n\nסה\"כ: {total_cal} קל׳ | {total_prot}g חלבון"

        # Check crossing alerts
        alerts = self._check_crossing_alerts(prev_cal, prev_protein, new_daily_cal, new_daily_prot, profile)

        response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)
        if alerts:
            response = f"{alerts}\n\n{response}"

        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(row_number))
        await safe_react(message, OK_HAND)

    async def _handle_correction(
        self, message, context, correction, last_entry: dict, profile: dict, today_str: str,
    ):
        """Handle a correction to the last food entry."""
        sheet_row = last_entry["sheet_row"]
        old_cal = last_entry["calories"]
        old_prot = last_entry["protein"]

        new_desc = correction.corrected_description
        new_cal = correction.corrected_calories
        new_prot = correction.corrected_protein

        # Update Google Sheets
        self.sheets.update_cell_by_name(sheet_row, "תיאור", new_desc)
        self.sheets.update_cell_by_name(sheet_row, "קלוריות", str(new_cal))
        self.sheets.update_cell_by_name(sheet_row, "חלבון", str(new_prot))

        # Update daily totals in sheet
        daily_cal, daily_prot = self._get_daily_totals_from_sheet(today_str)
        # Adjust: sheet already has old values, we need to replace them
        adjusted_cal = daily_cal - old_cal + new_cal
        adjusted_prot = daily_prot - old_prot + new_prot
        self.sheets.update_cell_by_name(sheet_row, "סהכ קלוריות יומי", str(adjusted_cal))
        self.sheets.update_cell_by_name(sheet_row, "סהכ חלבון יומי", str(adjusted_prot))

        # Update MongoDB
        self.mongo.update_food_entry(self.chat_id, sheet_row, {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
        })

        # Update last_entry context
        context.chat_data["last_entry"] = {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
            "sheet_row": sheet_row,
        }

        # Re-read totals from sheet after correction
        final_cal, final_prot = self._get_daily_totals_from_sheet(today_str)

        cal_diff = new_cal - old_cal
        prot_diff = new_prot - old_prot
        diff_text = []
        if cal_diff != 0:
            diff_text.append(f"קלוריות: {old_cal} → {new_cal} ({'+' if cal_diff > 0 else ''}{cal_diff})")
        if prot_diff != 0:
            diff_text.append(f"חלבון: {old_prot}g → {new_prot}g ({'+' if prot_diff > 0 else ''}{prot_diff}g)")

        response = f"✏️ עודכן: {new_desc}\n" + "\n".join(diff_text)
        status = format_daily_status(
            final_cal, final_prot,
            profile.get("target_calories", 2000),
            profile.get("target_protein", 150),
        )
        response += status

        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(sheet_row))
        await safe_react(message, OK_HAND)

    # ------------------------------------------------------------------
    # Photo handler
    # ------------------------------------------------------------------

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.photo:
            return
        if message.chat_id != self.chat_id:
            return

        await safe_react(message, THUMBS_UP)

        profile = self._get_profile()
        today_str = self._get_today_str(profile)
        time_str = self._get_time_str(profile)

        # Download photo
        photo = message.photo[-1]  # Highest resolution
        file = await photo.get_file()
        photo_bytes = await file.download_as_bytearray()
        b64 = base64.b64encode(photo_bytes).decode("utf-8")

        caption = message.caption or ""

        # Get previous totals from sheet
        prev_cal, prev_protein = self._get_daily_totals_from_sheet(today_str)

        result = self.analyzer.analyze_food_photo(b64, today_str, caption=caption)
        if result is None or not result.items:
            await message.reply_text("לא הצלחתי לזהות מאכל בתמונה. נסה לתאר מה אכלת בטקסט.")
            return

        # One row per message
        combined_desc = ", ".join(item.description for item in result.items)
        total_cal = result.total_calories
        total_prot = result.total_protein

        new_daily_cal = prev_cal + total_cal
        new_daily_prot = prev_protein + total_prot

        row_number = self.sheets.append_food_entry(
            date_str=today_str,
            time_str=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            daily_total_cal=new_daily_cal,
            daily_total_protein=new_daily_prot,
        )
        self.mongo.save_food_entry(
            chat_id=self.chat_id,
            date_str=today_str,
            time_str=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            source="photo",
            sheet_row=row_number,
        )

        # Store last entry for correction context
        context.chat_data["last_entry"] = {
            "description": combined_desc,
            "calories": total_cal,
            "protein": total_prot,
            "sheet_row": row_number,
        }

        items_lines = [f"• {item.description}: {item.calories} קל׳ | {item.protein}g חלבון" for item in result.items]
        items_text = "\n".join(items_lines)
        if len(result.items) > 1:
            items_text += f"\n\nסה\"כ: {total_cal} קל׳ | {total_prot}g חלבון"

        alerts = self._check_crossing_alerts(prev_cal, prev_protein, new_daily_cal, new_daily_prot, profile)
        response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)
        if alerts:
            response = f"{alerts}\n\n{response}"

        await send_long_text(message, response, reply_markup=make_food_entry_keyboard(row_number))
        await safe_react(message, OK_HAND)

    # ------------------------------------------------------------------
    # Pending edit/question state
    # ------------------------------------------------------------------

    async def _handle_pending_edit(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
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
                self.mongo.save_user_profile(self.chat_id, {
                    "eating_window_start": parts[0].strip(),
                    "eating_window_end": parts[1].strip(),
                })
            elif field in ("age", "height_cm", "weight_kg", "target_calories", "target_protein"):
                value = int(text)
                self.mongo.save_user_profile(self.chat_id, {field: value})
            elif field == "timezone":
                self.mongo.save_user_profile(self.chat_id, {"timezone": text})
            else:
                await message.reply_text("שדה לא מוכר.")
                return True

            await safe_react(message, OK_HAND)
            await message.reply_text(f"✅ {FIELD_LABELS.get(field, field)} עודכן!")

            # Reschedule eating window if needed
            if field == "eating_window":
                from scheduler import schedule_eating_window_jobs
                profile = self._get_profile()
                schedule_eating_window_jobs(
                    context.job_queue, self.chat_id, profile,
                    self.mongo, self.analyzer, self.sheets,
                )

        except ValueError:
            await message.reply_text("ערך לא תקין. נסה שוב.")
        except Exception:
            logger.exception("Failed to update profile field %s", field)
            await message.reply_text("❌ שגיאה בעדכון.")

        return True

    async def _handle_pending_question(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
        pending = context.chat_data.get("pending_question")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_question"]
            return False

        del context.chat_data["pending_question"]
        question = message.text.strip()

        await safe_react(message, THUMBS_UP)

        profile = self._get_profile()
        today_str = self._get_today_str(profile)

        # Get week's data
        dates = []
        from datetime import date
        today = datetime.strptime(today_str, "%d/%m/%Y").date()
        for i in range(7):
            d = today - timedelta(days=i)
            dates.append(d.strftime("%d/%m/%Y"))

        entries = self.mongo.get_week_entries(self.chat_id, dates)
        csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון"]
        for e in entries:
            csv_lines.append(
                f"{e.get('date','')},{e.get('time','')},{e.get('description','')},{e.get('calories',0)},{e.get('protein',0)}"
            )
        week_csv = "\n".join(csv_lines)

        targets = {
            "calories": profile.get("target_calories", 2000),
            "protein": profile.get("target_protein", 150),
        }

        answer = self.analyzer.answer_question(question, week_csv, targets)
        if answer:
            await send_long_text(message, answer, reply_markup=make_daily_summary_keyboard())
        else:
            await message.reply_text("לא הצלחתי לענות. נסה שוב.")

        return True

    # ------------------------------------------------------------------
    # Callback handlers
    # ------------------------------------------------------------------

    async def handle_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        data = query.data.removeprefix(CB_MENU)

        if data == "profile":
            profile = self._get_profile()
            text = (
                "👤 הפרופיל שלך:\n\n"
                f"גיל: {profile.get('age', '-')}\n"
                f"גובה: {profile.get('height_cm', '-')} ס\"מ\n"
                f"משקל: {profile.get('weight_kg', '-')} ק\"ג\n\n"
                f"🎯 יעדים:\n"
                f"קלוריות: {profile.get('target_calories', '-')}\n"
                f"חלבון: {profile.get('target_protein', '-')}g\n\n"
                f"⏰ חלון אכילה: {profile.get('eating_window_start', '08:00')}-{profile.get('eating_window_end', '20:00')}\n"
                f"🌍 אזור זמן: {profile.get('timezone', 'Asia/Jerusalem')}\n\n"
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

        data = query.data.removeprefix(CB_PROFILE)

        if data == "suggest_targets":
            profile = self._get_profile()
            height = profile.get("height_cm", 0)
            weight = profile.get("weight_kg", 0)
            age = profile.get("age", 0)

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
                self.mongo.save_user_profile(self.chat_id, {
                    "target_calories": cal,
                    "target_protein": prot,
                })
                await query.edit_message_text(
                    f"🎯 יעדים מומלצים עודכנו:\n"
                    f"קלוריות: {cal}\n"
                    f"חלבון: {prot}g",
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

        profile = self._get_profile()
        today_str = self._get_today_str(profile)
        entries = self.mongo.get_today_entries(self.chat_id, today_str)
        total_cal, total_protein = self._calculate_daily_totals(entries)

        target_cal = profile.get("target_calories", 2000)
        target_prot = profile.get("target_protein", 150)
        remaining_cal = max(0, target_cal - total_cal)
        remaining_prot = max(0, target_prot - total_protein)

        today_text = "\n".join(
            f"- {e.get('description', '')}: {e.get('calories', 0)} קל׳, {e.get('protein', 0)}g"
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

        row_str = query.data.removeprefix(CB_FOOD_DELETE)
        try:
            row_number = int(row_str)
            self.sheets.delete_row(row_number)
            self.mongo.delete_food_entry(self.chat_id, row_number)
            await query.edit_message_text("🗑 הרשומה נמחקה.", reply_markup=make_daily_summary_keyboard())
        except Exception:
            logger.exception("Failed to delete food entry row %s", row_str)
            await query.edit_message_text("❌ שגיאה במחיקה.", reply_markup=make_daily_summary_keyboard())

    async def handle_back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        profile = self._get_profile()
        today_str = self._get_today_str(profile)
        total_cal, total_protein = self._get_daily_totals_from_sheet(today_str)

        status = format_daily_status(
            total_cal, total_protein,
            profile.get("target_calories", 2000),
            profile.get("target_protein", 150),
        )
        await query.edit_message_text(
            f"📋 תפריט ראשי{status}",
            reply_markup=make_main_menu_keyboard(),
        )
