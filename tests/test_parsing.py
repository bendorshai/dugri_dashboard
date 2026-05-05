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
