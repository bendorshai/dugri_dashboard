"""
test_pattern_detector.py - Tests for behavioral pattern detection engine.

Expected behavior:
- PatternDetector analyzes food_entries to detect behavioral patterns
- Each pattern has a category, raw_score, confidence, and context dict
- Patterns are returned sorted by interest score (raw_score * weight * confidence) descending
- Safety: has_restriction_signal returns True when eating restriction is detected
- Safety: low calories (<1000 avg for 3+ days) triggers restriction signal
- Safety: very few meals (0-1/day for 3+ days when active) triggers restriction signal
- Safety: consistently >40% under calorie target triggers restriction signal
- No patterns detected with insufficient data (fewer than 3 days)
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from models.profile import User, Targets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(**kwargs) -> User:
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "trial_started_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return User(**defaults)


def _make_entry(date_str: str, calories: int = 500, protein: int = 30, time: str = "12:00"):
    """Create a dict matching what food_repo.get_by_user_and_dates returns."""
    from models.food import FoodEntry
    return FoodEntry(
        telegram_user_id=123,
        date=date_str,
        time=time,
        description="test food",
        calories=calories,
        protein=protein,
    )


def _make_clock(dt: datetime = None):
    from user_clock import UserClock
    if dt is None:
        dt = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)  # Sunday
    return UserClock("Asia/Jerusalem", _now_override=dt)


def _make_detector():
    from services.pattern_detector import PatternDetector
    food_repo = MagicMock()
    food_repo.get_by_user_and_dates.return_value = []
    return PatternDetector(food_repo), food_repo


def _dates_back(n: int, from_date: datetime = None) -> list[str]:
    """Generate DD/MM/YYYY date strings for n days back from from_date."""
    if from_date is None:
        from_date = datetime(2026, 6, 15, tzinfo=timezone.utc)
    dates = []
    for i in range(n):
        d = from_date - timedelta(days=i)
        dates.append(d.strftime("%d/%m/%Y"))
    return dates


# ---------------------------------------------------------------------------
# Safety tests (highest priority)
# ---------------------------------------------------------------------------

class TestRestrictionSignal:

    def test_low_calories_triggers_restriction(self):
        """Avg <1000 cal/day for 3+ days = restriction signal."""
        detector, food_repo = _make_detector()
        user = _make_user(targets=Targets(calories=2000))
        # 3 days of ~800 cal each (2 meals per day)
        entries = []
        for date_str in _dates_back(3):
            entries.append(_make_entry(date_str, calories=400, time="09:00"))
            entries.append(_make_entry(date_str, calories=400, time="13:00"))
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        assert detector.has_restriction_signal(user, clock) is True

    def test_normal_calories_no_restriction(self):
        detector, food_repo = _make_detector()
        user = _make_user(targets=Targets(calories=2000))
        entries = []
        for date_str in _dates_back(5):
            entries.append(_make_entry(date_str, calories=700, time="09:00"))
            entries.append(_make_entry(date_str, calories=800, time="13:00"))
            entries.append(_make_entry(date_str, calories=500, time="19:00"))
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        assert detector.has_restriction_signal(user, clock) is False

    def test_very_few_meals_triggers_restriction(self):
        """0-1 meals/day for 3+ days when active = restriction."""
        detector, food_repo = _make_detector()
        user = _make_user(
            targets=Targets(calories=2000),
            last_user_message_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        # 3 days with only 1 meal each
        entries = [_make_entry(d, calories=600) for d in _dates_back(3)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        assert detector.has_restriction_signal(user, clock) is True

    def test_no_entries_no_restriction(self):
        """No food entries = user just isn't logging, not restricting."""
        detector, food_repo = _make_detector()
        user = _make_user()
        food_repo.get_by_user_and_dates.return_value = []
        clock = _make_clock()
        assert detector.has_restriction_signal(user, clock) is False

    def test_under_target_triggers_restriction(self):
        """Consistently >40% under calorie target = restriction."""
        detector, food_repo = _make_detector()
        user = _make_user(targets=Targets(calories=2500))
        # 3 days of ~1200 cal (52% under target)
        entries = []
        for date_str in _dates_back(3):
            entries.append(_make_entry(date_str, calories=600, time="09:00"))
            entries.append(_make_entry(date_str, calories=600, time="18:00"))
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        assert detector.has_restriction_signal(user, clock) is True

    def test_short_period_no_restriction(self):
        """Only 1-2 days of data: not enough to call restriction."""
        detector, food_repo = _make_detector()
        user = _make_user(targets=Targets(calories=2000))
        entries = [_make_entry(_dates_back(1)[0], calories=400)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        assert detector.has_restriction_signal(user, clock) is False


# ---------------------------------------------------------------------------
# Pattern detection tests
# ---------------------------------------------------------------------------

class TestConsistentLogging:

    def test_5_days_detected(self):
        detector, food_repo = _make_detector()
        user = _make_user()
        entries = [_make_entry(d, calories=600) for d in _dates_back(5)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        keys = [p.key for p in patterns]
        assert "consistent_logging" in keys

    def test_2_days_not_detected(self):
        detector, food_repo = _make_detector()
        user = _make_user()
        entries = [_make_entry(d, calories=600) for d in _dates_back(2)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        keys = [p.key for p in patterns]
        assert "consistent_logging" not in keys


class TestReturnAfterGap:

    def test_return_after_3_day_gap(self):
        detector, food_repo = _make_detector()
        user = _make_user()
        # Today (day 0) + day 4,5,6 (gap of 3 days in between)
        today = _dates_back(1)[0]
        old_dates = _dates_back(7)[4:]  # 3 old entries
        entries = [_make_entry(today)] + [_make_entry(d) for d in old_dates]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        keys = [p.key for p in patterns]
        assert "return_after_gap" in keys

    def test_no_gap_no_return_pattern(self):
        detector, food_repo = _make_detector()
        user = _make_user()
        entries = [_make_entry(d) for d in _dates_back(7)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        keys = [p.key for p in patterns]
        assert "return_after_gap" not in keys


class TestLoggingStreak:

    def test_streak_detected(self):
        detector, food_repo = _make_detector()
        user = _make_user()
        entries = [_make_entry(d) for d in _dates_back(7)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        keys = [p.key for p in patterns]
        assert "logging_streak" in keys

    def test_streak_score_scales(self):
        """Longer streak = higher score."""
        detector, food_repo = _make_detector()
        user = _make_user()
        entries_short = [_make_entry(d) for d in _dates_back(3)]
        entries_long = [_make_entry(d) for d in _dates_back(10)]

        food_repo.get_by_user_and_dates.return_value = entries_short
        clock = _make_clock()
        patterns_short = detector.detect(user, clock)
        streak_short = [p for p in patterns_short if p.key == "logging_streak"]

        food_repo.get_by_user_and_dates.return_value = entries_long
        patterns_long = detector.detect(user, clock)
        streak_long = [p for p in patterns_long if p.key == "logging_streak"]

        assert len(streak_short) == 1
        assert len(streak_long) == 1
        assert streak_long[0].raw_score > streak_short[0].raw_score


class TestImperfectButLogging:

    def test_detected_when_logging_daily_but_under_target(self):
        detector, food_repo = _make_detector()
        user = _make_user(targets=Targets(calories=2000))
        # 7 days logged, but only 800 cal/day (40% of target)
        entries = [_make_entry(d, calories=800) for d in _dates_back(7)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        keys = [p.key for p in patterns]
        assert "imperfect_but_logging" in keys


class TestPatternSorting:

    def test_patterns_sorted_by_interest_score(self):
        detector, food_repo = _make_detector()
        user = _make_user(targets=Targets(calories=2000))
        # Create data that triggers multiple patterns
        entries = [_make_entry(d, calories=800) for d in _dates_back(7)]
        food_repo.get_by_user_and_dates.return_value = entries
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        if len(patterns) >= 2:
            scores = [p.interest_score for p in patterns]
            assert scores == sorted(scores, reverse=True)


class TestNoDataNoPatterns:

    def test_empty_entries(self):
        detector, food_repo = _make_detector()
        user = _make_user()
        food_repo.get_by_user_and_dates.return_value = []
        clock = _make_clock()
        patterns = detector.detect(user, clock)
        assert patterns == []
