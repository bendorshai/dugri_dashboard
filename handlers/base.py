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
from parsing import get_user_now, israel_today, is_within_eating_window
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

    def _is_within_window(self, profile: dict) -> bool:
        tz = profile.get("timezone", "Asia/Jerusalem")
        now = get_user_now(tz)
        return is_within_eating_window(
            now,
            profile.get("eating_window_start", "08:00"),
            profile.get("eating_window_end", "20:00"),
        )

    def _get_stats_date(self, profile: dict) -> str:
        """Return the date string whose stats should be displayed.

        Inside the eating window → today.
        Outside the window (evening, after close) → today (completed day).
        Outside the window (morning, before open) → yesterday.
        """
        tz = profile.get("timezone", "Asia/Jerusalem")
        now = get_user_now(tz)
        window_start = profile.get("eating_window_start", "08:00")
        window_end = profile.get("eating_window_end", "20:00")

        if is_within_eating_window(now, window_start, window_end):
            return now.strftime("%d/%m/%Y")

        current_minutes = now.hour * 60 + now.minute
        start_h, start_m = int(window_start.split(":")[0]), int(window_start.split(":")[1])
        start_minutes = start_h * 60 + start_m

        if current_minutes < start_minutes:
            yesterday = now - timedelta(days=1)
            return yesterday.strftime("%d/%m/%Y")
        return now.strftime("%d/%m/%Y")

    def _get_eating_day_entries(self, date_str: str, profile: dict) -> list[dict[str, str]]:
        """Return entries for a logical eating day. Single source of truth for daily views."""
        day = datetime.strptime(date_str, "%d/%m/%Y").date()
        next_day = (day + timedelta(days=1)).strftime("%d/%m/%Y")
        window_start = profile.get("eating_window_start", "08:00")
        return self.sheets.get_entries_for_eating_day(date_str, next_day, window_start)

    def _get_eating_day_totals(self, date_str: str, profile: dict) -> tuple[int, int]:
        """Read totals for a logical eating day from Google Sheets.

        Uses eating-day-aware filtering — the single source of truth for daily totals.
        """
        try:
            entries = self._get_eating_day_entries(date_str, profile)
            total_cal = 0
            total_prot = 0
            for entry in entries:
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
            logger.exception("Failed to read eating day totals from sheet")
            return 0, 0

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
            alerts.append("🎉 כל הכבוד! הגעת ליעד גרם החלבון היומי!")
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
            "שלח לי תיאור של מה שאכלת (טקסט או תמונה) ואני אחשב קלוריות וגרם חלבון.\n\n"
            f"📊 היעדים שלך:\n"
            f"  קלוריות: {profile.get('target_calories', 2000)}\n"
            f"  גרם חלבון: {profile.get('target_protein', 150)}\n"
            f"  חלון אכילה: {profile.get('eating_window_start', '08:00')}-{profile.get('eating_window_end', '20:00')}\n\n"
            "אפשר לשנות הגדרות דרך התפריט למטה."
        )
        await message.reply_text(text, reply_markup=make_main_menu_keyboard())

    async def handle_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message:
            return

        profile = self._get_profile()
        stats_date = self._get_stats_date(profile)
        total_cal, total_protein = self._get_eating_day_totals(stats_date, profile)

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

        # Check for pending food correction (from edit button)
        if await self._handle_pending_correction(message, context):
            return

        # Check for pending bulk fix
        if await self._handle_pending_bulk_fix(message, context):
            return

        await safe_react(message, THUMBS_UP)

        profile = self._get_profile()
        today_str = self._get_today_str(profile)
        time_str = self._get_time_str(profile)
        within_window = self._is_within_window(profile)

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

        row_number = self.sheets.append_food_entry(
            date_str=today_str,
            time_str=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            within_window=within_window,
        )

        # Read totals from sheet after appending (source of truth)
        stats_date = self._get_stats_date(profile)
        new_daily_cal, new_daily_prot = self._get_eating_day_totals(stats_date, profile)
        prev_cal = new_daily_cal - total_cal
        prev_protein = new_daily_prot - total_prot
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
        items_text = self._format_items_text(result.items, total_cal, total_prot)

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

        # Update last_entry context
        context.chat_data["last_entry"] = {
            "description": new_desc,
            "calories": new_cal,
            "protein": new_prot,
            "sheet_row": sheet_row,
        }

        # Re-read totals from sheet after correction
        stats_date = self._get_stats_date(profile)
        final_cal, final_prot = self._get_eating_day_totals(stats_date, profile)

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
        within_window = self._is_within_window(profile)

        # Download photo
        photo = message.photo[-1]  # Highest resolution
        file = await photo.get_file()
        photo_bytes = await file.download_as_bytearray()
        b64 = base64.b64encode(photo_bytes).decode("utf-8")

        caption = message.caption or ""

        result = self.analyzer.analyze_food_photo(b64, today_str, caption=caption)
        if result is None or not result.items:
            await message.reply_text("לא הצלחתי לזהות מאכל בתמונה. נסה לתאר מה אכלת בטקסט.")
            return

        # One row per message
        combined_desc = ", ".join(item.description for item in result.items)
        total_cal = result.total_calories
        total_prot = result.total_protein

        row_number = self.sheets.append_food_entry(
            date_str=today_str,
            time_str=time_str,
            description=combined_desc,
            calories=total_cal,
            protein=total_prot,
            within_window=within_window,
        )
        # Store last entry for correction context
        context.chat_data["last_entry"] = {
            "description": combined_desc,
            "calories": total_cal,
            "protein": total_prot,
            "sheet_row": row_number,
        }

        # Read totals from sheet after appending (source of truth)
        stats_date = self._get_stats_date(profile)
        new_daily_cal, new_daily_prot = self._get_eating_day_totals(stats_date, profile)
        prev_cal = new_daily_cal - total_cal
        prev_protein = new_daily_prot - total_prot

        items_text = self._format_items_text(result.items, total_cal, total_prot)

        alerts = self._check_crossing_alerts(prev_cal, prev_protein, new_daily_cal, new_daily_prot, profile)
        response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)
        if alerts:
            response = f"{alerts}\n\n{response}"

        # Add photo tip from GPT analysis
        if result.photo_tips:
            response += f"\n\n💡 {result.photo_tips[0]}"

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

        # NOTE: using calendar-date filtering here is acceptable for the 7-day
        # context window sent to GPT. For single-day totals, always use
        # _get_eating_day_entries / _get_eating_day_totals instead.
        entries = self.sheets.get_entries_by_dates(dates)
        csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון"]
        for e in entries:
            csv_lines.append(
                f"{e.get('תאריך','')},{e.get('שעה','')},{e.get('תיאור','')},{e.get('קלוריות',0)},{e.get('חלבון',0)}"
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

    async def _handle_pending_correction(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
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
        profile = self._get_profile()
        today_str = self._get_today_str(profile)
        sheet_row = entry["sheet_row"]

        # Use analyze_correction with full history so GPT only changes mentioned items
        correction = self.analyzer.analyze_correction(
            original_description=entry["description"],
            original_calories=entry["calories"],
            original_protein=entry["protein"],
            correction_history=correction_history,
            new_correction=message.text,
            today_str=today_str,
        )

        if correction:
            await self._handle_correction(message, context, correction, entry, profile, today_str)
            # Accumulate correction history for potential subsequent edits
            updated_history = correction_history + [message.text]
            context.chat_data.setdefault("correction_histories", {})[sheet_row] = updated_history
        else:
            await message.reply_text("לא הצלחתי להבין את התיקון. נסה שוב.")

        return True

    async def _handle_pending_bulk_fix(self, message, context: ContextTypes.DEFAULT_TYPE) -> bool:
        pending = context.chat_data.get("pending_bulk_fix")
        if not pending:
            return False
        if time.time() - pending.get("timestamp", 0) > PENDING_STATE_TTL:
            del context.chat_data["pending_bulk_fix"]
            return False

        del context.chat_data["pending_bulk_fix"]
        await safe_react(message, THUMBS_UP)

        correction_text = message.text.strip()

        # Read all entries from sheet
        all_entries = self.sheets.get_all_entries()
        if not all_entries:
            await message.reply_text("אין רשומות לתיקון.")
            return True

        # Build CSV for GPT
        csv_lines = ["row_index,תאריך,שעה,תיאור,קלוריות,חלבון"]
        for i, e in enumerate(all_entries):
            csv_lines.append(
                f"{i},{e.get('תאריך','')},{e.get('שעה','')},{e.get('תיאור','')},{e.get('קלוריות','0')},{e.get('חלבון','0')}"
            )
        entries_csv = "\n".join(csv_lines)

        await message.reply_text("🔍 מחפש רשומות לתיקון...")

        corrections = self.analyzer.analyze_bulk_correction(correction_text, entries_csv)

        if not corrections:
            await message.reply_text("לא מצאתי רשומות שמתאימות לתיקון.", reply_markup=make_main_menu_keyboard())
            return True

        # Apply corrections — sheet rows are 1-based, header is row 1, data starts at row 2
        report_lines = []
        total_cal_diff = 0
        total_prot_diff = 0

        for c in corrections:
            sheet_row = c.row_index + 2  # row_index is 0-based in data, +2 for header + 1-based
            old_entry = all_entries[c.row_index] if c.row_index < len(all_entries) else None
            if not old_entry:
                continue

            old_cal = int(old_entry.get("קלוריות", 0) or 0)
            old_prot = int(old_entry.get("חלבון", 0) or 0)

            self.sheets.update_cell_by_name(sheet_row, "תיאור", c.corrected_description)
            self.sheets.update_cell_by_name(sheet_row, "קלוריות", str(c.corrected_calories))
            self.sheets.update_cell_by_name(sheet_row, "חלבון", str(c.corrected_protein))

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
                f"גרם חלבון: {profile.get('target_protein', '-')}\n\n"
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

        profile = self._get_profile()
        stats_date = self._get_stats_date(profile)
        total_cal, total_protein = self._get_eating_day_totals(stats_date, profile)
        # Must use eating-day-aware filtering to match the totals above
        entries = self._get_eating_day_entries(stats_date, profile)

        target_cal = profile.get("target_calories", 2000)
        target_prot = profile.get("target_protein", 150)
        remaining_cal = max(0, target_cal - total_cal)
        remaining_prot = max(0, target_prot - total_protein)

        today_text = "\n".join(
            f"- {e.get('תיאור', '')}: {e.get('קלוריות', 0)} קל׳, {e.get('חלבון', 0)} גרם חלבון"
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
            await query.edit_message_text("🗑 הרשומה נמחקה.", reply_markup=make_daily_summary_keyboard())
        except Exception:
            logger.exception("Failed to delete food entry row %s", row_str)
            await query.edit_message_text("❌ שגיאה במחיקה.", reply_markup=make_daily_summary_keyboard())

    async def handle_food_edit_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        row_str = query.data.removeprefix(CB_FOOD_EDIT)
        try:
            row_number = int(row_str)
            entry_data = self.sheets.get_entry_data(row_number)
            description = entry_data.get("תיאור", "")
            calories = int(entry_data.get("קלוריות", 0) or 0)
            protein = int(entry_data.get("חלבון", 0) or 0)

            existing_history = context.chat_data.get("correction_histories", {}).get(row_number, [])
            context.chat_data["pending_correction"] = {
                "entry": {
                    "description": description,
                    "calories": calories,
                    "protein": protein,
                    "sheet_row": row_number,
                },
                "correction_history": existing_history,
                "timestamp": time.time(),
            }

            await query.edit_message_text(
                f"✏️ עריכת רשומה: {description}\n"
                f"קלוריות: {calories} | גרם חלבון: {protein}\n\n"
                "שלח תיאור של התיקון (למשל: 'זה היה 300 גרם לא 150'):"
            )
        except Exception:
            logger.exception("Failed to read entry for edit, row %s", row_str)
            await query.edit_message_text("❌ שגיאה בקריאת הרשומה.", reply_markup=make_daily_summary_keyboard())

    async def handle_food_again_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        row_str = query.data.removeprefix(CB_FOOD_AGAIN)
        try:
            row_number = int(row_str)
            entry_data = self.sheets.get_entry_data(row_number)
            description = entry_data.get("תיאור", "")
            calories = int(entry_data.get("קלוריות", 0) or 0)
            protein = int(entry_data.get("חלבון", 0) or 0)

            profile = self._get_profile()
            today_str = self._get_today_str(profile)
            time_str = self._get_time_str(profile)
            within_window = self._is_within_window(profile)

            new_row = self.sheets.append_food_entry(
                date_str=today_str,
                time_str=time_str,
                description=description,
                calories=calories,
                protein=protein,
                within_window=within_window,
            )

            stats_date = self._get_stats_date(profile)
            new_daily_cal, new_daily_prot = self._get_eating_day_totals(stats_date, profile)

            items_text = f"🔁 {description}: {calories} קל׳ | {protein} גרם חלבון"
            response = self._build_food_response(items_text, new_daily_cal, new_daily_prot, profile)

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=response,
                reply_markup=make_food_entry_keyboard(new_row),
            )
        except Exception:
            logger.exception("Failed to duplicate food entry row %s", row_str)
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

        profile = self._get_profile()
        target_cal = profile.get("target_calories", 2000)
        target_prot = profile.get("target_protein", 150)
        window_start = profile.get("eating_window_start", "08:00")

        stats_date = self._get_stats_date(profile)
        next_date = (datetime.strptime(stats_date, "%d/%m/%Y") + timedelta(days=1)).strftime("%d/%m/%Y")
        entries = self.sheets.get_entries_for_eating_day(stats_date, next_date, window_start)

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
            desc = e.get("תיאור", "")
            cal = int(e.get("קלוריות", 0) or 0)
            prot = int(e.get("חלבון", 0) or 0)
            entry_time = e.get("שעה", "")
            total_cal += cal
            total_prot += prot
            lines.append(f"{i}. {desc} — {cal} קל׳ | {prot} גרם חלבון ({entry_time})")

        status = format_daily_status(total_cal, total_prot, target_cal, target_prot)
        text = "\n".join(lines) + status

        await send_long_text(query.message, text, reply_markup=make_daily_summary_keyboard())

    async def handle_weekly_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        profile = self._get_profile()
        target_cal = profile.get("target_calories", 2000)
        target_prot = profile.get("target_protein", 150)
        window_start = profile.get("eating_window_start", "08:00")
        window_end = profile.get("eating_window_end", "20:00")

        tz = profile.get("timezone", "Asia/Jerusalem")
        now = get_user_now(tz)
        today = now.date()

        # Collect last 7 logical eating days
        dates = [(today - timedelta(days=i)) for i in range(7)]

        lines = ["📅 סיכום שבועי:\n"]
        for d in dates:
            ds = d.strftime("%d/%m/%Y")
            next_ds = (d + timedelta(days=1)).strftime("%d/%m/%Y")
            day_label = d.strftime("%a %d/%m")
            entries = self.sheets.get_entries_for_eating_day(ds, next_ds, window_start)

            if not entries:
                lines.append(f"📆 {day_label}  —  אין נתונים")
                continue

            day_cal = 0
            day_prot = 0
            window_kept = True
            for e in entries:
                try:
                    day_cal += int(e.get("קלוריות", 0) or 0)
                except (ValueError, TypeError):
                    pass
                try:
                    day_prot += int(e.get("חלבון", 0) or 0)
                except (ValueError, TypeError):
                    pass
                entry_time = e.get("שעה", "")
                if entry_time and not (window_start <= entry_time < window_end):
                    window_kept = False

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
        await query.edit_message_text(
            text,
            reply_markup=make_main_menu_keyboard(),
        )

    async def handle_back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await safe_answer(query)

        profile = self._get_profile()
        stats_date = self._get_stats_date(profile)
        total_cal, total_protein = self._get_eating_day_totals(stats_date, profile)

        status = format_daily_status(
            total_cal, total_protein,
            profile.get("target_calories", 2000),
            profile.get("target_protein", 150),
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

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="🤔 מכין משוב...",
        )

        try:
            profile = self._get_profile()
            tz_str = profile.get("timezone", "Asia/Jerusalem")
            import pytz
            today = datetime.now(pytz.timezone(tz_str)).date()
            today_str = today.strftime("%d/%m/%Y")

            # Build week's data
            dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]
            week_entries = self.sheets.get_entries_by_dates(dates)

            if not week_entries:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="אין נתונים מהשבוע האחרון לתת עליהם משוב.",
                    reply_markup=make_main_menu_keyboard(),
                )
                return

            csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון"]
            for e in week_entries:
                csv_lines.append(
                    f"{e.get('תאריך','')},{e.get('שעה','')},{e.get('תיאור','')},{e.get('קלוריות',0)},{e.get('חלבון',0)}"
                )
            week_csv = "\n".join(csv_lines)

            target_cal = profile.get("target_calories", 2000)
            target_prot = profile.get("target_protein", 150)
            targets = {"calories": target_cal, "protein": target_prot}

            past_fb = [f.get("feedback_text", "") for f in self.mongo.get_recent_feedbacks(self.chat_id, limit=7)]

            feedback_result = self.analyzer.generate_weekly_feedback(week_csv, targets, past_fb)

            if feedback_result and feedback_result.get("feedback_text"):
                feedback_text = feedback_result["feedback_text"]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"💬 משוב על התזונה:\n{feedback_text}",
                    reply_markup=make_main_menu_keyboard(),
                )
            else:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="לא הצלחתי לייצר משוב כרגע. נסה שוב מאוחר יותר.",
                    reply_markup=make_main_menu_keyboard(),
                )
        except Exception:
            logger.exception("Failed to generate feedback")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ שגיאה ביצירת משוב.",
                reply_markup=make_main_menu_keyboard(),
            )
