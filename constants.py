"""
constants.py — All numeric and timing parameters for Dugri.

Every magic number or timing constant lives here. Logic code reads from this
file — never hard-codes values. This makes tuning Dugri's cadence and
behavior a one-file change without touching logic.

Depends on: nothing.
Used by: scheduler, toggle_service, onboarding_service, handlers, feedback_service.
"""

# ---------------------------------------------------------------------------
# Lazy opt-in hook configuration
#
# Each toggle's full config in one place: schedule type, anchor day,
# time window, gate days, and special params.
#
# Anchor days use Python weekday: 0=Monday ... 6=Sunday
# Windows are (start_hour, end_hour) in user timezone
# ---------------------------------------------------------------------------

HOOK_CONFIG = {
    "sleep": {
        "schedule": "daily",
        "window": (8, 10),           # 08:00-10:00
        "gate_days": 1,              # reveal after day 1
    },
    "eating_window": {
        "schedule": "daily",         # window warning/close are daily
        "gate_days": 4,              # reveal after day 4
        "retry_days": 11,            # retry 11 days after reveal refusal
    },
    "workouts": {
        "schedule": "weekly",
        "anchor_day": 3,             # Thursday
        "window": (16, 20),          # 16:00-20:00
        "gate_days": 4,              # reveal after day 4
    },
    "self_care": {
        "schedule": "weekly",
        "anchor_day": 4,             # Friday
        "window": (10, 14),          # 10:00-14:00
        "gate_days": 4,              # reveal after day 4
    },
    "weekly_summary": {
        "schedule": "weekly",
        "anchor_day": 6,             # Sunday
        "window": (9, 11),           # 09:00-11:00
        "default_active": True,      # opt-out (born active)
        "min_days": 7,               # min food entry days before first offer
    },
    "target_data": {
        "gate_days": 0,              # offered after first meal
        "retry_day": 9,              # retry on day 9 if refused
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
TARGET_RETRY_DAY = HOOK_CONFIG["target_data"]["retry_day"]
EATING_WINDOW_RETRY_DAYS = HOOK_CONFIG["eating_window"]["retry_days"]
WEEKLY_SUMMARY_MIN_DAYS = HOOK_CONFIG["weekly_summary"]["min_days"]

# ---------------------------------------------------------------------------
# Other constants
# ---------------------------------------------------------------------------

DASHBOARD_INTRO_DAY = 16
"""Day number to show the dashboard introduction hook."""

EXIT_DOOR_UNANSWERED_THRESHOLD = 2
"""Consecutive unanswered hooks before showing the exit door message (once)."""

ROTATING_PROMPT_COUNT = 5
"""Number of rotating phrasings per hook type (defined in messages.py)."""

MAX_RECENT_MESSAGES = 8
"""Maximum recent messages stored per user for classifier context."""
