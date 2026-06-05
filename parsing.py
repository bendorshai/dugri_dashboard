from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytz

IL_TZ = pytz.timezone("Asia/Jerusalem")


def get_user_now(timezone_str: str = "Asia/Jerusalem") -> datetime:
    tz = pytz.timezone(timezone_str)
    return datetime.now(tz)


def israel_today() -> date:
    return datetime.now(IL_TZ).date()


def parse_time_window(window_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute)."""
    parts = window_str.strip().split(":")
    return int(parts[0]), int(parts[1])


def is_within_eating_window(
    now: datetime,
    window_start: str,
    window_end: str,
) -> bool:
    """Check if current time is within the eating window.

    Handles windows that cross midnight (e.g., start=22:00, end=02:00).
    """
    start_h, start_m = parse_time_window(window_start)
    end_h, end_m = parse_time_window(window_end)
    current = now.hour * 60 + now.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m

    if start <= end:
        return start <= current < end
    else:
        return current >= start or current < end


_HEBREW_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def hebrew_day_name(dt: datetime | date) -> str:
    """Return Hebrew day name. Monday=0 in Python's weekday()."""
    return _HEBREW_DAYS[dt.weekday()]


def minutes_until_window_close(now: datetime, window_end: str) -> int:
    """Calculate minutes until eating window closes."""
    end_h, end_m = parse_time_window(window_end)
    current = now.hour * 60 + now.minute
    end = end_h * 60 + end_m

    if end > current:
        return end - current
    else:
        return (24 * 60 - current) + end
