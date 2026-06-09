"""
eating_day_service.py - eating-day logic and auto-computed eating window.

An "eating day" is not a calendar day. It runs from window_start on day X
to window_start on day X+1. A meal at 02:00 belongs to the previous eating day.

The eating window is auto-computed from the user's recent food entries
(median first/last meal times over the past 7 days). When no window exists
yet, the fallback is 00:00-23:59 (full calendar day).

Depends on: repositories/food_repository, models/profile, parsing.
Used by: handlers, scheduler.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from models.food import FoodEntry
from models.profile import EatingWindow, UserProfile
from parsing import is_within_eating_window, get_user_now, israel_today
from repositories.food_repository import FoodRepository


def _round_time_down_30(time_str: str) -> str:
    """Round HH:MM down to nearest 30-minute mark (for window start)."""
    h, m = int(time_str[:2]), int(time_str[3:5])
    m = (m // 30) * 30
    return f"{h:02d}:{m:02d}"


def _round_time_up_30(time_str: str) -> str:
    """Round HH:MM up to nearest 30-minute mark (for window end)."""
    h, m = int(time_str[:2]), int(time_str[3:5])
    if m % 30 == 0:
        return f"{h:02d}:{m:02d}"
    m = ((m // 30) + 1) * 30
    if m >= 60:
        m = 0
        h = (h + 1) % 24
    return f"{h:02d}:{m:02d}"


class EatingDayService:
    def __init__(self, food_repo: FoodRepository):
        self._food_repo = food_repo

    # ------------------------------------------------------------------
    # Auto-computed eating window
    # ------------------------------------------------------------------

    def compute_eating_window(self, telegram_user_id: int) -> EatingWindow | None:
        """Compute eating window from last 7 days of food entries.

        Returns None if fewer than 2 days have meals (not enough data).
        Uses median of each day's first/last meal time, rounded to 30 min.
        """
        today = israel_today()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]
        entries = self._food_repo.get_by_user_and_dates(telegram_user_id, dates)
        if not entries:
            return None

        by_date: dict[str, list[str]] = {}
        for e in entries:
            if e.time:
                by_date.setdefault(e.date, []).append(e.time)

        if len(by_date) < 2:
            return None

        first_times: list[str] = []
        last_times: list[str] = []
        for times in by_date.values():
            s = sorted(times)
            first_times.append(s[0])
            last_times.append(s[-1])

        first_times.sort()
        last_times.sort()
        start = _round_time_down_30(first_times[len(first_times) // 2])
        end = _round_time_up_30(last_times[len(last_times) // 2])
        return EatingWindow(start=start, end=end)

    # ------------------------------------------------------------------
    # Eating day logic
    # ------------------------------------------------------------------

    def resolve_eating_day(self, profile: UserProfile, now: datetime) -> str:
        """Map a timestamp to its eating day (DD/MM/YYYY).

        The eating day starts at window_start. Any time before window_start
        belongs to the previous calendar day's eating day. A meal at 2am
        belongs to yesterday's eating day, not today's.

        Rules:
          - Inside the window   -> current calendar day's eating day.
          - After window close  -> same calendar day's eating day.
          - Before window open  -> PREVIOUS calendar day's eating day.
          - No window (fallback) -> calendar day (window = 00:00-23:59).

        This is the canonical interface for eating-day resolution. All code
        that needs "which eating day does this moment belong to?" MUST use
        this method.
        """
        window_start = profile.eating_window.start if profile.eating_window else "00:00"
        window_end = profile.eating_window.end if profile.eating_window else "23:59"

        if is_within_eating_window(now, window_start, window_end):
            return now.strftime("%d/%m/%Y")

        current_minutes = now.hour * 60 + now.minute
        start_h, start_m = int(window_start.split(":")[0]), int(window_start.split(":")[1])
        start_minutes = start_h * 60 + start_m

        if current_minutes < start_minutes:
            yesterday = now - timedelta(days=1)
            return yesterday.strftime("%d/%m/%Y")
        return now.strftime("%d/%m/%Y")

    def get_stats_date(self, profile: UserProfile, now: datetime) -> str:
        """Alias for resolve_eating_day. Kept for backward compatibility."""
        return self.resolve_eating_day(profile, now)

    def get_eating_day_entries(
        self, profile: UserProfile, date_str: str,
    ) -> list[FoodEntry]:
        """All entries for a logical eating day. Single source of truth."""
        day = datetime.strptime(date_str, "%d/%m/%Y").date()
        next_day_str = (day + timedelta(days=1)).strftime("%d/%m/%Y")
        window_start = profile.eating_window.start if profile.eating_window else "00:00"

        entries = self._food_repo.get_by_user_and_dates(
            profile.telegram_user_id, [date_str, next_day_str],
        )

        results = []
        for entry in entries:
            if entry.date == date_str:
                if not entry.time or entry.time >= window_start:
                    results.append(entry)
            elif entry.date == next_day_str:
                if entry.time and entry.time < window_start:
                    results.append(entry)
        return results

    def get_eating_day_totals(
        self, profile: UserProfile, date_str: str,
    ) -> tuple[int, int]:
        """Total calories and protein for a logical eating day."""
        entries = self.get_eating_day_entries(profile, date_str)
        total_cal = 0
        total_prot = 0
        for entry in entries:
            total_cal += entry.calories
            total_prot += entry.protein
        return total_cal, total_prot
