from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

import pytz

from parsing import parse_time_window

logger = logging.getLogger(__name__)


def schedule_eating_window_jobs(job_queue, chat_id: int, profile: dict, mongo, analyzer, sheets):
    """Schedule eating window warning and close jobs."""
    # Cancel existing jobs for this chat
    for job in job_queue.get_jobs_by_name(f"window_{chat_id}_warning"):
        job.schedule_removal()
    for job in job_queue.get_jobs_by_name(f"window_{chat_id}_close"):
        job.schedule_removal()

    tz_str = profile.get("timezone", "Asia/Jerusalem")
    tz = pytz.timezone(tz_str)
    end_h, end_m = parse_time_window(profile.get("eating_window_end", "20:00"))

    # 30-min warning
    warning_dt = datetime(2000, 1, 1, end_h, end_m) - timedelta(minutes=30)
    warning_time = time(warning_dt.hour, warning_dt.minute, tzinfo=tz)

    job_queue.run_daily(
        _window_warning_callback,
        time=warning_time,
        chat_id=chat_id,
        name=f"window_{chat_id}_warning",
        data={
            "chat_id": chat_id,
            "mongo": mongo,
            "sheets": sheets,
        },
    )

    # Window close
    close_time = time(end_h, end_m, tzinfo=tz)
    job_queue.run_daily(
        _window_close_callback,
        time=close_time,
        chat_id=chat_id,
        name=f"window_{chat_id}_close",
        data={
            "chat_id": chat_id,
            "mongo": mongo,
            "analyzer": analyzer,
            "sheets": sheets,
        },
    )

    logger.info("Scheduled eating window jobs for chat %d: warning at %s, close at %s",
                chat_id, warning_time, close_time)


def _get_eating_day_totals(sheets, today_str, profile):
    """Read totals for a logical eating day from Google Sheets."""
    day = datetime.strptime(today_str, "%d/%m/%Y").date()
    next_day = (day + timedelta(days=1)).strftime("%d/%m/%Y")
    window_start = profile.get("eating_window_start", "08:00")

    entries = sheets.get_entries_for_eating_day(today_str, next_day, window_start)
    total_cal = sum(int(e.get("קלוריות", 0) or 0) for e in entries)
    total_prot = sum(int(e.get("חלבון", 0) or 0) for e in entries)
    return total_cal, total_prot


async def _window_warning_callback(context):
    data = context.job.data
    chat_id = data["chat_id"]
    mongo = data["mongo"]
    sheets = data["sheets"]

    profile = mongo.get_user_profile(chat_id) or {}
    tz_str = profile.get("timezone", "Asia/Jerusalem")
    today_str = datetime.now(pytz.timezone(tz_str)).strftime("%d/%m/%Y")
    total_cal, total_prot = _get_eating_day_totals(sheets, today_str, profile)

    target_cal = profile.get("target_calories", 2000)
    target_prot = profile.get("target_protein", 150)
    remaining_cal = target_cal - total_cal
    remaining_prot = target_prot - total_prot

    prot_status = f"נותרו {remaining_prot}g" if remaining_prot > 0 else "✅ הגעת ליעד!"

    text = (
        "⏰ חלון האכילה נסגר בעוד 30 דקות!\n\n"
        f"קלוריות: {total_cal}/{target_cal} (נותרו: {remaining_cal})\n"
        f"חלבון: {total_prot}g/{target_prot}g ({prot_status})"
    )

    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.exception("Failed to send window warning")


async def _window_close_callback(context):
    data = context.job.data
    chat_id = data["chat_id"]
    mongo = data["mongo"]
    analyzer = data["analyzer"]
    sheets = data["sheets"]

    profile = mongo.get_user_profile(chat_id) or {}
    tz_str = profile.get("timezone", "Asia/Jerusalem")
    today_str = datetime.now(pytz.timezone(tz_str)).strftime("%d/%m/%Y")
    total_cal, total_prot = _get_eating_day_totals(sheets, today_str, profile)

    target_cal = profile.get("target_calories", 2000)
    target_prot = profile.get("target_protein", 150)

    cal_delta = total_cal - target_cal
    prot_delta = total_prot - target_prot

    cal_icon = "✅" if cal_delta <= 0 else "⚠️"
    prot_icon = "✅" if prot_delta >= 0 else "⚠️"

    cal_text = f"{abs(cal_delta)} מתחת ליעד" if cal_delta <= 0 else f"{cal_delta} מעל היעד"
    prot_text = f"{prot_delta} מעל היעד" if prot_delta >= 0 else f"{abs(prot_delta)} מתחת ליעד"

    summary = (
        "🌙 חלון האכילה נסגר! סיכום יומי:\n\n"
        f"{cal_icon} קלוריות: {total_cal}/{target_cal} ({cal_text})\n"
        f"{prot_icon} חלבון: {total_prot}g/{target_prot}g ({prot_text})"
    )

    # Daily GPT coaching feedback (GPT analyzes the full week for context)
    feedback_text = ""
    day = datetime.strptime(today_str, "%d/%m/%Y").date()
    next_day = (day + timedelta(days=1)).strftime("%d/%m/%Y")
    window_start = profile.get("eating_window_start", "08:00")
    today_entries = sheets.get_entries_for_eating_day(today_str, next_day, window_start)

    if today_entries:
        # Build week's data
        dates = [(day - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]
        week_entries = sheets.get_entries_by_dates(dates)

        csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון,בחלון אכילה"]
        for e in week_entries:
            csv_lines.append(
                f"{e.get('תאריך','')},{e.get('שעה','')},{e.get('תיאור','')},{e.get('קלוריות',0)},{e.get('חלבון',0)},{e.get('בחלון אכילה','')}"
            )
        week_csv = "\n".join(csv_lines)

        past_fb = [f.get("feedback_text", "") for f in mongo.get_recent_feedbacks(chat_id, limit=7)]
        insights = [i.get("insight_text", "") for i in mongo.get_recent_insights(chat_id, limit=5)]

        targets = {"calories": target_cal, "protein": target_prot}
        feedback_result = analyzer.generate_weekly_feedback(week_csv, targets, past_fb, insights)

        if feedback_result:
            feedback_text = feedback_result.get("feedback_text", "")
            insight = feedback_result.get("insight", "")
            insight_category = feedback_result.get("insight_category", "")

            if feedback_text:
                feedback_text = f"\n\n💬 משוב יומי:\n{feedback_text}"
                mongo.save_weekly_feedback(
                    chat_id=chat_id,
                    date_str=today_str,
                    feedback_text=feedback_text,
                    week_summary={"total_cal": total_cal, "total_prot": total_prot},
                )
                if insight:
                    mongo.save_gpt_insight(
                        chat_id=chat_id,
                        insight_type=insight_category or "feedback_effectiveness",
                        insight_text=insight,
                        context={"feedback_given": feedback_text},
                    )

    try:
        await context.bot.send_message(chat_id=chat_id, text=summary + feedback_text)
    except Exception:
        logger.exception("Failed to send window close summary")
