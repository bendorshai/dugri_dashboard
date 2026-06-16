"""
messages.py - All Hebrew text that Dugri says.

Content is loaded from .txt files in content/messages/.
Edit the text files directly to change Dugri's voice without touching code.

Depends on: content/loader.py
Used by: handlers, services, scheduler.
"""

import logging
from pathlib import Path
from content.loader import load_content

import random
from datetime import datetime

_logger = logging.getLogger(__name__)
_ns = load_content(Path(__file__).parent / "content" / "messages", _logger)
globals().update(vars(_ns))


# ---------------------------------------------------------------------------
# Habit correction context
# ---------------------------------------------------------------------------

HABIT_TYPE_LABELS = {
    "sleep": "שינה",
    "workout": "אימון",
    "self_care": "משהו לעצמי",
}

_CORRECTION_PREFIXES = ["עידכנתי", "תיקנתי", "טיפלתי לך בזה"]

_HEBREW_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def _day_label(date_str: str) -> str:
    """Convert DD/MM/YYYY to Hebrew day name."""
    dt = datetime.strptime(date_str, "%d/%m/%Y")
    return _HEBREW_DAYS[dt.weekday()]


def build_habit_correction_msg(
    original_type: str,
    result,
    entry_date: str,
) -> str:
    """Build a contextual correction confirmation message.

    Returns a message like: ✅ עידכנתי מ-משהו לעצמי ל-אימון ביום שבת.
    """
    prefix = random.choice(_CORRECTION_PREFIXES)

    # Reclassification: type changed
    if result.reclassify_to and result.reclassify_to != original_type:
        from_label = HABIT_TYPE_LABELS.get(original_type, original_type)
        to_label = HABIT_TYPE_LABELS.get(result.reclassify_to, result.reclassify_to)
        effective_date = result.corrected_date or entry_date
        day = _day_label(effective_date) if effective_date else None
        if day:
            return f"✅ {prefix} מ-{from_label} ל-{to_label} ביום {day}."
        return f"✅ {prefix} מ-{from_label} ל-{to_label}."

    # Date move
    if result.corrected_date:
        day = _day_label(result.corrected_date)
        habit_label = HABIT_TYPE_LABELS.get(original_type, original_type)
        return f"✅ {prefix} - העברתי {habit_label} ליום {day}."

    # Sleep time change
    if original_type == "sleep" and result.corrected_time:
        return f"✅ {prefix} - שינה ל-{result.corrected_time}."

    # Note/description change
    if result.corrected_note:
        return f"✅ {prefix} - {result.corrected_note}."

    # Fallback
    return f"✅ {prefix}."
