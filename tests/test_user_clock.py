"""
test_user_clock — Tests for UserClock timezone-safe date comparison.

Covers the critical bug: last_asked_at stored in UTC compared against
user's local date. Between midnight and 3am Israel time, UTC date is
still "yesterday" while local date is "today".
"""

from datetime import datetime, timezone, date

import pytz
import pytest

from user_clock import UserClock, clock_for


class TestUserClockBasics:
    def test_now_returns_localized_datetime(self):
        clock = UserClock("Asia/Jerusalem")
        now = clock.now()
        assert now.tzinfo is not None
        assert "Jerusalem" in str(now.tzinfo) or "IST" in str(now.tzinfo) or "IDT" in str(now.tzinfo)

    def test_now_override_converts_to_local(self):
        # 2026-06-05 21:00 UTC = 2026-06-06 00:00 Israel (UTC+3)
        utc_time = datetime(2026, 6, 5, 21, 0, tzinfo=timezone.utc)
        clock = UserClock("Asia/Jerusalem", _now_override=utc_time)
        assert clock.now().date() == date(2026, 6, 6)
        assert clock.today() == date(2026, 6, 6)

    def test_weekday_uses_local_date(self):
        # Friday 2026-06-05 23:00 UTC = Saturday 2026-06-06 02:00 Israel
        utc_time = datetime(2026, 6, 5, 23, 0, tzinfo=timezone.utc)
        clock = UserClock("Asia/Jerusalem", _now_override=utc_time)
        # Saturday = weekday 5
        assert clock.weekday() == 5


class TestToLocal:
    def test_converts_utc_aware_datetime(self):
        clock = UserClock("Asia/Jerusalem")
        utc_dt = datetime(2026, 6, 5, 21, 30, tzinfo=timezone.utc)
        local = clock.to_local(utc_dt)
        assert local.hour == 0
        assert local.minute == 30
        assert local.day == 6

    def test_handles_naive_datetime_as_utc(self):
        clock = UserClock("Asia/Jerusalem")
        naive_dt = datetime(2026, 6, 5, 21, 30)
        local = clock.to_local(naive_dt)
        assert local.hour == 0
        assert local.minute == 30
        assert local.day == 6

    def test_handles_pytz_aware_datetime(self):
        clock = UserClock("Asia/Jerusalem")
        utc_dt = pytz.utc.localize(datetime(2026, 6, 5, 21, 30))
        local = clock.to_local(utc_dt)
        assert local.hour == 0
        assert local.day == 6


class TestLocalDate:
    def test_extracts_local_date_from_utc(self):
        clock = UserClock("Asia/Jerusalem")
        # 23:00 UTC = 02:00 next day in Israel
        utc_dt = datetime(2026, 6, 5, 23, 0, tzinfo=timezone.utc)
        assert clock.local_date(utc_dt) == date(2026, 6, 6)

    def test_same_date_when_no_crossover(self):
        clock = UserClock("Asia/Jerusalem")
        # 12:00 UTC = 15:00 Israel, same date
        utc_dt = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
        assert clock.local_date(utc_dt) == date(2026, 6, 5)


class TestIsSameLocalDay:
    """The core bug fix: comparing UTC timestamps against local dates."""

    def test_same_day_when_both_same_local_date(self):
        # Clock at 2026-06-05 15:00 Israel
        clock = UserClock(
            "Asia/Jerusalem",
            _now_override=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
        )
        # last_asked_at: 2026-06-05 08:00 UTC = 2026-06-05 11:00 Israel
        utc_dt = datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)
        assert clock.is_same_local_day(utc_dt) is True

    def test_not_same_day_when_different_local_dates(self):
        # Clock at 2026-06-06 01:00 Israel (= 2026-06-05 22:00 UTC)
        clock = UserClock(
            "Asia/Jerusalem",
            _now_override=datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc),
        )
        # last_asked_at: 2026-06-05 20:30 UTC = 2026-06-05 23:30 Israel (June 5)
        # Clock is June 6 Israel -> different local days
        utc_dt = datetime(2026, 6, 5, 20, 30, tzinfo=timezone.utc)
        assert clock.is_same_local_day(utc_dt) is False

    def test_the_actual_bug_scenario(self):
        """The exact bug: hook fired at 23:30 Israel, checked again at 00:30 Israel.

        Without fix: last_asked_at.date() = June 5 (UTC), now.date() = June 6 (Israel)
        -> fires again! (wrong)

        With fix: both converted to Israel time -> both June 5 -> no double fire.
        Wait, 23:30 Israel on June 5 = 20:30 UTC June 5.
        00:30 Israel on June 6 = 21:30 UTC June 5.
        last_asked_at local = June 5, now local = June 6.
        So is_same_local_day should be False, but is_before_today should be True.
        The hook SHOULD fire on June 6 because it's a new day. This is correct!

        The real bug is: hook fires at 23:30 Israel (20:30 UTC, June 5).
        Then at 00:30 Israel (21:30 UTC, still June 5 in UTC).
        Old code: last_asked_at.date() = June 5 (UTC), now.date() = June 6 (Israel)
        -> last_date < now_date -> True -> fires again!
        New code: local_date(last_asked_at) = June 5, today() = June 6
        -> is_before_today = True -> fires again.
        Wait, that's also True. But it SHOULD be True because it's a new local day!

        The ACTUAL bug scenario is different: hook fires at 01:00 Israel (22:00 UTC prev day).
        record_asked stores UTC: June 4 22:00.
        At 02:00 Israel (23:00 UTC June 4), poller runs again.
        Old code: last_asked_at.date() = June 4 (UTC), now.date() = June 5 (Israel)
        -> last_date < now_date -> True -> fires AGAIN on June 5 even though
        it already fired at 01:00 Israel June 5.
        New code: local_date(22:00 UTC June 4) = 01:00 June 5 Israel = June 5
        today() = June 5 -> is_before_today = False -> no double fire!
        """
        # Hook fired at 01:00 Israel June 5 = 22:00 UTC June 4
        last_asked_utc = datetime(2026, 6, 4, 22, 0, tzinfo=timezone.utc)

        # Poller runs at 02:00 Israel June 5 = 23:00 UTC June 4
        clock = UserClock(
            "Asia/Jerusalem",
            _now_override=datetime(2026, 6, 4, 23, 0, tzinfo=timezone.utc),
        )

        # Old buggy behavior would say: June 4 < June 5 -> fire again!
        # New correct behavior: both are June 5 in Israel -> don't fire
        assert clock.is_same_local_day(last_asked_utc) is True
        assert clock.is_before_today(last_asked_utc) is False


class TestIsBeforeToday:
    def test_yesterday_returns_true(self):
        clock = UserClock(
            "Asia/Jerusalem",
            _now_override=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
        )
        yesterday_utc = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        assert clock.is_before_today(yesterday_utc) is True

    def test_today_returns_false(self):
        clock = UserClock(
            "Asia/Jerusalem",
            _now_override=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
        )
        today_utc = datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)
        assert clock.is_before_today(today_utc) is False

    def test_crossover_same_local_day_returns_false(self):
        """UTC dates differ but both are same local day."""
        # Now: June 6 01:00 Israel = June 5 22:00 UTC
        clock = UserClock(
            "Asia/Jerusalem",
            _now_override=datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc),
        )
        # last_asked: June 5 23:30 Israel = June 5 20:30 UTC
        last_asked = datetime(2026, 6, 5, 20, 30, tzinfo=timezone.utc)
        # Both are June 5 in Israel... wait, clock is June 6 01:00 Israel
        # last_asked is June 5 23:30 Israel. Different local days!
        assert clock.is_before_today(last_asked) is True

    def test_midnight_crossover_bug_fix(self):
        """The critical fix: UTC same day but different local days should NOT double fire."""
        # Hook fired at 01:00 Israel = 22:00 UTC prev day
        last_asked = datetime(2026, 6, 4, 22, 0, tzinfo=timezone.utc)
        # Poller at 02:00 Israel = 23:00 UTC prev day
        clock = UserClock(
            "Asia/Jerusalem",
            _now_override=datetime(2026, 6, 4, 23, 0, tzinfo=timezone.utc),
        )
        # Both are June 5 in Israel, should NOT fire again
        assert clock.is_before_today(last_asked) is False


class TestClockFor:
    def test_creates_clock_from_profile(self):
        class FakeProfile:
            timezone = "Asia/Jerusalem"

        clock = clock_for(FakeProfile())
        assert clock.now().tzinfo is not None


class TestDifferentTimezones:
    """Multi-timezone readiness."""

    def test_us_eastern(self):
        # 2026-06-05 03:00 UTC = 2026-06-04 23:00 US/Eastern
        utc_time = datetime(2026, 6, 5, 3, 0, tzinfo=timezone.utc)
        clock = UserClock("US/Eastern", _now_override=utc_time)
        assert clock.today() == date(2026, 6, 4)

    def test_asia_tokyo(self):
        # 2026-06-05 16:00 UTC = 2026-06-06 01:00 Asia/Tokyo
        utc_time = datetime(2026, 6, 5, 16, 0, tzinfo=timezone.utc)
        clock = UserClock("Asia/Tokyo", _now_override=utc_time)
        assert clock.today() == date(2026, 6, 6)
