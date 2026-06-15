"""
gem_service.py - Core wisdom gem engine.

Manages the variable-ratio reinforcement system: declining threshold,
probabilistic firing, deck management, and GPT dressing.

The deterministic engine chooses which gem and when. GPT only dresses
the text with personal context.

Depends on: repositories/user_repository, services/pattern_detector,
            services/toggle_service, analyzer, gem_catalog, constants.
Used by: handlers/base (piggyback), scheduler (poller).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from gem_catalog import ALL_GEMS, Gem, get_gems_for_category
from models.profile import User, GemState, GemDelivery, GemFeedback
from services.pattern_detector import DetectedPattern
from user_clock import UserClock

from constants import (
    GEM_GATE_DAYS,
    GEM_SILENT_WEEK_RATE,
    GEM_FIRE_PROBABILITY,
    GEM_THRESHOLD_LIKE_DELTA,
    GEM_THRESHOLD_DISLIKE_DELTA,
    GEM_THRESHOLD_FLOOR,
    GEM_THRESHOLD_CEILING,
    GEM_FLOOR_OF_WEEK_DAY,
)


@dataclass
class GemResult:
    gem_id: str
    dressed_text: str
    category: str
    pattern_key: str | None


class GemService:

    def __init__(self, user_repo, pattern_detector, toggle_service, analyzer):
        self._user_repo = user_repo
        self._pattern_detector = pattern_detector
        self._toggle_service = toggle_service
        self._analyzer = analyzer

    def try_deliver_gem(self, profile: User, clock: UserClock) -> GemResult | None:
        """Master decision: should a gem fire now?

        Gates (in order):
        1. Safety: restriction signal -> silence
        2. Min days: too early in trial -> silence
        3. Week init: reset on boundary, decide silent week
        4. Already delivered this week -> silence
        5. Silent week -> silence
        6. Detect patterns, check threshold, probabilistic fire
        7. Floor-of-week fallback for general gems
        """
        tid = profile.telegram_user_id

        # Gate 1: Safety
        if self._pattern_detector.has_restriction_signal(profile, clock):
            return None

        # Gate 2: Min days
        day_number = self._toggle_service.get_day_number(profile)
        if day_number < GEM_GATE_DAYS:
            return None

        # Gate 3: Week init
        self._ensure_week_initialized(profile, clock)
        # Re-read state after potential update
        gem_state = profile.gem_state

        # Gate 4: Already delivered
        if gem_state.gem_delivered_this_week:
            return None

        # Gate 5: Silent week
        if gem_state.silent_week:
            return None

        # Detect patterns
        patterns = self._pattern_detector.detect(profile, clock)

        # Threshold
        weekday = clock.weekday()
        threshold = self._compute_threshold(weekday, gem_state.threshold_adjustment)

        # Check patterns against threshold
        for pattern in patterns:
            if pattern.interest_score < threshold:
                continue

            # Probabilistic firing
            if random.random() > GEM_FIRE_PROBABILITY:
                return None

            # Select gem from available deck
            gem = self._select_gem_for_pattern(pattern, gem_state)
            if gem is None:
                continue  # category exhausted

            # Dress and deliver
            return self._deliver(tid, profile, gem, pattern.key, pattern.context, clock)

        # Floor-of-week: general gem on late days
        gem_day = _weekday_to_gem_day(weekday)
        if gem_day >= GEM_FLOOR_OF_WEEK_DAY:
            if random.random() < GEM_FIRE_PROBABILITY:
                gem = self._select_general_gem(gem_state)
                if gem:
                    return self._deliver(tid, profile, gem, None, {}, clock)

        return None

    def handle_feedback(self, tid: int, gem_id: str, reaction: str):
        """Adjust personal threshold based on like/dislike feedback."""
        profile = self._user_repo.get(tid)
        current = profile.gem_state.threshold_adjustment

        if reaction == "like":
            new_adj = max(GEM_THRESHOLD_FLOOR, current + GEM_THRESHOLD_LIKE_DELTA)
        else:
            new_adj = min(GEM_THRESHOLD_CEILING, current + GEM_THRESHOLD_DISLIKE_DELTA)

        self._user_repo.update_fields(tid, {
            "gem_state.threshold_adjustment": new_adj,
        })

        feedback = GemFeedback(
            gem_id=gem_id,
            reaction=reaction,
            reacted_at=datetime.now(timezone.utc),
        )
        self._user_repo.push_to_list(
            tid, "gem_state.feedbacks", feedback.model_dump(mode="json"),
        )

    @staticmethod
    def _compute_threshold(weekday: int, user_adjustment: float) -> float:
        """Declining threshold over the gem-week.

        weekday: Python weekday (0=Mon...6=Sun).
        Gem-week starts Sunday: Sun=0, Mon=1, ..., Sat=6.
        Base threshold: 0.8 (Sunday) -> 0.3 (Saturday).
        """
        gem_day = _weekday_to_gem_day(weekday)
        base = 0.8 - (gem_day * 0.5 / 6)
        adjusted = base + user_adjustment
        return max(0.15, min(0.95, adjusted))

    def _ensure_week_initialized(self, profile: User, clock: UserClock):
        """Reset weekly state on week boundary."""
        week_start = _get_week_start_iso(clock)
        if profile.gem_state.week_start_iso == week_start:
            return  # same week

        is_silent = random.random() < GEM_SILENT_WEEK_RATE
        self._user_repo.update_fields(profile.telegram_user_id, {
            "gem_state.week_start_iso": week_start,
            "gem_state.gem_delivered_this_week": False,
            "gem_state.silent_week": is_silent,
        })
        # Update in-memory state too
        profile.gem_state.week_start_iso = week_start
        profile.gem_state.gem_delivered_this_week = False
        profile.gem_state.silent_week = is_silent

    def _get_available_gems(self, gem_state: GemState) -> list[Gem]:
        used = set(gem_state.used_gem_ids)
        return [g for g in ALL_GEMS if g.id not in used]

    def _get_available_for_category(self, gem_state: GemState, category: str) -> list[Gem]:
        return [g for g in self._get_available_gems(gem_state) if category in g.categories]

    def _select_gem_for_pattern(self, pattern: DetectedPattern, gem_state: GemState) -> Gem | None:
        """Select best available gem matching the pattern's category."""
        available = self._get_available_for_category(gem_state, pattern.category)
        if not available:
            return None
        # Prefer higher-league gems (lower number)
        available.sort(key=lambda g: g.league)
        return available[0]

    def _select_general_gem(self, gem_state: GemState) -> Gem | None:
        available = self._get_available_for_category(gem_state, "general")
        if not available:
            return None
        return random.choice(available)

    def _deliver(self, tid: int, profile: User, gem: Gem,
                 pattern_key: str | None, context: dict, clock: UserClock) -> GemResult:
        """Dress gem via GPT, record delivery, return result."""
        mode = "general" if pattern_key is None else "pattern"
        dressed_text = self._analyzer.dress_wisdom_gem(
            gem_text=gem.text,
            category=gem.categories[0],
            mode=mode,
            context=context,
            name=profile.name or "",
            gender=profile.gender or "male",
        )

        # Record delivery
        now = datetime.now(timezone.utc)
        delivery = GemDelivery(
            gem_id=gem.id,
            category=gem.categories[0],
            pattern_key=pattern_key,
            delivered_at=now,
        )

        # Update state: mark gem used, week delivered, persist delivery
        used_ids = profile.gem_state.used_gem_ids + [gem.id]
        self._user_repo.update_fields(tid, {
            "gem_state.used_gem_ids": used_ids,
            "gem_state.last_delivered_at": now.isoformat(),
            "gem_state.gem_delivered_this_week": True,
        })
        self._user_repo.push_to_list(
            tid, "gem_state.deliveries", delivery.model_dump(mode="json"),
        )

        # Check if deck needs reset
        if len(used_ids) >= len(ALL_GEMS):
            self._user_repo.update_fields(tid, {
                "gem_state.used_gem_ids": [],
                "gem_state.cycle_number": profile.gem_state.cycle_number + 1,
                "gem_state.deliveries": [],
            })

        return GemResult(
            gem_id=gem.id,
            dressed_text=dressed_text,
            category=gem.categories[0],
            pattern_key=pattern_key,
        )


def _weekday_to_gem_day(weekday: int) -> int:
    """Convert Python weekday (0=Mon...6=Sun) to gem-week day (0=Sun...6=Sat)."""
    return (weekday + 1) % 7


def _get_week_start_iso(clock: UserClock) -> str:
    """Get ISO date string for the Sunday starting the current gem-week."""
    from datetime import timedelta
    today = clock.today()
    # weekday(): 0=Mon, 6=Sun. Days since last Sunday:
    weekday = today.weekday()
    days_since_sunday = (weekday + 1) % 7
    sunday = today - timedelta(days=days_since_sunday)
    return sunday.isoformat()
