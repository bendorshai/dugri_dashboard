"""
constants.py — All numeric and timing parameters for Dugri.

Every magic number or timing constant lives here. Logic code reads from this
file — never hard-codes values. This makes tuning Dugri's cadence and
behavior a one-file change without touching logic.

Depends on: nothing.
Used by: scheduler, toggle_service, goal_service, onboarding_service, handlers, feedback_service.
"""

# ---------------------------------------------------------------------------
# Lazy opt-in hook configuration
#
# Each toggle's full config in one place: schedule type, anchor day,
# time window, gate days, goal settings, and special params.
#
# Anchor days use Python weekday: 0=Monday ... 6=Sunday
# Windows are (start_hour, end_hour) in user timezone
# ---------------------------------------------------------------------------

HOOK_CONFIG = {
    "sleep": {
        "schedule": "daily",
        "window": (8, 10),           # 08:00-10:00
        "gate_days": 1,              # reveal after day 1
        "has_goal": True,
        "goal_reminder_days": 10,
    },
    "eating_window": {
        "schedule": "daily",         # window warning/close are daily
        "gate_days": 4,              # reveal after day 4
        "has_goal": True,
        "goal_reminder_days": 10,
    },
    "workouts": {
        "schedule": "weekly",
        "anchor_day": 3,             # Thursday
        "window": (16, 20),          # 16:00-20:00
        "gate_days": 4,              # reveal after day 4
        "has_goal": True,
        "goal_reminder_days": 10,
    },
    "self_care": {
        "schedule": "weekly",
        "anchor_day": 4,             # Friday
        "window": (10, 14),          # 10:00-14:00
        "gate_days": 4,              # reveal after day 4
        "has_goal": False,
    },
    "nutrition": {
        "gate_days": 0,              # offered after first meal
        "has_goal": True,
        "goal_reminder_days": 10,
    },
    "weekly_summary": {
        "schedule": "weekly",
        "anchor_day": 6,             # Sunday
        "window": (9, 11),           # 09:00-11:00
        "default_active": True,      # opt-out (born active)
        "min_days": 7,               # min food entry days before first offer
        "has_goal": False,
    },
}

# ---------------------------------------------------------------------------
# Backward-compatible aliases (derived from HOOK_CONFIG)
# Existing code imports these — do not remove.
# ---------------------------------------------------------------------------

WORKOUTS_ANCHOR_DAY = HOOK_CONFIG["workouts"]["anchor_day"]
SELF_CARE_ANCHOR_DAY = HOOK_CONFIG["self_care"]["anchor_day"]
WEEKLY_SUMMARY_ANCHOR_DAY = HOOK_CONFIG["weekly_summary"]["anchor_day"]

SLEEP_HOOK_WINDOW = HOOK_CONFIG["sleep"]["window"]
WORKOUTS_HOOK_WINDOW = HOOK_CONFIG["workouts"]["window"]
SELF_CARE_HOOK_WINDOW = HOOK_CONFIG["self_care"]["window"]
WEEKLY_SUMMARY_HOOK_WINDOW = HOOK_CONFIG["weekly_summary"]["window"]

TOGGLE_GATE_DAYS = HOOK_CONFIG["workouts"]["gate_days"]
WEEKLY_SUMMARY_MIN_DAYS = HOOK_CONFIG["weekly_summary"]["min_days"]

DEFAULT_GOAL_REMINDER_DAYS = 10
"""Default days before re-asking about a declined goal."""

# ---------------------------------------------------------------------------
# Global polling interval
#
# All scheduled checks (hooks, eating window, goal reminders) run on a single
# polling loop. 28 minutes chosen deliberately:
# - Frequent enough for eating window precision (~30 min accuracy)
# - Infrequent enough to avoid DB spam
# - Slightly irregular to make Dugri's timing feel natural, not robotic
# ---------------------------------------------------------------------------

POLL_INTERVAL_SECONDS = 28 * 60  # 28 minutes

EATING_WINDOW_WARN_MINUTES = 60
"""Send 'closing soon' when window closes within this many minutes. Once per day."""

# ---------------------------------------------------------------------------
# Other constants
# ---------------------------------------------------------------------------

DASHBOARD_INTRO_DAY = 16
"""Day number to show the dashboard introduction hook."""

EXIT_DOOR_UNANSWERED_THRESHOLD = 2
"""Consecutive unanswered hooks before showing the exit door message (once)."""

ROTATING_PROMPT_COUNT = 5
"""Number of rotating phrasings per hook type (defined in messages.py)."""

MAX_RECENT_MESSAGES = 12
"""Maximum recent messages stored per user for classifier context."""

INLINE_HOOK_DELAY_SECONDS = 5
"""Seconds to wait before sending an inline hook after a meal response.
Makes the bot feel less robotic - like it's thinking before bringing up a new topic."""

FOOD_NUDGE_WINDOW = (8, 10)
"""Morning window for food nudge messages (same as sleep)."""

RE_ENGAGEMENT_WINDOW = (8, 10)
"""Morning window for silence pipeline messages."""

SILENCE_ENTRY_HOURS = 48
"""Elapsed hours of silence before entering silence pipeline (day 1)."""

SILENCE_DAY2_HOURS = 72
"""Elapsed hours of silence before day 2 (GPT smart question)."""

SILENCE_DAY3_HOURS = 96
"""Elapsed hours of silence before day 3 (GPT context message)."""

SILENCE_PERMANENT_HOURS = 120
"""Elapsed hours of silence before permanent silencing."""

# ---------------------------------------------------------------------------
# Wisdom gems
# ---------------------------------------------------------------------------

GEM_GATE_DAYS = 14
"""Minimum days since trial start before gems activate."""

GEM_SILENT_WEEK_RATE = 0.10
"""Probability of a silent week (~10%). Silent weeks = no gems."""

GEM_FIRE_PROBABILITY = 0.85
"""Base probability of firing when pattern is above threshold."""

GEM_THRESHOLD_LIKE_DELTA = -0.01
"""Threshold adjustment on like (1% easier)."""

GEM_THRESHOLD_DISLIKE_DELTA = 0.10
"""Threshold adjustment on dislike (10% harder)."""

GEM_THRESHOLD_FLOOR = -0.15
"""Minimum threshold adjustment (even many likes won't go below this)."""

GEM_THRESHOLD_CEILING = 0.30
"""Maximum threshold adjustment (even many dislikes won't go above this)."""

GEM_FLOOR_OF_WEEK_DAY = 4
"""Gem-week day (0=Sun) from which floor-of-week general gems can fire."""

# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------

DEBUG_MODE = True
"""When True, every bot message to the admin includes a debug metadata button."""
