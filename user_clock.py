"""
user_clock.py - Timezone-safe clock for per-user date/time comparisons.

Structural enforcement: all comparisons between UTC timestamps (e.g.
last_asked_at from MongoDB) and the user's local calendar go through
UserClock methods. This makes timezone-incorrect .date() comparisons
structurally impossible.

Depends on: pytz.
Used by: scheduler.py, handlers/base.py.
"""

from __future__ import annotations

from datetime import datetime, date, timezone

import pytz


class UserClock:
    """Timezone-safe clock for a single user.

    Snapshot-based: ``now`` is captured once at construction, so all
    comparisons within a single scheduler tick use the same instant.
    """

    def __init__(self, timezone_str: str, _now_override: datetime | None = None):
        self._tz = pytz.timezone(timezone_str)
        if _now_override is not None:
            self._now = _now_override.astimezone(self._tz)
        else:
            self._now = datetime.now(self._tz)

    def now(self) -> datetime:
        """Current time in user's local timezone (aware)."""
        return self._now

    def today(self) -> date:
        """Today's date in user's local timezone."""
        return self._now.date()

    def weekday(self) -> int:
        """Day of week (0=Monday) in user's local timezone."""
        return self._now.weekday()

    def to_local(self, utc_dt: datetime) -> datetime:
        """Convert a UTC datetime to user's local timezone.

        Treats naive datetimes as UTC.
        """
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        return utc_dt.astimezone(self._tz)

    def local_date(self, utc_dt: datetime) -> date:
        """Extract the user-local date from a UTC datetime."""
        return self.to_local(utc_dt).date()

    def is_same_local_day(self, utc_dt: datetime) -> bool:
        """True if utc_dt falls on the same local calendar day as now."""
        return self.local_date(utc_dt) == self.today()

    def is_before_today(self, utc_dt: datetime) -> bool:
        """True if utc_dt's local date is strictly before today."""
        return self.local_date(utc_dt) < self.today()


def clock_for(profile) -> UserClock:
    """Create a UserClock from a user profile."""
    return UserClock(profile.timezone)
