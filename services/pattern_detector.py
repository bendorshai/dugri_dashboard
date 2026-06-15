"""
pattern_detector.py - Deterministic behavioral pattern detection engine.

Analyzes food_entries over the last 14 days to detect patterns that
trigger wisdom gem delivery. No GPT involved - pure arithmetic.

Safety: has_restriction_signal() detects eating restriction patterns
and must be checked BEFORE any gem delivery.

Depends on: repositories/food_repository, models/profile, user_clock.
Used by: services/gem_service.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from models.profile import User
from user_clock import UserClock

# Category weights: some patterns carry more emotional weight
CATEGORY_WEIGHTS = {
    "return": 1.3,
    "compassion": 1.2,
    "momentum": 1.0,
    "streak": 1.0,
    "measurement": 0.9,
    "general": 0.8,
}

# Safety thresholds
RESTRICTION_MIN_DAYS = 3
RESTRICTION_LOW_CAL_THRESHOLD = 1000
RESTRICTION_FEW_MEALS_THRESHOLD = 1.0  # avg meals/day
RESTRICTION_UNDER_TARGET_RATIO = 0.60  # below 60% of target = restriction

# Pattern thresholds
CONSISTENT_LOGGING_MIN_DAYS = 5
RETURN_GAP_MIN_DAYS = 2
LOGGING_STREAK_MIN_DAYS = 3
IMPERFECT_TARGET_HIT_RATIO = 0.50


@dataclass
class DetectedPattern:
    key: str
    category: str
    raw_score: float
    confidence: float
    context: dict = field(default_factory=dict)

    @property
    def interest_score(self) -> float:
        weight = CATEGORY_WEIGHTS.get(self.category, 1.0)
        return self.raw_score * weight * self.confidence


class PatternDetector:

    def __init__(self, food_repo):
        self._food_repo = food_repo

    def _fetch_entries(self, user: User, clock: UserClock):
        """Fetch food entries for the last 14 days."""
        today = clock.today()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(14)]
        return self._food_repo.get_by_user_and_dates(user.telegram_user_id, dates)

    def _group_by_date(self, entries) -> dict[str, list]:
        """Group entries by date string."""
        grouped = defaultdict(list)
        for entry in entries:
            grouped[entry.date].append(entry)
        return dict(grouped)

    def has_restriction_signal(self, user: User, clock: UserClock) -> bool:
        """Safety gate: detect eating restriction patterns.

        Returns True if:
        - Average daily calories < 1000 for 3+ days
        - Average meals/day <= 1 for 3+ days (when user has entries)
        - Consistently >40% under calorie target for 3+ days
        """
        entries = self._fetch_entries(user, clock)
        if not entries:
            return False

        by_date = self._group_by_date(entries)
        if len(by_date) < RESTRICTION_MIN_DAYS:
            return False

        # Check low calories
        daily_cals = [sum(e.calories for e in day_entries) for day_entries in by_date.values()]
        low_cal_days = sum(1 for c in daily_cals if c < RESTRICTION_LOW_CAL_THRESHOLD)
        if low_cal_days >= RESTRICTION_MIN_DAYS:
            return True

        # Check few meals per day
        meals_per_day = [len(day_entries) for day_entries in by_date.values()]
        few_meals_days = sum(1 for m in meals_per_day if m <= RESTRICTION_FEW_MEALS_THRESHOLD)
        if few_meals_days >= RESTRICTION_MIN_DAYS:
            return True

        # Check under calorie target
        target_cal = user.targets.calories if user.targets else None
        if target_cal and target_cal > 0:
            under_target_days = sum(
                1 for c in daily_cals
                if c < target_cal * RESTRICTION_UNDER_TARGET_RATIO
            )
            if under_target_days >= RESTRICTION_MIN_DAYS:
                return True

        return False

    def detect(self, user: User, clock: UserClock) -> list[DetectedPattern]:
        """Detect behavioral patterns from food entries.

        Returns patterns sorted by interest score descending.
        """
        entries = self._fetch_entries(user, clock)
        if not entries:
            return []

        by_date = self._group_by_date(entries)
        today = clock.today()
        patterns = []

        # --- Consistent logging (momentum) ---
        # Count unique days with entries in last 7 days
        week_dates = {(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)}
        logged_days_this_week = sum(1 for d in week_dates if d in by_date)
        if logged_days_this_week >= CONSISTENT_LOGGING_MIN_DAYS:
            patterns.append(DetectedPattern(
                key="consistent_logging",
                category="momentum",
                raw_score=logged_days_this_week / 7,
                confidence=0.9,
                context={"days_logged": logged_days_this_week},
            ))

        # --- Return after gap (return) ---
        today_str = today.strftime("%d/%m/%Y")
        if today_str in by_date:
            # Find the most recent entry before today
            sorted_dates = sorted(by_date.keys(), key=lambda d: _parse_date(d), reverse=True)
            gap_days = 0
            for i, d in enumerate(sorted_dates):
                if d == today_str:
                    continue
                entry_date = _parse_date(d)
                gap = (today - entry_date).days
                if i == 1 or (i > 0 and sorted_dates[i - 1] == today_str):
                    gap_days = gap - 1  # days between today and previous entry
                    break
            if gap_days >= RETURN_GAP_MIN_DAYS:
                patterns.append(DetectedPattern(
                    key="return_after_gap",
                    category="return",
                    raw_score=min(1.0, 0.6 + 0.1 * gap_days),
                    confidence=0.95,
                    context={"gap_days": gap_days},
                ))

        # --- Logging streak (streak) ---
        streak = 0
        for i in range(14):
            d = (today - timedelta(days=i)).strftime("%d/%m/%Y")
            if d in by_date:
                streak += 1
            else:
                break
        if streak >= LOGGING_STREAK_MIN_DAYS:
            patterns.append(DetectedPattern(
                key="logging_streak",
                category="streak",
                raw_score=min(1.0, streak / 14),
                confidence=0.9,
                context={"streak_days": streak},
            ))

        # --- Imperfect but logging (compassion) ---
        target_cal = user.targets.calories if user.targets else None
        if target_cal and target_cal > 0 and len(by_date) >= 5:
            daily_cals = {d: sum(e.calories for e in es) for d, es in by_date.items()}
            hit_days = sum(1 for c in daily_cals.values() if c >= target_cal * 0.9)
            hit_ratio = hit_days / len(daily_cals)
            if hit_ratio < IMPERFECT_TARGET_HIT_RATIO and logged_days_this_week >= 5:
                patterns.append(DetectedPattern(
                    key="imperfect_but_logging",
                    category="compassion",
                    raw_score=0.6,
                    confidence=0.85,
                    context={"hit_ratio": round(hit_ratio, 2), "days_logged": len(by_date)},
                ))

        # --- First week complete (measurement) ---
        all_dates = sorted(by_date.keys(), key=lambda d: _parse_date(d))
        if len(all_dates) >= 7:
            first_date = _parse_date(all_dates[0])
            days_since_first = (today - first_date).days
            if days_since_first <= 10:  # within first 10 days
                patterns.append(DetectedPattern(
                    key="first_week_complete",
                    category="measurement",
                    raw_score=0.8,
                    confidence=0.9,
                    context={"total_days": len(all_dates)},
                ))

        # --- Improving trend (measurement) ---
        if target_cal and target_cal > 0 and len(by_date) >= 10:
            this_week_dates = {(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)}
            last_week_dates = {(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7, 14)}
            this_week_cals = [sum(e.calories for e in by_date[d]) for d in this_week_dates if d in by_date]
            last_week_cals = [sum(e.calories for e in by_date[d]) for d in last_week_dates if d in by_date]
            if this_week_cals and last_week_cals:
                this_avg = sum(this_week_cals) / len(this_week_cals)
                last_avg = sum(last_week_cals) / len(last_week_cals)
                this_diff = abs(this_avg - target_cal)
                last_diff = abs(last_avg - target_cal)
                if this_diff < last_diff:
                    patterns.append(DetectedPattern(
                        key="improving_trend",
                        category="measurement",
                        raw_score=0.7,
                        confidence=0.8,
                        context={
                            "this_week_avg": round(this_avg),
                            "last_week_avg": round(last_avg),
                            "target": target_cal,
                        },
                    ))

        # Sort by interest score descending
        patterns.sort(key=lambda p: p.interest_score, reverse=True)
        return patterns


def _parse_date(date_str: str):
    """Parse DD/MM/YYYY to date object."""
    from datetime import datetime as dt
    return dt.strptime(date_str, "%d/%m/%Y").date()
