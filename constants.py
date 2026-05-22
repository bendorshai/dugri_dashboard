"""
constants.py — All numeric and timing parameters for Dugri.

Every magic number or timing constant lives here. Logic code reads from this
file — never hard-codes values. This makes tuning Dugri's cadence and
behavior a one-file change without touching logic.

Depends on: nothing.
Used by: scheduler, toggle_service, onboarding_service, handlers, feedback_service.
"""

# ---------------------------------------------------------------------------
# Gate & retry days
# ---------------------------------------------------------------------------

TOGGLE_GATE_DAYS = 4
"""Minimum days since signup before revealing opt-in toggles (workouts, self-care, eating window)."""

TARGET_RETRY_DAY = 9
"""Day number to retry target offer if refused at moment 1."""

EATING_WINDOW_RETRY_DAYS = 11
"""Days after eating window refusal to retry the offer once."""

DASHBOARD_INTRO_DAY = 16
"""Day number to show the dashboard introduction hook."""

WEEKLY_SUMMARY_MIN_DAYS = 7
"""Minimum days of food entries before first weekly summary offer."""

# ---------------------------------------------------------------------------
# Anchor days (Python weekday: 0=Monday … 6=Sunday)
# ---------------------------------------------------------------------------

WORKOUTS_ANCHOR_DAY = 3       # Thursday
SELF_CARE_ANCHOR_DAY = 4      # Friday
WEEKLY_SUMMARY_ANCHOR_DAY = 6  # Sunday

# ---------------------------------------------------------------------------
# Random time windows — (start_hour, end_hour) in user timezone
# ---------------------------------------------------------------------------

SLEEP_HOOK_WINDOW = (8, 10)            # 08:00–10:00
EATING_WINDOW_HOOK_WINDOW = (18, 22)   # 18:00–22:00
WORKOUTS_HOOK_WINDOW = (16, 20)        # 16:00–20:00
SELF_CARE_HOOK_WINDOW = (10, 14)       # 10:00–14:00
WEEKLY_SUMMARY_HOOK_WINDOW = (9, 11)   # 09:00–11:00

# ---------------------------------------------------------------------------
# Exit door
# ---------------------------------------------------------------------------

EXIT_DOOR_UNANSWERED_THRESHOLD = 2
"""Consecutive unanswered hooks before showing the exit door message (once)."""

# ---------------------------------------------------------------------------
# Rotating prompts
# ---------------------------------------------------------------------------

ROTATING_PROMPT_COUNT = 5
"""Number of rotating phrasings per hook type (defined in messages.py)."""
