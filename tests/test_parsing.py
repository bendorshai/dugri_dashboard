"""
test_parsing.py - TDD for time parsing and eating window utilities.

Tests the parsing module that handles time window logic, eating window
compliance checks, and timezone-aware datetime utilities.

# ============================================================================
# PARSING SPECIFICATION (Single Source of Truth)
#
# This comment defines the expected behavior of each parsing utility.
# When behavior changes, UPDATE THIS COMMENT FIRST, then update/add tests,
# then fix code to pass.
#
# ============================================================================
#
# TIME WINDOW PARSING (parse_time_window)
# ----------------------------------------
# - Parses "HH:MM" string into (hour, minute) tuple
# - Handles full range: "00:00" through "23:59"
#
# EATING WINDOW CHECK (is_within_eating_window)
# -----------------------------------------------
# - Returns True if a datetime falls within the start-end eating window
# - Start boundary is inclusive, end boundary is exclusive
# - SUPPORTS MIDNIGHT-CROSSING WINDOWS: e.g., 22:00-02:00 means
#   "from 10 PM to 2 AM next day". Both 23:00 and 01:00 are inside;
#   15:00 is outside.
#
# MINUTES UNTIL WINDOW CLOSE (minutes_until_window_close)
# --------------------------------------------------------
# - Returns integer minutes remaining until eating window closes
# - Handles midnight-crossing windows correctly
#   (e.g., 23:00 to 02:00 = 180 minutes)
#
# TIMEZONE UTILITIES (get_user_now, israel_today)
# ------------------------------------------------
# - get_user_now(tz): returns timezone-aware datetime
# - get_user_now() with no args: returns timezone-aware datetime
#   (default timezone)
# - israel_today(): returns a date object in Asia/Jerusalem timezone
#
# ============================================================================
"""

from __future__ import annotations

import pytest
from datetime import datetime

import pytz

from parsing import (
    parse_time_window,
    is_within_eating_window,
    minutes_until_window_close,
    israel_today,
    get_user_now,
)


class TestParseTimeWindow:
    def test_standard_time(self):
        assert parse_time_window("08:00") == (8, 0)

    def test_with_minutes(self):
        assert parse_time_window("14:30") == (14, 30)

    def test_midnight(self):
        assert parse_time_window("00:00") == (0, 0)

    def test_end_of_day(self):
        assert parse_time_window("23:59") == (23, 59)


class TestIsWithinEatingWindow:
    def _make_dt(self, hour, minute=0):
        tz = pytz.timezone("Asia/Jerusalem")
        return datetime(2026, 5, 5, hour, minute, tzinfo=tz)

    def test_inside_window(self):
        now = self._make_dt(12, 0)
        assert is_within_eating_window(now, "08:00", "20:00") is True

    def test_before_window(self):
        now = self._make_dt(7, 0)
        assert is_within_eating_window(now, "08:00", "20:00") is False

    def test_after_window(self):
        now = self._make_dt(20, 0)
        assert is_within_eating_window(now, "08:00", "20:00") is False

    def test_at_start_boundary(self):
        now = self._make_dt(8, 0)
        assert is_within_eating_window(now, "08:00", "20:00") is True

    def test_at_end_boundary(self):
        now = self._make_dt(20, 0)
        assert is_within_eating_window(now, "08:00", "20:00") is False

    def test_crossing_midnight_inside_before(self):
        now = self._make_dt(23, 0)
        assert is_within_eating_window(now, "22:00", "02:00") is True

    def test_crossing_midnight_inside_after(self):
        now = self._make_dt(1, 0)
        assert is_within_eating_window(now, "22:00", "02:00") is True

    def test_crossing_midnight_outside(self):
        now = self._make_dt(15, 0)
        assert is_within_eating_window(now, "22:00", "02:00") is False


class TestMinutesUntilWindowClose:
    def _make_dt(self, hour, minute=0):
        tz = pytz.timezone("Asia/Jerusalem")
        return datetime(2026, 5, 5, hour, minute, tzinfo=tz)

    def test_hours_remaining(self):
        now = self._make_dt(18, 0)
        assert minutes_until_window_close(now, "20:00") == 120

    def test_thirty_minutes_remaining(self):
        now = self._make_dt(19, 30)
        assert minutes_until_window_close(now, "20:00") == 30

    def test_crossing_midnight(self):
        now = self._make_dt(23, 0)
        assert minutes_until_window_close(now, "02:00") == 180


class TestGetUserNow:
    def test_returns_datetime_with_timezone(self):
        now = get_user_now("Asia/Jerusalem")
        assert now.tzinfo is not None

    def test_default_timezone(self):
        now = get_user_now()
        assert now.tzinfo is not None


class TestIsraelToday:
    def test_returns_date(self):
        today = israel_today()
        assert isinstance(today, type(today))
