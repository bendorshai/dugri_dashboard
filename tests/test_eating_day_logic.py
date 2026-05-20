"""
test_eating_day_logic — characterization tests for eating day behavior.

These tests document the exact behavior of eating-day filtering and stats-date
logic BEFORE the refactor. They must pass against both the old code and the new
EatingDayService to guarantee behavioral preservation.
"""

from datetime import datetime, timedelta

import pytest
import pytz

from parsing import is_within_eating_window


IL_TZ = pytz.timezone("Asia/Jerusalem")


# ---------------------------------------------------------------------------
# Pure eating-day filtering logic (extracted from sheets.py lines 168-180)
# ---------------------------------------------------------------------------

def filter_eating_day_entries(
    entries: list[dict],
    date_str: str,
    next_date_str: str,
    window_start_str: str,
) -> list[dict]:
    """Replicates sheets.py get_entries_for_eating_day filtering logic."""
    results = []
    for entry in entries:
        entry_date = entry.get("date", "")
        entry_time = entry.get("time", "")
        if entry_date == date_str:
            if not entry_time or entry_time >= window_start_str:
                results.append(entry)
        elif entry_date == next_date_str:
            if entry_time and entry_time < window_start_str:
                results.append(entry)
    return results


def get_stats_date(now: datetime, window_start: str, window_end: str) -> str:
    """Replicates handlers/base.py _get_stats_date logic."""
    if is_within_eating_window(now, window_start, window_end):
        return now.strftime("%d/%m/%Y")

    current_minutes = now.hour * 60 + now.minute
    start_h, start_m = int(window_start.split(":")[0]), int(window_start.split(":")[1])
    start_minutes = start_h * 60 + start_m

    if current_minutes < start_minutes:
        yesterday = now - timedelta(days=1)
        return yesterday.strftime("%d/%m/%Y")
    return now.strftime("%d/%m/%Y")


def compute_totals(entries: list[dict]) -> tuple[int, int]:
    """Replicates handlers/base.py _get_eating_day_totals summing logic."""
    total_cal = 0
    total_prot = 0
    for entry in entries:
        try:
            total_cal += int(entry.get("calories", 0) or 0)
        except (ValueError, TypeError):
            pass
        try:
            total_prot += int(entry.get("protein", 0) or 0)
        except (ValueError, TypeError):
            pass
    return total_cal, total_prot


# ---------------------------------------------------------------------------
# Characterization tests
# ---------------------------------------------------------------------------

class TestEatingDayFiltering:
    """Tests 1-3: eating day entry filtering boundary cases."""

    def test_entry_after_window_start_is_included(self):
        """Case 1: entry on date_str after window start -> included."""
        entries = [
            {"date": "05/05/2026", "time": "14:30", "calories": 500},
        ]
        result = filter_eating_day_entries(entries, "05/05/2026", "06/05/2026", "08:00")
        assert len(result) == 1
        assert result[0]["time"] == "14:30"

    def test_entry_before_window_start_is_excluded(self):
        """Case 2: entry on date_str before window start -> excluded (belongs to previous day)."""
        entries = [
            {"date": "05/05/2026", "time": "01:00", "calories": 300},
        ]
        result = filter_eating_day_entries(entries, "05/05/2026", "06/05/2026", "08:00")
        assert len(result) == 0

    def test_next_day_entry_before_window_start_is_included(self):
        """Case 3: entry on next_date_str before window start -> included (late night)."""
        entries = [
            {"date": "06/05/2026", "time": "02:00", "calories": 200},
        ]
        result = filter_eating_day_entries(entries, "05/05/2026", "06/05/2026", "08:00")
        assert len(result) == 1
        assert result[0]["time"] == "02:00"

    def test_next_day_entry_after_window_start_is_excluded(self):
        """Extra: entry on next_date_str after window start -> excluded (new day)."""
        entries = [
            {"date": "06/05/2026", "time": "09:00", "calories": 400},
        ]
        result = filter_eating_day_entries(entries, "05/05/2026", "06/05/2026", "08:00")
        assert len(result) == 0

    def test_entry_at_exact_window_start_is_included(self):
        """Edge: entry at exactly window start time -> included."""
        entries = [
            {"date": "05/05/2026", "time": "08:00", "calories": 100},
        ]
        result = filter_eating_day_entries(entries, "05/05/2026", "06/05/2026", "08:00")
        assert len(result) == 1

    def test_entry_with_empty_time_is_included(self):
        """Edge: entry with empty time string -> included (fallback behavior)."""
        entries = [
            {"date": "05/05/2026", "time": "", "calories": 100},
        ]
        result = filter_eating_day_entries(entries, "05/05/2026", "06/05/2026", "08:00")
        assert len(result) == 1


class TestGetStatsDate:
    """Tests 4-6: which date's stats to show based on current time."""

    def test_morning_before_window_returns_yesterday(self):
        """Case 4: before window opens -> show yesterday's stats."""
        now = IL_TZ.localize(datetime(2026, 5, 5, 6, 0))
        result = get_stats_date(now, "08:00", "20:00")
        assert result == "04/05/2026"

    def test_inside_window_returns_today(self):
        """Case 5: inside eating window -> show today's stats."""
        now = IL_TZ.localize(datetime(2026, 5, 5, 12, 0))
        result = get_stats_date(now, "08:00", "20:00")
        assert result == "05/05/2026"

    def test_evening_after_window_returns_today(self):
        """Case 6: after window closes (evening) -> show today's completed stats."""
        now = IL_TZ.localize(datetime(2026, 5, 5, 22, 0))
        result = get_stats_date(now, "08:00", "20:00")
        assert result == "05/05/2026"


class TestMidnightCrossingWindow:
    """Test 7: eating window that crosses midnight."""

    def test_within_midnight_crossing_window(self):
        now = IL_TZ.localize(datetime(2026, 5, 5, 23, 0))
        assert is_within_eating_window(now, "22:00", "02:00") is True

    def test_outside_midnight_crossing_window(self):
        now = IL_TZ.localize(datetime(2026, 5, 5, 3, 0))
        assert is_within_eating_window(now, "22:00", "02:00") is False

    def test_at_window_end_is_outside(self):
        now = IL_TZ.localize(datetime(2026, 5, 5, 2, 0))
        assert is_within_eating_window(now, "22:00", "02:00") is False


class TestTotalsComputation:
    """Test 8: totals computation handles edge cases."""

    def test_normal_totals(self):
        entries = [
            {"calories": 500, "protein": 30},
            {"calories": 300, "protein": 20},
        ]
        cal, prot = compute_totals(entries)
        assert cal == 800
        assert prot == 50

    def test_empty_string_values(self):
        entries = [
            {"calories": "", "protein": ""},
            {"calories": 500, "protein": 30},
        ]
        cal, prot = compute_totals(entries)
        assert cal == 500
        assert prot == 30

    def test_non_numeric_values(self):
        entries = [
            {"calories": "abc", "protein": None},
            {"calories": 500, "protein": 30},
        ]
        cal, prot = compute_totals(entries)
        assert cal == 500
        assert prot == 30

    def test_missing_fields(self):
        entries = [
            {},
            {"calories": 500, "protein": 30},
        ]
        cal, prot = compute_totals(entries)
        assert cal == 500
        assert prot == 30
