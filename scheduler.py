"""
scheduler.py - single unified polling loop for all scheduled behaviors.

All proactive messages (hooks, eating window, goal reminders) run on one
28-minute polling loop. Each tick loads fresh user data from MongoDB, so
changes (resets, toggle cancellations) take effect immediately - no stale
in-memory jobs.

Depends on: repositories, services, constants, messages, parsing.
Used by: bot.py, handlers/base.py (should_fire_inline only).
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from constants import (
    HOOK_CONFIG,
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
    TRIAL_EXPIRY_WINDOW_START,
    TRIAL_EXPIRY_WINDOW_END,
)
from models.profile import User, ToggleState
from parsing import parse_time_window
from services.re_engagement_service import SuppressionLevel
from user_clock import UserClock

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (used by both poller and inline hook hooks in handlers)
# ---------------------------------------------------------------------------

def should_fire_inline(profile: User, toggle_name: str, clock: UserClock) -> bool:
    """Should this hook fire now? True if active and hasn't fired today.

    Uses UserClock for timezone-safe date comparison: last_asked_at (stored
    in UTC) is converted to the user's local date before comparing.
    """
    toggle: ToggleState = getattr(profile.toggles, toggle_name)
    if toggle.status != "active":
        return False
    if toggle.last_asked_at is None:
        return True
    return clock.is_before_today(toggle.last_asked_at)


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
    hook_schedule_store=None,
    food_repo=None,
    re_engagement_service=None,
    gem_service=None,
    admin_chat_id: int = 0,
    trial_service=None,
    feedback_service=None,
    landing_page_url: str = "",
    analyzer=None,
    sleep_repo=None,
    workout_repo=None,
    self_care_repo=None,
):
    """Schedule the single unified polling loop.

    Every POLL_INTERVAL_SECONDS (28 min), checks all users for:
    - Habit hook messages (sleep, workouts, self_care, weekly_summary)
    - Eating window warnings and close summaries
    - Goal reminders
    - Re-engagement nudges (food nudge, silence pipeline)
    - Trial expiry proactive messages
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
            "hook_schedule_store": hook_schedule_store,
            "food_repo": food_repo,
            "re_engagement_service": re_engagement_service,
            "gem_service": gem_service,
            "admin_chat_id": admin_chat_id,
            "trial_service": trial_service,
            "feedback_service": feedback_service,
            "landing_page_url": landing_page_url,
            "analyzer": analyzer,
            "sleep_repo": sleep_repo,
            "workout_repo": workout_repo,
            "self_care_repo": self_care_repo,
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
    hook_schedule_store = data.get("hook_schedule_store")

    food_repo = data.get("food_repo")
    admin_chat_id = data.get("admin_chat_id", 0)
    if food_repo:
        try:
            cleaned = food_repo.cleanup_expired_edits()
            if cleaned:
                logger.info("Cleaned up edit history from %d expired entries", cleaned)
        except Exception:
            logger.exception("Edit history cleanup failed")

    all_users = user_repo.find({"telegram_user_id": {"$ne": None}})
    logger.info("Poller tick: checking %d users", len(all_users))

    trial_service = data.get("trial_service")
    feedback_service = data.get("feedback_service")
    gem_service = data.get("gem_service")
    landing_page_url = data.get("landing_page_url", "")
    analyzer = data.get("analyzer")
    sleep_repo = data.get("sleep_repo")
    workout_repo = data.get("workout_repo")
    self_care_repo = data.get("self_care_repo")

    for profile in all_users:
        if not profile.telegram_user_id:
            continue
        try:
            # Trial expiry proactive message (before regular hooks)
            if trial_service:
                await _check_trial_expiry_message(
                    context, profile, user_repo, toggle_service,
                    trial_service,
                    analyzer=analyzer,
                    gem_service=gem_service,
                    feedback_service=feedback_service,
                    admin_chat_id=admin_chat_id,
                    landing_page_url=landing_page_url,
                    food_repo=food_repo,
                    sleep_repo=sleep_repo,
                    workout_repo=workout_repo,
                    self_care_repo=self_care_repo,
                )
        except Exception:
            logger.exception("Trial expiry check failed for user %d", profile.telegram_user_id)
        try:
            await _check_user_hooks(
                context, profile, user_repo, toggle_service,
                goal_service, eating_day_svc, hook_schedule_store,
                admin_chat_id=admin_chat_id, food_repo=food_repo,
            )
        except Exception:
            logger.exception("Poller tick failed for user %d", profile.telegram_user_id)


# ---------------------------------------------------------------------------
# Trial expiry proactive message
# ---------------------------------------------------------------------------

def _in_trial_expiry_window(clock: UserClock) -> bool:
    """Check if current local time is within the trial expiry window."""
    local_now = clock.now()
    current = (local_now.hour, local_now.minute)
    return TRIAL_EXPIRY_WINDOW_START <= current < TRIAL_EXPIRY_WINDOW_END


def _compute_trial_stats(profile, food_repo, sleep_repo=None,
                         workout_repo=None, self_care_repo=None) -> dict:
    """Compute trial-period statistics for the expiry message.

    All averages are computed over active days only (days with at least one entry).
    """
    from services.feedback_service import FeedbackService

    tid = profile.telegram_user_id
    started = profile.trial_started_at
    now = datetime.now(timezone.utc)

    # Generate trial date range as DD/MM/YYYY strings
    start_date = started.date() if hasattr(started, 'date') else started
    end_date = now.date() if hasattr(now, 'date') else now
    trial_duration = (end_date - start_date).days + 1
    trial_dates = [
        (start_date + timedelta(days=i)).strftime("%d/%m/%Y")
        for i in range(trial_duration)
    ]
    trial_date_set = set(trial_dates)

    # --- Food stats ---
    avg_daily_calories = 0
    avg_daily_protein = 0
    active_food_days = 0

    if food_repo:
        food_entries = food_repo.get_by_user_and_dates(tid, trial_dates)
        by_date = defaultdict(lambda: {"calories": 0, "protein": 0})
        for e in food_entries:
            by_date[e.date]["calories"] += e.calories
            by_date[e.date]["protein"] += e.protein
        active_food_days = len(by_date)
        if active_food_days > 0:
            total_cal = sum(d["calories"] for d in by_date.values())
            total_prot = sum(d["protein"] for d in by_date.values())
            avg_daily_calories = round(total_cal / active_food_days)
            avg_daily_protein = round(total_prot / active_food_days)

    # --- Workout stats ---
    total_workouts = 0
    if workout_repo:
        all_workouts = workout_repo.get_recent(tid, limit=100)
        total_workouts = sum(1 for w in all_workouts if w.date in trial_date_set)

    # --- Sleep stats ---
    avg_sleep_time = None
    if sleep_repo:
        all_sleep = sleep_repo.get_recent(tid, limit=100)
        trial_sleep_times = [s.sleep_time for s in all_sleep if s.date in trial_date_set]
        if trial_sleep_times:
            avg_sleep_time = FeedbackService._avg_time(trial_sleep_times)

    # --- Self-care stats ---
    self_care_count = 0
    if self_care_repo:
        all_sc = self_care_repo.get_recent(tid, limit=100)
        self_care_count = sum(1 for sc in all_sc if sc.date in trial_date_set)

    return {
        "trial_duration_days": trial_duration,
        "active_food_days": active_food_days,
        "avg_daily_calories": avg_daily_calories,
        "avg_daily_protein": avg_daily_protein,
        "target_calories": profile.targets.calories,
        "target_protein": profile.targets.protein,
        "total_workouts": total_workouts,
        "target_workouts_per_week": profile.targets.workouts_per_week,
        "avg_sleep_time": avg_sleep_time,
        "target_sleep_time": profile.targets.sleep_time,
        "self_care_count": self_care_count,
    }


async def _check_trial_expiry_message(
    context, profile, user_repo, toggle_service,
    trial_service, analyzer=None,
    gem_service=None, feedback_service=None,
    admin_chat_id: int = 0, landing_page_url: str = "",
    food_repo=None, sleep_repo=None, workout_repo=None, self_care_repo=None,
    now_override=None,
):
    """Send a one-time celebratory message when trial expires (20:30-21:30 local)."""
    import messages as M
    from keyboards import make_trial_cta_keyboard

    if profile.subscription_status != "trial_active":
        return
    if getattr(profile, "trial_expiry_message_sent", False):
        return

    tid = profile.telegram_user_id
    clock = UserClock(profile.timezone, _now_override=now_override)

    # Only fire within the 20:30-21:30 local window
    if not _in_trial_expiry_window(clock):
        return

    # Expire the trial (flips status to trial_ended)
    just_expired = trial_service.check_and_expire(profile, clock.now())
    if not just_expired:
        return

    # Gather data for the LLM
    celebration_text = M.TRIAL_EXPIRY_CELEBRATION
    stats = _compute_trial_stats(
        profile, food_repo, sleep_repo, workout_repo, self_care_repo,
    )

    # Get raw gem text
    gem_raw_text = None
    if gem_service:
        try:
            gem_result = gem_service.select_best_gem(profile, clock)
            if gem_result:
                gem_raw_text = gem_result.raw_text
        except Exception:
            logger.exception("Failed to select gem for trial expiry (user %d)", tid)

    # Get weekly report
    weekly_report = None
    if feedback_service:
        try:
            today_str = clock.now().strftime("%d/%m/%Y")
            weekly_report = feedback_service.give_feedback(
                tid, today_str, profile, is_first_feedback=False,
            )
        except Exception:
            logger.exception("Failed to generate weekly report for trial expiry (user %d)", tid)

    # Single LLM call to compose the full message
    text = celebration_text  # fallback
    if analyzer:
        try:
            llm_text = analyzer.generate_trial_expiry_message(
                celebration_text=celebration_text,
                trial_stats=stats,
                gem_text=gem_raw_text,
                weekly_report=weekly_report,
                name=profile.name or "",
                gender=profile.gender or "male",
            )
            if llm_text:
                text = llm_text
        except Exception:
            logger.exception("Trial expiry LLM call failed (user %d), using fallback", tid)

    keyboard = make_trial_cta_keyboard(landing_page_url)

    await _send_and_save(
        context, tid, text, user_repo, profile, toggle_service,
        admin_chat_id, reply_markup=keyboard,
    )

    # Mark as sent so we never send twice
    user_repo.update_fields(tid, {"trial_expiry_message_sent": True})


# ---------------------------------------------------------------------------
# Per-user check (called each tick for each user)
# ---------------------------------------------------------------------------

async def _check_user_hooks(
    context, profile, user_repo, toggle_service,
    goal_service=None, eating_day_svc=None, hook_schedule_store=None,
    admin_chat_id: int = 0, food_repo=None, now_override=None,
):
    """Check and fire all due messages for a single user."""
    import messages as M

    tid = profile.telegram_user_id

    # Trial-ended users: skip all proactive hooks
    if profile.subscription_status == "trial_ended":
        return

    clock = UserClock(profile.timezone, _now_override=now_override)
    now = clock.now()
    today_weekday = clock.weekday()

    # --- Goal reminders (highest priority) ---
    if goal_service:
        due = goal_service.check_goal_reminders(profile)
        if due:
            text = goal_service.fire_goal_reminder(tid, due[0])
            await _send_and_save(context, tid, text, user_repo, profile, toggle_service, admin_chat_id)
            return

    # --- Re-engagement (before habit hooks) ---
    re_engagement_svc = context.job.data.get("re_engagement_service")
    suppression = SuppressionLevel.NONE
    if re_engagement_svc:
        suppression = re_engagement_svc.get_suppression_level(profile)

        if suppression == SuppressionLevel.TOTAL:
            return

        action = re_engagement_svc.check_re_engagement(profile, clock)
        if action:
            re_engagement_svc.transition_stage(tid, action.new_stage)
            if action.message:
                await _send_and_save(context, tid, action.message, user_repo, profile, toggle_service, admin_chat_id)
            return

        if suppression == SuppressionLevel.ALLOW_WEEKLY_ONLY:
            if should_fire_inline(profile, "weekly_summary", clock):
                text = M.WEEKLY_SUMMARY_OFFER
                toggle_service.record_asked(tid, "weekly_summary")
                toggle_service.increment_unanswered(tid, profile, "weekly_summary")
                await _send_and_save(context, tid, text, user_repo, profile, toggle_service, admin_chat_id)
            return

    # --- Habit hooks (sleep, workouts, self_care, weekly_summary) ---
    hooks = get_hooks_to_schedule(profile)

    for hook in hooks:
        toggle_name = hook["toggle_name"]
        schedule_type = hook["schedule_type"]
        window = hook["window"]

        # Food nudge blocks sleep hooks
        if toggle_name == "sleep" and suppression == SuppressionLevel.BLOCK_SLEEP:
            continue

        if schedule_type == "weekly" and today_weekday != hook["anchor_day"]:
            continue

        # Randomized timing: fire after the random time, not on window entry.
        # Falls back to window check if no hook_schedule_store is configured.
        if hook_schedule_store:
            fire_h, fire_m = hook_schedule_store.get_or_generate(
                toggle_name, window, schedule_type, now,
            )
            if (now.hour, now.minute) < (fire_h, fire_m):
                continue
        else:
            start_hour, end_hour = window
            if not (start_hour <= now.hour < end_hour):
                continue

        if not should_fire_inline(profile, toggle_name, clock):
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
            if toggle_name == "self_care":
                from services.hook_prompt_service import HookPromptService
                text = HookPromptService.pick_self_care_prompt(
                    profile.self_care_activities, pool,
                )
            else:
                text = random.choice(pool)

        if toggle_service.should_show_exit_door(profile, toggle_name):
            habit_names = {
                "sleep": "שינה", "eating_window": "חלון אכילה",
                "workouts": "אימונים", "self_care": "משהו לעצמי",
                "weekly_summary": "סיכום שבועי",
            }
            text += "\n\n" + random.choice(M.EXIT_DOOR_PROMPTS).format(
                habit=habit_names.get(toggle_name, "")
            )

        toggle_service.record_asked(tid, toggle_name)
        toggle_service.increment_unanswered(tid, profile, toggle_name)
        await _send_and_save(context, tid, text, user_repo, profile, toggle_service, admin_chat_id)

    # --- Eating window: "closing soon" warning ---
    await _check_eating_window(context, profile, user_repo, toggle_service, eating_day_svc, clock, admin_chat_id)

    # --- Proactive reveals (fallback for users who haven't logged food) ---
    if toggle_service:
        await _check_proactive_reveals(
            context, profile, user_repo, toggle_service, now, today_weekday,
            admin_chat_id=admin_chat_id, food_repo=food_repo,
        )

    # --- Wisdom gem (poller path) ---
    gem_service = context.job.data.get("gem_service")
    if gem_service:
        gem_result = gem_service.try_deliver_gem(profile, clock)
        if gem_result:
            from keyboards import make_gem_feedback_keyboard
            kb = make_gem_feedback_keyboard(gem_result.gem_id)
            await _send_and_save(context, tid, gem_result.dressed_text,
                                 user_repo, profile, toggle_service, admin_chat_id,
                                 reply_markup=kb)

    # --- Ghosting detection (goal flows that went unanswered) ---
    goal_service = context.job.data.get("goal_service")
    if goal_service:
        goal_service.check_ghosting(profile)


async def _check_proactive_reveals(
    context, profile, user_repo, toggle_service, now, weekday,
    admin_chat_id: int = 0, food_repo=None,
):
    """Proactive reveals: offer dormant habits via poller if not yet offered.

    This is the fallback for users who haven't logged food (inline hooks
    didn't fire). Checks gate days, anchor days, and time windows.

    NOTE: nutrition is excluded - it is strictly inline (after first food entry).
    Eating window requires at least 1 food entry in history.
    """
    import messages as M

    tid = profile.telegram_user_id

    reveal_checks = [
        ("sleep", toggle_service.should_reveal_sleep(profile), M.REVEAL_SLEEP, HOOK_CONFIG["sleep"].get("window")),
        ("eating_window", toggle_service.should_reveal_eating_window(profile), M.REVEAL_EATING_WINDOW, None),
        ("workouts", toggle_service.should_reveal_workouts(profile, weekday), M.REVEAL_WORKOUTS, HOOK_CONFIG["workouts"].get("window")),
        ("self_care", toggle_service.should_reveal_self_care(profile, weekday), M.REVEAL_SELF_CARE, HOOK_CONFIG["self_care"].get("window")),
    ]

    for name, should_reveal, reveal_msg, window in reveal_checks:
        if not should_reveal:
            continue
        # Check time window if the habit has one
        if window and not (window[0] <= now.hour < window[1]):
            continue
        # Eating window requires at least 1 food entry
        if name == "eating_window" and food_repo:
            if not food_repo.get_all_for_user(tid):
                continue
        # Reveal and offer (toggle state tells classifier what to do)
        toggle_service.reveal_toggle(tid, name)
        await _send_and_save(context, tid, reveal_msg, user_repo, profile, toggle_service, admin_chat_id)
        return  # One reveal per tick


async def _check_eating_window(context, profile, user_repo, toggle_service, eating_day_svc, clock, admin_chat_id=0):
    """Check if eating window is closing soon or has closed. Send once per day."""
    import messages as M

    if profile.toggles.eating_window.status != "active":
        return
    if not profile.eating_window:
        return

    tid = profile.telegram_user_id
    toggle = profile.toggles.eating_window
    now = clock.now()

    end_h, end_m = parse_time_window(profile.eating_window.end)
    close_minutes = end_h * 60 + end_m
    now_minutes = now.hour * 60 + now.minute
    minutes_until_close = close_minutes - now_minutes

    # Already sent today? Check via last_asked_at (timezone-safe)
    if toggle.last_asked_at and clock.is_same_local_day(toggle.last_asked_at):
        return

    # Window closing soon (within EATING_WINDOW_WARN_MINUTES, but still open)
    if 0 < minutes_until_close <= EATING_WINDOW_WARN_MINUTES:
        stats = _build_eating_stats(profile, eating_day_svc, clock)
        text = random.choice(M.EATING_WINDOW_CLOSING_SOON).format(stats=stats)
        toggle_service.record_asked(tid, "eating_window")
        await _send_and_save(context, tid, text, user_repo, profile, toggle_service, admin_chat_id)
        return

    # Window just closed (within one poll interval after close)
    if -EATING_WINDOW_WARN_MINUTES <= minutes_until_close <= 0:
        stats = _build_eating_close_summary(profile, eating_day_svc, clock)
        text = f"🌙 חלון האכילה נסגר! סיכום יומי:\n\n{stats}"
        toggle_service.record_asked(tid, "eating_window")
        await _send_and_save(context, tid, text, user_repo, profile, toggle_service, admin_chat_id)


def _build_eating_stats(profile, eating_day_svc, clock) -> str:
    """Build stats string for eating window warning."""
    if not eating_day_svc:
        return ""

    today_str = clock.today().strftime("%d/%m/%Y")
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


def _build_eating_close_summary(profile, eating_day_svc, clock) -> str:
    """Build close summary string."""
    if not eating_day_svc:
        return ""

    today_str = clock.today().strftime("%d/%m/%Y")
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

async def _send_and_save(context, tid: int, text: str, user_repo,
                         profile=None, toggle_service=None, admin_chat_id: int = 0,
                         reply_markup=None) -> None:
    """Send a message and save to conversation history."""
    try:
        msg = {
            "role": "bot",
            "text": text[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        user_repo.push_messages(tid, [msg], MAX_RECENT_MESSAGES)

        await context.bot.send_message(chat_id=tid, text=text, reply_markup=reply_markup)
    except Exception:
        logger.exception("Failed to send scheduled message to user %d", tid)
