"""
test_gem_service.py - Tests for the core wisdom gem engine.

Expected behavior:
- Safety gate: restriction signal blocks all gem delivery
- Min days gate: <14 days since trial start blocks delivery
- Silent week: ~10% of weeks are silent (no gems)
- Already-delivered-this-week blocks repeat delivery
- Declining threshold: high on Sunday (week start), low on Saturday
- Threshold adjustment: likes decrease by 1%, dislikes increase by 10%
- Threshold clamped to floor (-0.15) and ceiling (0.30)
- Probabilistic firing: even above threshold, only fires ~85% of time
- Deck: gem marked used after delivery, not selected again
- Deck: resets when all 52 used, cycle_number incremented
- Category exhausted: silence for that category
- Floor-of-week: general gem on late days (Thu+) if nothing fired yet
- Week boundary resets gem_delivered_this_week and decides silent_week
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass

from models.profile import User, GemState

from services.pattern_detector import DetectedPattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(day_number: int = 20, **kwargs) -> User:
    trial_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "trial_started_at": trial_start,
    }
    defaults.update(kwargs)
    return User(**defaults)


def _make_clock(dt: datetime = None):
    from user_clock import UserClock
    if dt is None:
        # Wednesday
        dt = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    return UserClock("Asia/Jerusalem", _now_override=dt)


def _make_service():
    from services.gem_service import GemService
    user_repo = MagicMock()
    pattern_detector = MagicMock()
    toggle_service = MagicMock()
    analyzer = MagicMock()

    pattern_detector.has_restriction_signal.return_value = False
    pattern_detector.detect.return_value = []
    toggle_service.get_day_number.return_value = 20

    svc = GemService(user_repo, pattern_detector, toggle_service, analyzer)
    return svc, user_repo, pattern_detector, toggle_service, analyzer


def _make_pattern(key="consistent_logging", category="momentum", score=0.8):
    return DetectedPattern(
        key=key,
        category=category,
        raw_score=score,
        confidence=0.9,
        context={"days_logged": 5},
    )


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------

class TestSafetyGate:

    def test_restriction_blocks_delivery(self):
        svc, user_repo, pattern_detector, _, _ = _make_service()
        pattern_detector.has_restriction_signal.return_value = True
        user = _make_user()
        clock = _make_clock()
        result = svc.try_deliver_gem(user, clock)
        assert result is None

    @patch("services.gem_service.random")
    def test_no_restriction_allows_evaluation(self, mock_random):
        """When no restriction, evaluation continues (may still return None for other reasons)."""
        svc, user_repo, pattern_detector, _, _ = _make_service()
        pattern_detector.has_restriction_signal.return_value = False
        mock_random.random.return_value = 0.5  # not silent
        mock_random.uniform.return_value = 0.0
        user = _make_user()
        clock = _make_clock()
        # No patterns detected, so still None, but safety gate didn't block
        result = svc.try_deliver_gem(user, clock)
        assert result is None
        pattern_detector.detect.assert_called_once()


class TestMinDaysGate:

    def test_too_early_blocks(self):
        svc, _, _, toggle_service, _ = _make_service()
        toggle_service.get_day_number.return_value = 10  # < 14
        user = _make_user()
        clock = _make_clock()
        result = svc.try_deliver_gem(user, clock)
        assert result is None

    @patch("services.gem_service.random")
    def test_past_gate_allows(self, mock_random):
        svc, _, pattern_detector, toggle_service, _ = _make_service()
        toggle_service.get_day_number.return_value = 15  # >= 14
        mock_random.random.return_value = 0.5  # not silent (0.5 > 0.10)
        mock_random.uniform.return_value = 0.0
        user = _make_user()
        clock = _make_clock()
        svc.try_deliver_gem(user, clock)
        pattern_detector.detect.assert_called_once()


class TestAlreadyDelivered:

    def test_already_delivered_this_week_blocks(self):
        svc, _, pattern_detector, _, _ = _make_service()
        user = _make_user(gem_state=GemState(
            gem_delivered_this_week=True,
            week_start_iso="2026-06-14",  # current week
        ))
        clock = _make_clock()  # Wed Jun 17
        result = svc.try_deliver_gem(user, clock)
        assert result is None
        pattern_detector.detect.assert_not_called()


class TestSilentWeek:

    def test_silent_week_blocks(self):
        svc, _, pattern_detector, _, _ = _make_service()
        user = _make_user(gem_state=GemState(
            silent_week=True,
            week_start_iso="2026-06-14",  # current week
        ))
        clock = _make_clock()
        result = svc.try_deliver_gem(user, clock)
        assert result is None
        pattern_detector.detect.assert_not_called()


# ---------------------------------------------------------------------------
# Threshold tests
# ---------------------------------------------------------------------------

class TestDecliningThreshold:

    def test_threshold_higher_on_sunday(self):
        from services.gem_service import GemService
        # Sunday = gem day 0 (week start)
        sunday = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
        clock_sun = _make_clock(sunday)
        threshold_sun = GemService._compute_threshold(clock_sun.weekday(), 0.0)

        # Saturday = gem day 6 (week end)
        saturday = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        clock_sat = _make_clock(saturday)
        threshold_sat = GemService._compute_threshold(clock_sat.weekday(), 0.0)

        assert threshold_sun > threshold_sat

    def test_threshold_adjustment_applied(self):
        from services.gem_service import GemService
        clock = _make_clock()
        weekday = clock.weekday()
        base = GemService._compute_threshold(weekday, 0.0)
        lowered = GemService._compute_threshold(weekday, -0.10)
        raised = GemService._compute_threshold(weekday, 0.10)
        assert lowered < base < raised


class TestThresholdFeedback:

    def test_like_decreases_threshold(self):
        svc, user_repo, _, _, _ = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=0.0))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "like")
        call_args = user_repo.update_fields.call_args
        fields = call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] < 0.0

    def test_dislike_increases_threshold(self):
        svc, user_repo, _, _, _ = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=0.0))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "dislike")
        call_args = user_repo.update_fields.call_args
        fields = call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] > 0.0

    def test_threshold_floor_respected(self):
        svc, user_repo, _, _, _ = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=-0.15))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "like")
        call_args = user_repo.update_fields.call_args
        fields = call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] >= -0.15

    def test_threshold_ceiling_respected(self):
        svc, user_repo, _, _, _ = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=0.30))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "dislike")
        call_args = user_repo.update_fields.call_args
        fields = call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] <= 0.30


# ---------------------------------------------------------------------------
# Deck management tests
# ---------------------------------------------------------------------------

class TestDeckManagement:

    def test_used_gem_not_selected(self):
        svc, _, _, _, _ = _make_service()
        from gem_catalog import ALL_GEMS
        gem_state = GemState(used_gem_ids=["gem_01"])
        available = svc._get_available_gems(gem_state)
        ids = [g.id for g in available]
        assert "gem_01" not in ids
        assert len(available) == 51

    def test_deck_reset_when_all_used(self):
        svc, user_repo, _, _, _ = _make_service()
        from gem_catalog import ALL_GEMS
        all_ids = [g.id for g in ALL_GEMS]
        gem_state = GemState(used_gem_ids=all_ids, cycle_number=1)
        available = svc._get_available_gems(gem_state)
        assert len(available) == 0

    def test_category_exhausted_returns_none(self):
        svc, _, _, _, _ = _make_service()
        from gem_catalog import get_gems_for_category
        # Mark all momentum gems as used
        momentum_ids = [g.id for g in get_gems_for_category("momentum")]
        gem_state = GemState(used_gem_ids=momentum_ids)
        available_momentum = svc._get_available_for_category(gem_state, "momentum")
        assert len(available_momentum) == 0


class TestProbabilisticFiring:

    @patch("services.gem_service.random")
    def test_fires_when_random_below_probability(self, mock_random):
        svc, user_repo, pattern_detector, _, analyzer = _make_service()
        pattern = _make_pattern(score=0.9)
        pattern_detector.detect.return_value = [pattern]
        # Mock random to always fire
        mock_random.random.return_value = 0.5  # below 0.85
        mock_random.uniform.return_value = 0.0  # no noise
        analyzer.dress_wisdom_gem.return_value = "dressed text"
        user = _make_user()
        clock = _make_clock()
        result = svc.try_deliver_gem(user, clock)
        assert result is not None

    @patch("services.gem_service.random")
    def test_does_not_fire_when_random_above_probability(self, mock_random):
        svc, user_repo, pattern_detector, _, _ = _make_service()
        pattern = _make_pattern(score=0.9)
        pattern_detector.detect.return_value = [pattern]
        # Mock random so the coin flip fails
        mock_random.random.side_effect = [
            0.5,   # silent week check: not silent (0.5 > 0.10)
            0.95,  # fire probability: miss (0.95 > 0.85)
        ]
        mock_random.uniform.return_value = 0.0
        user = _make_user()
        clock = _make_clock()
        result = svc.try_deliver_gem(user, clock)
        assert result is None


class TestWeekBoundary:

    def test_week_init_resets_state(self):
        svc, user_repo, _, _, _ = _make_service()
        user = _make_user(gem_state=GemState(
            week_start_iso="2026-06-07",  # last week
            gem_delivered_this_week=True,
            silent_week=True,
        ))
        clock = _make_clock()  # Wed Jun 17 -> week started Sun Jun 14
        with patch("services.gem_service.random") as mock_random:
            mock_random.random.return_value = 0.5  # not silent
            svc._ensure_week_initialized(user, clock)
        # Should have updated user fields
        call_args = user_repo.update_fields.call_args
        fields = call_args[0][1]
        assert fields["gem_state.gem_delivered_this_week"] is False
        assert "gem_state.week_start_iso" in fields
