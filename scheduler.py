"""
scheduler.py — single unified polling loop for all scheduled behaviors.

All proactive messages (hooks, eating window, goal reminders) run on one
28-minute polling loop. Each tick loads fresh user data from MongoDB, so
changes (resets, toggle cancellations) take effect immediately - no stale
in-memory jobs.

Depends on: repositories, services, constants, messages, parsing.
Used by: bot.py, handlers/base.py (should_piggyback only).
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

import pytz

from constants import (
    POLL_INTERVAL_SECONDS,
    EATING_WINDOW_WARN_MINUTES,
    SLEEP_HOOK_WINDOW,
    WORKOUTS_HOOK_WINDOW,
    SELF_CARE_HOOK_WINDOW,
    WEEKLY_SUMMARY_HOOK_WINDOW,
    WORKOUTS_ANCHOR_DAY,
    SELF_CARE_ANCHOR_DAY,
    WEEKLY_SUMMARY_ANCHOR_DAY,
    MAX_RECENT_MESSAGES,
)
from models.profile import User, ToggleState
from parsing import parse_time_window

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (used by both poller and piggyback hooks in handlers)
# ---------------------------------------------------------------------------

def should_piggyback(profile: User, toggle_name: str, now: datetime) -> bool:
    """Should this hook fire now? True if active and hasn't fired today."""
    toggle: ToggleState = getattr(profile.toggles, toggle_name)
    if toggle.status != "active":
        return False
    if toggle.last_asked_at is None:
        return True
    last_date = toggle.last_asked_at.date() if hasattr(toggle.last_asked_at, 'date') else None
    now_date = now.date() if hasattr(now, 'date') else None
    if last_date is None or now_date is None:
        return True
    return last_date < now_date


def get_hooks_to_schedule(profile: User) -> list[dict]:
    """Return list of hook descriptors for active toggles."""
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


# ---------------------------------------------------------------------------
# Global poller
# ---------------------------------------------------------------------------

def schedule_global_poller(
    job_queue, user_repo, toggle_service,
    goal_service=None, eating_day_service=None,
):
    """Schedule the single unified polling loop.

    Every POLL_INTERVAL_SECONDS (28 min), checks all users for:
    - Habit hook messages (sleep, workouts, self_care, weekly_summary)
    - Eating window warnings and close summaries
    - Goal reminders
    All data is read fresh from MongoDB each tick.
    """
    job_name = "global_poller"
    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    job_queue.run_repeating(
        _global_tick,
        interval=POLL_INTERVAL_SECONDS,
        first=10,
        name=job_name,
        data={
            "user_repo": user_repo,
            "toggle_service": toggle_service,
            "goal_service": goal_service,
            "eating_day_service": eating_day_service,
        },
    )
    logger.info(
        "Global poller scheduled (every %d seconds / %.1f minutes)",
        POLL_INTERVAL_SECONDS, POLL_INTERVAL_SECONDS / 60,
    )


async def _global_tick(context):
    """Single tick: check all users for any due scheduled messages."""
    data = context.job.data
    user_repo = data["user_repo"]
    toggle_service = data["toggle_service"]
    goal_service = data.get("goal_service")
    eating_day_svc = data.get("eating_day_service")

    all_users = user_repo.find({"telegram_user_id": {"$ne": None}})
    logger.info("Poller tick: checking %d users", len(all_users))

    for profile in all_users:
        if not profile.telegram_user_id:
            continue
        try:
            await _check_user_hooks(
                context, profile, user_repo, toggle_service,
                goal_service, eating_day_svc,
            )
        except Exception:
            logger.exception("Poller tick failed for user %d", profile.telegram_user_id)


# ---------------------------------------------------------------------------
# Per-user check (called each tick for each user)
# ---------------------------------------------------------------------------

async def _check_user_hooks(
    context, profile, user_repo, toggle_service,
    goal_service=None, eating_day_svc=None,
):
    """Check and fire all due messages for a single user."""
    import messages as M

    tid = profile.telegram_user_id
    tz = pytz.timezone(profile.timezone)
    now = datetime.now(tz)
    today_weekday = now.weekday()

    # --- Goal reminders (highest priority) ---
    if goal_service:
        due = goal_service.check_goal_reminders(profile)
        if due:
            text = goal_service.fire_goal_reminder(tid, due[0])
            await _send_and_save(context, tid, text, user_repo)
            return

    # --- Habit hooks (sleep, workouts, self_care, weekly_summary) ---
    hooks = get_hooks_to_schedule(profile)

    for hook in hooks:
        toggle_name = hook["toggle_name"]
        schedule_type = hook["schedule_type"]
        start_hour, end_hour = hook["window"]

        if not (start_hour <= now.hour < end_hour):
            continue

        if schedule_type == "weekly" and today_weekday != hook["anchor_day"]:
            continue

        if not should_piggyback(profile, toggle_name, now):
            continue

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

        if toggle_service.should_show_exit_door(profile, toggle_name):
            habit_names = {
                "sleep": "שינה", "eating_window": "חלון אכילה",
                "workouts": "אימונים", "self_care": "משהו לעצמי",
                "weekly_summary": "סיכום שבועי",
            }
            text += "\n\n" + M.EXIT_DOOR.format(habit=habit_names.get(toggle_name, ""))

        toggle_service.record_asked(tid, toggle_name)
        toggle_service.increment_unanswered(tid, profile, toggle_name)
        await _send_and_save(context, tid, text, user_repo)

    # --- Eating window: "closing soon" warning ---
    await _check_eating_window(context, profile, user_repo, toggle_service, eating_day_svc, now)


async def _check_eating_window(context, profile, user_repo, toggle_service, eating_day_svc, now):
    """Check if eating window is closing soon or has closed. Send once per day."""
    import messages as M

    if profile.toggles.eating_window.status != "active":
        return
    if not profile.eating_window:
        return

    tid = profile.telegram_user_id
    toggle = profile.toggles.eating_window

    end_h, end_m = parse_time_window(profile.eating_window.end)
    close_minutes = end_h * 60 + end_m
    now_minutes = now.hour * 60 + now.minute
    minutes_until_close = close_minutes - now_minutes

    # Already sent today? Check via last_asked_at
    already_warned = False
    if toggle.last_asked_at:
        last_date = toggle.last_asked_at.date() if hasattr(toggle.last_asked_at, 'date') else None
        if last_date == now.date():
            already_warned = True

    if already_warned:
        return

    # Window closing soon (within EATING_WINDOW_WARN_MINUTES, but still open)
    if 0 < minutes_until_close <= EATING_WINDOW_WARN_MINUTES:
        stats = _build_eating_stats(profile, eating_day_svc, now)
        text = random.choice(M.EATING_WINDOW_CLOSING_SOON).format(stats=stats)
        toggle_service.record_asked(tid, "eating_window")
        await _send_and_save(context, tid, text, user_repo)
        return

    # Window just closed (within one poll interval after close)
    if -EATING_WINDOW_WARN_MINUTES <= minutes_until_close <= 0:
        stats = _build_eating_close_summary(profile, eating_day_svc, now)
        text = f"🌙 חלון האכילה נסגר! סיכום יומי:\n\n{stats}"
        toggle_service.record_asked(tid, "eating_window")
        await _send_and_save(context, tid, text, user_repo)


def _build_eating_stats(profile, eating_day_svc, now) -> str:
    """Build stats string for eating window warning."""
    if not eating_day_svc:
        return ""

    from parsing import get_user_now
    today_str = get_user_now(profile.timezone).strftime("%d/%m/%Y")
    total_cal, total_prot = eating_day_svc.get_eating_day_totals(profile, today_str)

    # Read targets from nutrition goal_value or fallback
    nv = profile.toggles.nutrition.goal_value
    target_cal = (nv or {}).get("calories") or profile.targets.calories or 2000
    target_prot = (nv or {}).get("protein") or profile.targets.protein or 150

    remaining_cal = target_cal - total_cal
    remaining_prot = target_prot - total_prot
    cal_pct = round(total_cal / target_cal * 100) if target_cal else 0
    prot_pct = round(total_prot / target_prot * 100) if target_prot else 0
    prot_status = f"נותרו {remaining_prot}" if remaining_prot > 0 else "✅ הגעת ליעד!"

    return (
        f"קלוריות: {total_cal}/{target_cal} ({cal_pct}%, נותרו: {remaining_cal})\n"
        f"גרם חלבון: {total_prot}/{target_prot} ({prot_pct}%, {prot_status})"
    )


def _build_eating_close_summary(profile, eating_day_svc, now) -> str:
    """Build close summary string."""
    if not eating_day_svc:
        return ""

    from parsing import get_user_now
    today_str = get_user_now(profile.timezone).strftime("%d/%m/%Y")
    total_cal, total_prot = eating_day_svc.get_eating_day_totals(profile, today_str)

    nv = profile.toggles.nutrition.goal_value
    target_cal = (nv or {}).get("calories") or profile.targets.calories or 2000
    target_prot = (nv or {}).get("protein") or profile.targets.protein or 150

    cal_delta = total_cal - target_cal
    prot_delta = total_prot - target_prot
    cal_icon = "✅" if cal_delta <= 0 else "⚠️"
    prot_icon = "✅" if prot_delta >= 0 else "⚠️"
    cal_pct = round(total_cal / target_cal * 100) if target_cal else 0
    prot_pct = round(total_prot / target_prot * 100) if target_prot else 0
    cal_text = f"{abs(cal_delta)} מתחת ליעד" if cal_delta <= 0 else f"{cal_delta} מעל היעד"
    prot_text = f"{prot_delta} מעל היעד" if prot_delta >= 0 else f"{abs(prot_delta)} מתחת ליעד"

    return (
        f"{cal_icon} קלוריות: {total_cal}/{target_cal} ({cal_pct}%, {cal_text})\n"
        f"{prot_icon} גרם חלבון: {total_prot}/{target_prot} ({prot_pct}%, {prot_text})"
    )


# ---------------------------------------------------------------------------
# Send helper (shared by all scheduled messages)
# ---------------------------------------------------------------------------

async def _send_and_save(context, tid: int, text: str, user_repo) -> None:
    """Send a message and save to conversation history."""
    try:
        await context.bot.send_message(chat_id=tid, text=text)
        msg = {
            "role": "bot",
            "text": text[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)
    except Exception:
        logger.exception("Failed to send scheduled message to user %d", tid)
