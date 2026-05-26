"""
scheduler.py — תזמון jobs: חלון אכילה + hooks של מתגים.

מתזמן את כל ה-hooks הפרואקטיביים (שינה, אימונים, משהו טוב, סיכום שבועי,
חלון אכילה) וגם את התרעות חלון האכילה.

תלוי ב: repositories, services, analyzer, parsing, constants, messages.
נצרך על ידי: bot.py, handlers/base.py.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta, timezone

import pytz

from constants import (
    SLEEP_HOOK_WINDOW,
    WORKOUTS_HOOK_WINDOW,
    SELF_CARE_HOOK_WINDOW,
    WEEKLY_SUMMARY_HOOK_WINDOW,
    WORKOUTS_ANCHOR_DAY,
    SELF_CARE_ANCHOR_DAY,
    WEEKLY_SUMMARY_ANCHOR_DAY,
)
from models.profile import User, UserProfile, ToggleState
from parsing import parse_time_window

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hook scheduling helpers
# ---------------------------------------------------------------------------

def random_time_in_window(start_hour: int, end_hour: int) -> time:
    """Generate a random time within [start_hour, end_hour) range."""
    hour = random.randint(start_hour, end_hour - 1)
    minute = random.randint(0, 59)
    return time(hour, minute)


def should_piggyback(profile: User, toggle_name: str, now: datetime) -> bool:
    """Should this hook piggyback on the current interaction?

    True if the toggle is active and the hook hasn't fired today.
    """
    toggle: ToggleState = getattr(profile.toggles, toggle_name)
    if toggle.status != "active":
        return False
    if toggle.last_asked_at is None:
        return True
    # Check if last_asked_at was today (comparing dates)
    last_date = toggle.last_asked_at.date() if hasattr(toggle.last_asked_at, 'date') else None
    now_date = now.date() if hasattr(now, 'date') else None
    if last_date is None or now_date is None:
        return True
    return last_date < now_date


def get_hooks_to_schedule(profile: User) -> list[dict]:
    """Return list of hook descriptors for active toggles.

    Each descriptor: {toggle_name, schedule_type, window, anchor_day}
    """
    hooks = []
    toggle_configs = {
        "sleep": {
            "schedule_type": "daily",
            "window": SLEEP_HOOK_WINDOW,
        },
        "workouts": {
            "schedule_type": "weekly",
            "window": WORKOUTS_HOOK_WINDOW,
            "anchor_day": WORKOUTS_ANCHOR_DAY,
        },
        "self_care": {
            "schedule_type": "weekly",
            "window": SELF_CARE_HOOK_WINDOW,
            "anchor_day": SELF_CARE_ANCHOR_DAY,
        },
        "weekly_summary": {
            "schedule_type": "weekly",
            "window": WEEKLY_SUMMARY_HOOK_WINDOW,
            "anchor_day": WEEKLY_SUMMARY_ANCHOR_DAY,
        },
    }

    for toggle_name, config in toggle_configs.items():
        toggle: ToggleState = getattr(profile.toggles, toggle_name)
        if toggle.status == "active":
            hooks.append({"toggle_name": toggle_name, **config})

    return hooks


def schedule_global_hook_poller(job_queue, user_repo, toggle_service, goal_service=None):
    """Schedule a single global job that checks all users every 2 hours."""
    job_name = "global_hook_poller"
    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    job_queue.run_repeating(
        _global_hook_tick,
        interval=7200,
        first=10,
        name=job_name,
        data={
            "user_repo": user_repo,
            "toggle_service": toggle_service,
            "goal_service": goal_service,
        },
    )
    logger.info("Global hook poller scheduled (every 2 hours)")


async def _global_hook_tick(context):
    """Every 2 hours: check all users, fire any due hooks."""
    data = context.job.data
    user_repo = data["user_repo"]
    toggle_service = data["toggle_service"]
    goal_service = data.get("goal_service")

    all_users = user_repo.find({"telegram_user_id": {"$ne": None}})
    logger.info("Hook tick: checking %d users", len(all_users))

    for profile in all_users:
        if not profile.telegram_user_id:
            continue
        try:
            await _check_user_hooks(context, profile, user_repo, toggle_service, goal_service)
        except Exception:
            logger.exception("Hook tick failed for user %d", profile.telegram_user_id)


async def _check_user_hooks(context, profile, user_repo, toggle_service, goal_service=None):
    """Check and fire all due hooks for a single user."""
    import messages as M
    from constants import MAX_RECENT_MESSAGES

    tid = profile.telegram_user_id
    tz = pytz.timezone(profile.timezone)
    now = datetime.now(tz)
    today_weekday = now.weekday()

    # Check goal reminders first
    if goal_service:
        due = goal_service.check_goal_reminders(profile)
        if due:
            text = goal_service.fire_goal_reminder(tid, due[0])
            try:
                await context.bot.send_message(chat_id=tid, text=text)
                msg = {"role": "bot", "text": text[:500], "timestamp": datetime.now(timezone.utc).isoformat()}
                user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)
            except Exception:
                logger.exception("Failed to send goal reminder to user %d", tid)
            return  # One reminder per tick

    hooks = get_hooks_to_schedule(profile)

    for hook in hooks:
        toggle_name = hook["toggle_name"]
        schedule_type = hook["schedule_type"]
        start_hour, end_hour = hook["window"]

        # Check if we're within the time window
        if not (start_hour <= now.hour < end_hour):
            continue

        # For weekly hooks, check if today is the anchor day
        if schedule_type == "weekly":
            if today_weekday != hook["anchor_day"]:
                continue

        # Check if haven't already asked today
        if not should_piggyback(profile, toggle_name, now):
            continue

        # All conditions met - fire the hook
        prompt_pools = {
            "sleep": M.HOOK_SLEEP_PROMPTS,
            "workouts": M.HOOK_WORKOUTS_PROMPTS,
            "self_care": M.HOOK_SELF_CARE_PROMPTS,
        }

        if toggle_name == "weekly_summary":
            text = M.WEEKLY_SUMMARY_OFFER
        else:
            pool = prompt_pools.get(toggle_name, [])
            if not pool:
                continue
            text = random.choice(pool)

        # Check exit door
        if toggle_service.should_show_exit_door(profile, toggle_name):
            habit_names = {
                "sleep": "שינה", "eating_window": "חלון אכילה",
                "workouts": "אימונים", "self_care": "משהו לעצמי",
                "weekly_summary": "סיכום שבועי",
            }
            text += "\n\n" + M.EXIT_DOOR.format(habit=habit_names.get(toggle_name, ""))

        # Record + send
        toggle_service.record_asked(tid, toggle_name)
        toggle_service.increment_unanswered(tid, profile, toggle_name)

        try:
            await context.bot.send_message(chat_id=tid, text=text)
            msg = {"role": "bot", "text": text[:500], "timestamp": datetime.now(timezone.utc).isoformat()}
            user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)
        except Exception:
            logger.exception("Failed to send hook %s to user %d", toggle_name, tid)


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

    # Don't schedule if no eating window computed yet
    if not profile.eating_window:
        logger.info("No eating window for user %d, skipping window job scheduling", telegram_user_id)
        return

    tz_str = profile.timezone
    tz = pytz.timezone(tz_str)
    window_end = profile.eating_window.end
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
        from constants import MAX_RECENT_MESSAGES
        msg = {"role": "bot", "text": text[:500], "timestamp": datetime.now(timezone.utc).isoformat()}
        user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)
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
        from constants import MAX_RECENT_MESSAGES
        msg = {"role": "bot", "text": summary[:500], "timestamp": datetime.now(timezone.utc).isoformat()}
        user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)
    except Exception:
        logger.exception("Failed to send window close summary")
