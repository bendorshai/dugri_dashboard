"""
test_eating_day_window.py - Eating Day Window Specification
============================================================

This file is the authoritative specification for how Dugri defines an "eating day".

CORE CONCEPT: AN EATING DAY IS NOT A CALENDAR DAY.
---------------------------------------------------

A person who eats at midnight is finishing yesterday's eating, not starting
tomorrow's. The eating day starts when the eating window OPENS and ends when
it opens again the next calendar day.

    Eating day for June 8 (window 10:00-22:00):
    +-----------+---------------------------+-----------+
    |  June 8   |       June 8              |  June 9   |
    | 00:00     |  10:00          22:00     | 10:00     |
    | ...before |  === WINDOW OPEN ===      | ...next   |
    |  window   |  (inside window)          |  window   |
    |  opens    |         | after close --> |  opens    |
    +-----------+---------+-----------------+-----------+
    |<-- belongs to June 7's eating day     |
                |<-- belongs to June 8's eating day --->|

    Everything from window_start on day X to window_start on day X+1
    belongs to eating day X.

RULES:
------
1. Inside the eating window   -> current calendar day's eating day.
2. After window closes        -> same calendar day's eating day (day is done).
3. Before window opens        -> PREVIOUS calendar day's eating day.
4. No eating window (fallback) -> calendar day (window = 00:00-23:59).

WHY THIS MATTERS:
-----------------
- Food entries in MongoDB store the ACTUAL calendar date and time (real timestamp).
- All aggregation, summaries, and "how much did I eat today?" queries must go
  through the EatingDayService to resolve calendar timestamps to eating days.
- The GPT prompts receive the actual CALENDAR date (so "what day is today?" is
  correct), but daily summaries use the eating-day date.
- Without this abstraction, late-night entries leak to wrong days and daily
  totals become corrupted.

STORAGE vs QUERY:
-----------------
- STORAGE: FoodEntry.date = calendar date, FoodEntry.time = calendar time.
- QUERY:   EatingDayService.resolve_eating_day(timestamp) -> eating day string.
           EatingDayService.get_eating_day_entries(profile, eating_day) -> entries.
  The query fetches entries from TWO calendar dates (eating_day and next day)
  and filters by time relative to window_start.
"""

from datetime import datetime, timedelta

import pytest
import pytz

from models.food import FoodEntry
from models.profile import EatingWindow, UserProfile
from parsing import is_within_eating_window
from services.eating_day_service import EatingDayService


IL_TZ = pytz.timezone("Asia/Jerusalem")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(
    eating_window: EatingWindow | None = None,
    telegram_user_id: int = 123,
    timezone: str = "Asia/Jerusalem",
) -> UserProfile:
    """Build a minimal UserProfile for testing."""
    return UserProfile(
        email="test@example.com",
        telegram_user_id=telegram_user_id,
        eating_window=eating_window,
        timezone=timezone,
    )


def _make_entry(date: str, time: str, calories: int = 500, protein: int = 30) -> FoodEntry:
    """Build a FoodEntry with calendar date and time."""
    return FoodEntry(
        telegram_user_id=123,
        date=date,
        time=time,
        description="test food",
        calories=calories,
        protein=protein,
    )


def _il(year, month, day, hour, minute=0) -> datetime:
    """Create a timezone-aware datetime in Asia/Jerusalem."""
    return IL_TZ.localize(datetime(year, month, day, hour, minute))


# ===========================================================================
#
# PART 1: resolve_eating_day - mapping timestamps to eating days
#
# This is the canonical interface. Every place in the codebase that needs
# to know "which eating day does this moment belong to?" MUST call this.
#
# ===========================================================================


class TestResolveEatingDay:
    """resolve_eating_day(profile, timestamp) -> DD/MM/YYYY eating day string.

    Given a user's eating window and a timestamp, returns which eating day
    that timestamp belongs to.
    """

    def setup_method(self):
        self.svc = EatingDayService(food_repo=None)
        self.window_10_22 = EatingWindow(start="10:00", end="22:00")
        self.window_08_20 = EatingWindow(start="08:00", end="20:00")

    # --- Inside the window: belongs to current calendar day ---

    def test_inside_window_returns_current_day(self):
        """14:00 is inside 10:00-22:00 -> eating day = June 8."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 8, 14, 0))
        assert result == "08/06/2026"

    def test_at_window_start_returns_current_day(self):
        """Exactly 10:00 (window opens) -> new eating day starts -> June 9."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 10, 0))
        assert result == "09/06/2026"

    def test_one_minute_after_open_returns_current_day(self):
        """10:01 -> eating day = June 9."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 10, 1))
        assert result == "09/06/2026"

    # --- After window closes: still belongs to current calendar day ---

    def test_after_window_close_returns_current_day(self):
        """23:00 is after 22:00 close -> eating day = June 8 (window closed today)."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 8, 23, 0))
        assert result == "08/06/2026"

    def test_at_window_close_returns_current_day(self):
        """Exactly 22:00 (window closes) -> eating day = June 8."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 8, 22, 0))
        assert result == "08/06/2026"

    def test_one_minute_before_midnight_returns_current_day(self):
        """23:59 on June 8 -> eating day = June 8."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 8, 23, 59))
        assert result == "08/06/2026"

    # --- Before window opens: belongs to PREVIOUS calendar day ---
    # This is the key insight: eating at 2am "belongs" to yesterday.

    def test_before_window_opens_returns_previous_day(self):
        """02:00 on June 9 is before 10:00 open -> eating day = June 8."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 2, 0))
        assert result == "08/06/2026"

    def test_midnight_returns_previous_day(self):
        """00:00 on June 9 -> eating day = June 8."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 0, 0))
        assert result == "08/06/2026"

    def test_one_minute_before_window_open_returns_previous_day(self):
        """09:59 on June 9 -> eating day = June 8 (window opens at 10:00)."""
        profile = _make_profile(self.window_10_22)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 9, 59))
        assert result == "08/06/2026"

    # --- Different window times ---

    def test_early_window_08_20(self):
        """07:30 before 08:00 window -> previous day."""
        profile = _make_profile(self.window_08_20)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 7, 30))
        assert result == "08/06/2026"

    def test_inside_early_window(self):
        """12:00 inside 08:00-20:00 -> current day."""
        profile = _make_profile(self.window_08_20)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 12, 0))
        assert result == "09/06/2026"

    # --- No eating window: fallback to calendar days ---

    def test_no_window_always_returns_calendar_day(self):
        """Without a window, 02:00 on June 9 = June 9 (calendar day)."""
        profile = _make_profile(eating_window=None)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 2, 0))
        assert result == "09/06/2026"

    def test_no_window_midnight_returns_new_day(self):
        """Without a window, 00:00 on June 9 = June 9."""
        profile = _make_profile(eating_window=None)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 9, 0, 0))
        assert result == "09/06/2026"

    def test_no_window_evening_returns_current_day(self):
        """Without a window, 23:00 on June 8 = June 8."""
        profile = _make_profile(eating_window=None)
        result = self.svc.resolve_eating_day(profile, _il(2026, 6, 8, 23, 0))
        assert result == "08/06/2026"


# ===========================================================================
#
# PART 2: get_eating_day_entries - querying food entries by eating day
#
# Food entries are stored with CALENDAR dates in MongoDB.
# This method maps eating-day boundaries to calendar date queries.
#
# For eating day June 8 with window 10:00-22:00, the entries come from:
#   - Calendar date June 8, time >= 10:00  (daytime + evening)
#   - Calendar date June 9, time < 10:00   (late night belonging to June 8)
#
# ===========================================================================


class FakeRepo:
    """In-memory food repository for testing."""

    def __init__(self, entries: list[FoodEntry]):
        self._entries = entries

    def get_by_user_and_dates(self, telegram_user_id: int, dates: list[str]) -> list[FoodEntry]:
        return [e for e in self._entries if e.date in dates and e.telegram_user_id == telegram_user_id]


class TestGetEatingDayEntries:
    """get_eating_day_entries returns all food entries belonging to a specific eating day.

    Entries are stored with calendar dates. The method queries TWO calendar
    dates and filters by time relative to window_start:
      - eating_day date:  include entries with time >= window_start
      - next calendar day: include entries with time < window_start
    """

    def setup_method(self):
        self.window = EatingWindow(start="10:00", end="22:00")

    def _svc(self, entries: list[FoodEntry]) -> EatingDayService:
        return EatingDayService(food_repo=FakeRepo(entries))

    # --- Basic inclusion/exclusion ---

    def test_daytime_entry_included(self):
        """Entry at 14:00 on June 8 -> in June 8's eating day."""
        entry = _make_entry("08/06/2026", "14:00", calories=500)
        svc = self._svc([entry])
        profile = _make_profile(self.window)
        result = svc.get_eating_day_entries(profile, "08/06/2026")
        assert len(result) == 1
        assert result[0].calories == 500

    def test_late_night_entry_included_in_previous_eating_day(self):
        """Entry at 02:00 on June 9 (calendar) -> belongs to June 8's eating day.

        This is the critical case: the entry is stored with calendar date
        June 9, but it belongs to June 8's eating day because 02:00 is
        before window_start (10:00).
        """
        entry = _make_entry("09/06/2026", "02:00", calories=300)
        svc = self._svc([entry])
        profile = _make_profile(self.window)
        result = svc.get_eating_day_entries(profile, "08/06/2026")
        assert len(result) == 1
        assert result[0].calories == 300

    def test_after_close_entry_included(self):
        """Entry at 23:00 on June 8 -> in June 8's eating day (after close)."""
        entry = _make_entry("08/06/2026", "23:00", calories=400)
        svc = self._svc([entry])
        profile = _make_profile(self.window)
        result = svc.get_eating_day_entries(profile, "08/06/2026")
        assert len(result) == 1
        assert result[0].calories == 400

    def test_entry_before_window_start_excluded_from_same_day(self):
        """Entry at 07:00 on June 8 -> NOT in June 8's eating day.

        07:00 is before window_start (10:00), so it belongs to June 7's
        eating day, not June 8's.
        """
        entry = _make_entry("08/06/2026", "07:00", calories=200)
        svc = self._svc([entry])
        profile = _make_profile(self.window)
        result = svc.get_eating_day_entries(profile, "08/06/2026")
        assert len(result) == 0

    def test_entry_before_window_included_in_previous_eating_day(self):
        """Entry at 07:00 on June 8 -> IN June 7's eating day (as next-day entry)."""
        entry = _make_entry("08/06/2026", "07:00", calories=200)
        svc = self._svc([entry])
        profile = _make_profile(self.window)
        result = svc.get_eating_day_entries(profile, "07/06/2026")
        assert len(result) == 1
        assert result[0].calories == 200

    def test_next_day_entry_after_window_start_excluded(self):
        """Entry at 11:00 on June 9 -> NOT in June 8's eating day.

        11:00 is after window_start, so it belongs to June 9's eating day.
        """
        entry = _make_entry("09/06/2026", "11:00", calories=600)
        svc = self._svc([entry])
        profile = _make_profile(self.window)
        result = svc.get_eating_day_entries(profile, "08/06/2026")
        assert len(result) == 0

    # --- Boundary cases ---

    def test_at_exact_window_start_included_in_new_day(self):
        """Entry at exactly 10:00 on June 9 -> in June 9's eating day (new day starts)."""
        entry = _make_entry("09/06/2026", "10:00", calories=500)
        svc = self._svc([entry])
        profile = _make_profile(self.window)

        # NOT in June 8
        result_june8 = svc.get_eating_day_entries(profile, "08/06/2026")
        assert len(result_june8) == 0

        # IN June 9
        result_june9 = svc.get_eating_day_entries(profile, "09/06/2026")
        assert len(result_june9) == 1

    # --- Full eating day scenario ---

    def test_full_eating_day_collects_all_entries(self):
        """A full eating day with meals at various times.

        Eating day June 8 (window 10:00-22:00) should include:
          - June 8 lunch at 12:00 (inside window)
          - June 8 dinner at 20:00 (inside window)
          - June 8 late snack at 23:30 (after close, same calendar day)
          - June 9 midnight snack at 01:00 (next calendar day, before window)

        And should NOT include:
          - June 8 early entry at 07:00 (belongs to June 7's eating day)
          - June 9 breakfast at 10:30 (belongs to June 9's eating day)
        """
        entries = [
            _make_entry("08/06/2026", "07:00", calories=100),   # June 7's eating day
            _make_entry("08/06/2026", "12:00", calories=600),   # June 8 - included
            _make_entry("08/06/2026", "20:00", calories=500),   # June 8 - included
            _make_entry("08/06/2026", "23:30", calories=200),   # June 8 - included
            _make_entry("09/06/2026", "01:00", calories=150),   # June 8 - included (late night)
            _make_entry("09/06/2026", "10:30", calories=400),   # June 9's eating day
        ]
        svc = self._svc(entries)
        profile = _make_profile(self.window)
        result = svc.get_eating_day_entries(profile, "08/06/2026")

        assert len(result) == 4
        total_cal = sum(e.calories for e in result)
        assert total_cal == 600 + 500 + 200 + 150  # 1450

    def test_no_double_counting_across_eating_days(self):
        """Each entry belongs to exactly one eating day - no leaking.

        An entry at 02:00 June 9 belongs to June 8's eating day ONLY.
        It must NOT also appear in June 9's eating day.
        """
        entry = _make_entry("09/06/2026", "02:00", calories=300)
        svc = self._svc([entry])
        profile = _make_profile(self.window)

        in_june8 = svc.get_eating_day_entries(profile, "08/06/2026")
        in_june9 = svc.get_eating_day_entries(profile, "09/06/2026")

        assert len(in_june8) == 1
        assert len(in_june9) == 0

    # --- No window fallback ---

    def test_no_window_uses_calendar_day(self):
        """Without an eating window, entries at 02:00 on June 9 belong to June 9."""
        entry = _make_entry("09/06/2026", "02:00", calories=300)
        svc = self._svc([entry])
        profile = _make_profile(eating_window=None)

        in_june8 = svc.get_eating_day_entries(profile, "08/06/2026")
        in_june9 = svc.get_eating_day_entries(profile, "09/06/2026")

        assert len(in_june8) == 0
        assert len(in_june9) == 1


# ===========================================================================
#
# PART 3: get_eating_day_totals - calorie/protein aggregation
#
# Simple sum over get_eating_day_entries. Tested here to verify
# the full pipeline from raw entries to aggregated totals.
#
# ===========================================================================


class TestGetEatingDayTotals:
    """Totals must aggregate exactly the entries in the eating day, no more."""

    def test_totals_include_late_night_entries(self):
        """Midnight snack at 01:00 June 9 counts toward June 8's totals."""
        entries = [
            _make_entry("08/06/2026", "14:00", calories=600, protein=40),
            _make_entry("09/06/2026", "01:00", calories=200, protein=10),
        ]
        svc = EatingDayService(food_repo=FakeRepo(entries))
        profile = _make_profile(EatingWindow(start="10:00", end="22:00"))

        cal, prot = svc.get_eating_day_totals(profile, "08/06/2026")
        assert cal == 800
        assert prot == 50

    def test_totals_exclude_pre_window_entries(self):
        """Entry at 07:00 June 8 does NOT count toward June 8's totals."""
        entries = [
            _make_entry("08/06/2026", "07:00", calories=100, protein=5),
            _make_entry("08/06/2026", "14:00", calories=600, protein=40),
        ]
        svc = EatingDayService(food_repo=FakeRepo(entries))
        profile = _make_profile(EatingWindow(start="10:00", end="22:00"))

        cal, prot = svc.get_eating_day_totals(profile, "08/06/2026")
        assert cal == 600
        assert prot == 40

    def test_first_meal_of_day_has_clean_total(self):
        """Bug C repro: logging breakfast at 10:33 should not include
        yesterday's entries in today's eating day total.

        If yesterday (June 8) had 2370 cal of food, and today (June 9)
        the user logs a 990 cal breakfast at 10:33, June 9's eating day
        total should be 990, not 3360.
        """
        entries = [
            # Yesterday's meals (June 8 eating day)
            _make_entry("08/06/2026", "12:00", calories=800, protein=50),
            _make_entry("08/06/2026", "18:00", calories=1000, protein=60),
            _make_entry("08/06/2026", "22:30", calories=570, protein=30),
            # Today's first meal (June 9 eating day)
            _make_entry("09/06/2026", "10:33", calories=990, protein=41),
        ]
        svc = EatingDayService(food_repo=FakeRepo(entries))
        profile = _make_profile(EatingWindow(start="10:00", end="22:00"))

        june8_cal, _ = svc.get_eating_day_totals(profile, "08/06/2026")
        june9_cal, _ = svc.get_eating_day_totals(profile, "09/06/2026")

        assert june8_cal == 800 + 1000 + 570  # 2370
        assert june9_cal == 990  # only the breakfast


# ===========================================================================
#
# PART 4: Clock bugs - calendar date vs eating-day date in GPT prompts
#
# The GPT classifier and food analyzer receive "today's date" in their
# system prompts. This MUST be the actual calendar date, not the eating-day
# date. Otherwise:
#   - "What day is today?" at 2am returns yesterday
#   - Day name (Tuesday) doesn't match date (Monday's date)
#   - QA queries miss today's entries
#
# ===========================================================================


class TestCalendarDateForGPT:
    """Calendar date must be used for GPT prompts, not eating-day date.

    The eating-day date is only for daily summary display and entry
    aggregation. GPT needs the actual calendar date to:
      - Answer "what day is today?" correctly
      - Assign correct calendar dates to food entries
      - Build correct date ranges for Q&A
    """

    def test_calendar_date_differs_from_eating_day_before_window(self):
        """At 2am on June 9, calendar = June 9, eating day = June 8.

        Bug A repro: GPT was told "today = June 8" (eating day) instead
        of "today = June 9" (calendar). When user asked "what day is today?",
        GPT said June 8.
        """
        svc = EatingDayService(food_repo=None)
        profile = _make_profile(EatingWindow(start="10:00", end="22:00"))
        now = _il(2026, 6, 9, 2, 0)

        calendar_date = now.strftime("%d/%m/%Y")
        eating_day = svc.resolve_eating_day(profile, now)

        assert calendar_date == "09/06/2026"  # actual date
        assert eating_day == "08/06/2026"     # eating day
        assert calendar_date != eating_day    # they differ before window

    def test_calendar_date_equals_eating_day_inside_window(self):
        """At 14:00 on June 9, calendar = eating day = June 9."""
        svc = EatingDayService(food_repo=None)
        profile = _make_profile(EatingWindow(start="10:00", end="22:00"))
        now = _il(2026, 6, 9, 14, 0)

        calendar_date = now.strftime("%d/%m/%Y")
        eating_day = svc.resolve_eating_day(profile, now)

        assert calendar_date == eating_day == "09/06/2026"

    def test_day_name_must_match_calendar_date(self):
        """Bug A detail: day name (from actual clock) must match the date
        passed to GPT. June 9, 2026 is a Tuesday.

        Before the fix, GPT received "08/06/2026 (Tuesday)" but June 8
        is Monday. The day name and date were computed from different sources.
        """
        from parsing import hebrew_day_name

        now = _il(2026, 6, 9, 2, 0)  # 2am Tuesday June 9
        calendar_date = now.strftime("%d/%m/%Y")
        day_name = hebrew_day_name(now)

        assert calendar_date == "09/06/2026"
        assert day_name == "שלישי"  # Tuesday - matches June 9

    def test_qa_date_range_includes_actual_today(self):
        """Bug B repro: QA must include actual today in its date range.

        At 2am on June 9, the QA date range must start from June 9
        (calendar), not June 8 (eating day). Otherwise June 9 entries
        are missing from the query.
        """
        now = _il(2026, 6, 9, 2, 0)
        calendar_date = now.strftime("%d/%m/%Y")
        today = datetime.strptime(calendar_date, "%d/%m/%Y").date()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]

        assert dates[0] == "09/06/2026"  # today is included
        assert "08/06/2026" in dates     # yesterday too
        assert "03/06/2026" in dates     # 6 days ago
