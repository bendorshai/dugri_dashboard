"""
scheduler.py — תזמון jobs של חלון אכילה.

מתזמן התרעת 30 דקות לפני סגירת חלון וסיכום בסגירת חלון.

תלוי ב: repositories, services, analyzer, parsing.
נצרך על ידי: bot.py, handlers/base.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

import pytz

from models.profile import UserProfile
from parsing import parse_time_window

logger = logging.getLogger(__name__)


def schedule_eating_window_jobs(
    job_queue,
    telegram_user_id: int,
    profile: UserProfile,
    user_repo,
    food_repo,
    feedback_repo,
    analyzer,
    eating_day_service,
):
    """Schedule eating window warning and close jobs."""
    for job in job_queue.get_jobs_by_name(f"window_{telegram_user_id}_warning"):
        job.schedule_removal()
    for job in job_queue.get_jobs_by_name(f"window_{telegram_user_id}_close"):
        job.schedule_removal()

    tz_str = profile.timezone
    tz = pytz.timezone(tz_str)
    window_end = profile.eating_window.end if profile.eating_window else "20:00"
    end_h, end_m = parse_time_window(window_end)

    # 30-min warning
    warning_dt = datetime(2000, 1, 1, end_h, end_m) - timedelta(minutes=30)
    warning_time = time(warning_dt.hour, warning_dt.minute, tzinfo=tz)

    job_queue.run_daily(
        _window_warning_callback,
        time=warning_time,
        chat_id=telegram_user_id,
        name=f"window_{telegram_user_id}_warning",
        data={
            "telegram_user_id": telegram_user_id,
            "user_repo": user_repo,
            "eating_day_service": eating_day_service,
        },
    )

    # Window close
    close_time = time(end_h, end_m, tzinfo=tz)
    job_queue.run_daily(
        _window_close_callback,
        time=close_time,
        chat_id=telegram_user_id,
        name=f"window_{telegram_user_id}_close",
        data={
            "telegram_user_id": telegram_user_id,
            "user_repo": user_repo,
            "food_repo": food_repo,
            "feedback_repo": feedback_repo,
            "analyzer": analyzer,
            "eating_day_service": eating_day_service,
        },
    )

    logger.info("Scheduled eating window jobs for user %d: warning at %s, close at %s",
                telegram_user_id, warning_time, close_time)


async def _window_warning_callback(context):
    data = context.job.data
    tid = data["telegram_user_id"]
    user_repo = data["user_repo"]
    eating_day_svc = data["eating_day_service"]

    profile = user_repo.get(tid)
    if profile is None:
        return

    from parsing import get_user_now
    today_str = get_user_now(profile.timezone).strftime("%d/%m/%Y")
    total_cal, total_prot = eating_day_svc.get_eating_day_totals(profile, today_str)

    target_cal = profile.targets.calories or 2000
    target_prot = profile.targets.protein or 150
    remaining_cal = target_cal - total_cal
    remaining_prot = target_prot - total_prot

    cal_pct = round(total_cal / target_cal * 100) if target_cal else 0
    prot_pct = round(total_prot / target_prot * 100) if target_prot else 0
    prot_status = f"נותרו {remaining_prot}" if remaining_prot > 0 else "✅ הגעת ליעד!"

    text = (
        "⏰ חלון האכילה נסגר בעוד 30 דקות!\n\n"
        f"קלוריות: {total_cal}/{target_cal} ({cal_pct}%, נותרו: {remaining_cal})\n"
        f"גרם חלבון: {total_prot}/{target_prot} ({prot_pct}%, {prot_status})"
    )

    try:
        await context.bot.send_message(chat_id=tid, text=text)
    except Exception:
        logger.exception("Failed to send window warning")


async def _window_close_callback(context):
    data = context.job.data
    tid = data["telegram_user_id"]
    user_repo = data["user_repo"]
    food_repo = data["food_repo"]
    feedback_repo = data["feedback_repo"]
    analyzer = data["analyzer"]
    eating_day_svc = data["eating_day_service"]

    profile = user_repo.get(tid)
    if profile is None:
        return

    from parsing import get_user_now
    today_str = get_user_now(profile.timezone).strftime("%d/%m/%Y")
    total_cal, total_prot = eating_day_svc.get_eating_day_totals(profile, today_str)

    target_cal = profile.targets.calories or 2000
    target_prot = profile.targets.protein or 150

    cal_delta = total_cal - target_cal
    prot_delta = total_prot - target_prot

    cal_icon = "✅" if cal_delta <= 0 else "⚠️"
    prot_icon = "✅" if prot_delta >= 0 else "⚠️"

    cal_pct = round(total_cal / target_cal * 100) if target_cal else 0
    prot_pct = round(total_prot / target_prot * 100) if target_prot else 0
    cal_text = f"{abs(cal_delta)} מתחת ליעד" if cal_delta <= 0 else f"{cal_delta} מעל היעד"
    prot_text = f"{prot_delta} מעל היעד" if prot_delta >= 0 else f"{abs(prot_delta)} מתחת ליעד"

    summary = (
        "🌙 חלון האכילה נסגר! סיכום יומי:\n\n"
        f"{cal_icon} קלוריות: {total_cal}/{target_cal} ({cal_pct}%, {cal_text})\n"
        f"{prot_icon} גרם חלבון: {total_prot}/{target_prot} ({prot_pct}%, {prot_text})"
    )

    # No automatic GPT coaching — just the dry numeric summary.
    # Feedback is opt-in only (via /menu button or classifier).

    try:
        await context.bot.send_message(chat_id=tid, text=summary)
    except Exception:
        logger.exception("Failed to send window close summary")
