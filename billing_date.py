"""Monthly-anniversary billing date helper (no calendar drift).

Pure stdlib calendar math - no timezone, no clock, no I/O. Callers pass the
local (Asia/Jerusalem) date. See tests/test_billing_date.py for the spec.
"""

import calendar
from datetime import date


def next_bill_date(anchor_day: int, from_date: date) -> date:
    """Return the next monthly billing date strictly after ``from_date``.

    The target day is always re-derived from ``anchor_day`` (the day-of-month the
    user first subscribed on), so a 31st subscriber returns to the 31st every
    month a 31st exists - a short month (Feb -> 28/29, Apr -> 30) clamps that one
    bill to the last day but never permanently shifts the anchor.
    """
    if not 1 <= anchor_day <= 31:
        raise ValueError(f"anchor_day must be in 1..31, got {anchor_day}")

    year, month = from_date.year, from_date.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1

    days_in_month = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor_day, days_in_month))
