"""
test_re_engagement.py - TDD tests for the re-engagement system.

Two pipelines:
- Pipeline A (Food Nudge): no food yesterday (calendar day), morning nudge.
  Blocks sleep hooks until answered. Resets when food is logged.
  Purely calendar-based - no "is user active" gate.
- Pipeline B (Complete Silence): user stops communicating entirely.
  Uses elapsed hours (not calendar days) to avoid false triggers:
  48h -> day1 nudge, 72h -> GPT smart question, 96h -> GPT context message,
  120h -> permanent silence.
  During days 1-3: only weekly feedback allowed, all other hooks suppressed.
  Any user message resets to normal.

Suppression levels:
- NONE: normal operation
- BLOCK_SLEEP: food nudge pending, sleep hooks blocked
- ALLOW_WEEKLY_ONLY: silence days 1-3, only weekly feedback passes
- TOTAL: silenced state, block everything
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from models.profile import User, ToggleState, Toggles
from user_clock import UserClock

# Will be created next
from services.re_engagement_service import (
    ReEngagementService,
    ReEngagementAction,
    SuppressionLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(**kwargs):
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "trial_started_at": datetime.now(timezone.utc) - timedelta(days=10),
        "last_user_message_at": datetime.now(timezone.utc) - timedelta(hours=2),
        "re_engagement_stage": "none",
    }
    defaults.update(kwargs)
    return User(**defaults)


def _clock(utc_time=None):
    """UserClock pinned to a specific UTC time for Israel timezone."""
    if utc_time and utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=timezone.utc)
    return UserClock("Asia/Jerusalem", _now_override=utc_time)


def _morning_clock():
    """Clock at 9:00 Israel time (UTC+3 = 06:00 UTC)."""
    return _clock(datetime(2026, 6, 15, 6, 0))


def _afternoon_clock():
    """Clock at 14:00 Israel time (UTC+3 = 11:00 UTC)."""
    return _clock(datetime(2026, 6, 15, 11, 0))


def _make_service(food_entries_by_date=None):
    """Create ReEngagementService with mocked dependencies."""
    user_repo = MagicMock()
    food_repo = MagicMock()
    analyzer = MagicMock()

    # Default: no food entries
    if food_entries_by_date is None:
        food_entries_by_date = {}

    def mock_get_by_user_and_dates(tid, dates):
        result = []
        for d in dates:
            result.extend(food_entries_by_date.get(d, []))
        return result

    food_repo.get_by_user_and_dates = mock_get_by_user_and_dates
    analyzer._create = MagicMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content="שאלה חכמה מ-GPT"))],
    ))

    return ReEngagementService(user_repo, food_repo, analyzer), user_repo, food_repo


# ---------------------------------------------------------------------------
# Suppression level tests
# ---------------------------------------------------------------------------

class TestSuppressionLevel:
    def test_none_for_normal_user(self):
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="none")
        assert svc.get_suppression_level(user) == SuppressionLevel.NONE

    def test_block_sleep_for_food_nudge_pending(self):
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="food_nudge_pending")
        assert svc.get_suppression_level(user) == SuppressionLevel.BLOCK_SLEEP

    def test_allow_weekly_only_for_silence_day1(self):
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="silence_day1")
        assert svc.get_suppression_level(user) == SuppressionLevel.ALLOW_WEEKLY_ONLY

    def test_allow_weekly_only_for_silence_day2(self):
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="silence_day2")
        assert svc.get_suppression_level(user) == SuppressionLevel.ALLOW_WEEKLY_ONLY

    def test_allow_weekly_only_for_silence_day3(self):
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="silence_day3")
        assert svc.get_suppression_level(user) == SuppressionLevel.ALLOW_WEEKLY_ONLY

    def test_total_for_silenced(self):
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="silenced")
        assert svc.get_suppression_level(user) == SuppressionLevel.TOTAL


# ---------------------------------------------------------------------------
# Pipeline A: Food Nudge
# ---------------------------------------------------------------------------

class TestFoodNudge:
    def test_fires_when_no_food_yesterday_and_morning_window(self):
        """User active, no food yesterday, 9:00 AM -> food nudge fires."""
        svc, _, _ = _make_service()
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 15, 5, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "food_nudge_pending"
        assert action.message  # non-empty message

    def test_skipped_outside_morning_window(self):
        """No food yesterday, but it's 14:00 -> no nudge."""
        svc, _, _ = _make_service()
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 15, 5, 0, tzinfo=timezone.utc),
        )
        clock = _afternoon_clock()
        action = svc.check_re_engagement(user, clock)

        assert action is None

    def test_skipped_when_food_exists_yesterday(self):
        """User logged food yesterday -> no nudge."""
        yesterday = "14/06/2026"
        svc, _, _ = _make_service(food_entries_by_date={
            yesterday: [{"description": "salad"}],
        })
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 15, 5, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)

        assert action is None

    def test_resets_when_food_logged(self):
        """User in food_nudge_pending, logs food today -> reset to none."""
        today = "15/06/2026"
        yesterday = "14/06/2026"
        svc, user_repo, _ = _make_service(food_entries_by_date={
            today: [{"description": "omelette"}],
        })
        user = _make_user(
            re_engagement_stage="food_nudge_pending",
            last_user_message_at=datetime(2026, 6, 15, 5, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)

        # No new message, but stage should reset
        assert action is not None
        assert action.new_stage == "none"
        assert action.message is None  # silent reset

    def test_blocks_sleep_suppression_level(self):
        """food_nudge_pending -> BLOCK_SLEEP suppression."""
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="food_nudge_pending")
        assert svc.get_suppression_level(user) == SuppressionLevel.BLOCK_SLEEP

    def test_allows_workouts_and_self_care(self):
        """food_nudge_pending -> BLOCK_SLEEP, not TOTAL. Other hooks still run."""
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="food_nudge_pending")
        level = svc.get_suppression_level(user)
        assert level != SuppressionLevel.TOTAL
        assert level != SuppressionLevel.ALLOW_WEEKLY_ONLY

    def test_daily_forever_without_food(self):
        """No food yesterday -> nudge fires daily regardless of last message time."""
        svc, _, _ = _make_service()
        user = _make_user(
            re_engagement_stage="none",
            last_user_message_at=datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "food_nudge_pending"

    def test_food_nudge_fires_even_if_user_inactive_30h(self):
        """Food nudge fires even if user hasn't messaged in 30h (no _is_user_active gate)."""
        svc, _, _ = _make_service()
        # User last messaged 30h ago - would have been blocked by old _is_user_active
        # But 30h < 48h so silence pipeline doesn't fire either
        user = _make_user(
            re_engagement_stage="none",
            last_user_message_at=datetime(2026, 6, 14, 0, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()  # 06:00 UTC = 09:00 Israel
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "food_nudge_pending"

    def test_not_sent_to_new_user(self):
        """User with no last_user_message_at -> no re-engagement."""
        svc, _, _ = _make_service()
        user = _make_user(last_user_message_at=None)
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)

        assert action is None

    def test_no_double_send_same_day(self):
        """Already sent today -> no re-send."""
        svc, _, _ = _make_service()
        user = _make_user(
            re_engagement_stage="food_nudge_pending",
            re_engagement_last_sent_at=datetime(2026, 6, 15, 5, 30, tzinfo=timezone.utc),
            last_user_message_at=datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)

        # Should not send again today (already sent, and no food reset)
        # The action is None because we already sent today and no reset condition
        assert action is None


# ---------------------------------------------------------------------------
# Pipeline B: Complete Silence
# ---------------------------------------------------------------------------

class TestSilencePipeline:
    def test_day1_after_48h_silence(self):
        """User silent for 49h, morning window -> silence day 1 nudge."""
        svc, _, _ = _make_service()
        # 49 hours before 06:00 UTC June 15 = June 12 at 05:00 UTC
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 13, 5, 0, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 15, 6, 0))  # 09:00 Israel
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "silence_day1"
        assert action.message  # non-empty

    def test_day1_skipped_before_48h(self):
        """User silent for 47h -> no silence pipeline (needs 48h)."""
        svc, _, _ = _make_service()
        # 47 hours before 06:00 UTC June 15 = June 13 at 07:00 UTC
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 13, 7, 0, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 15, 6, 0))  # 09:00 Israel
        action = svc.check_re_engagement(user, clock)

        # Should NOT enter silence pipeline - only 47h elapsed
        assert action is None or action.new_stage != "silence_day1"

    def test_11h_ago_no_silence(self):
        """Bug repro: user messaged 11h ago (21:25 -> 08:10 next day) -> no silence."""
        svc, _, _ = _make_service()
        # User messaged at 21:25 UTC, now is 08:10 UTC next day (~11h)
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 14, 18, 25, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 15, 5, 10))  # 08:10 Israel (05:10 UTC)
        action = svc.check_re_engagement(user, clock)

        # Must NOT trigger silence pipeline - only 11h elapsed
        assert action is None or action.new_stage != "silence_day1"

    def test_day1_skipped_outside_window(self):
        """User silent 48h+ but it's afternoon -> no message."""
        svc, _, _ = _make_service()
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 13, 5, 0, tzinfo=timezone.utc),
        )
        clock = _afternoon_clock()
        action = svc.check_re_engagement(user, clock)

        assert action is None

    def test_day2_after_72h(self):
        """Silence day 1 + 72h elapsed -> GPT smart question."""
        svc, _, _ = _make_service()
        # 73h before 06:00 UTC June 16 = June 13 at 05:00 UTC
        user = _make_user(
            re_engagement_stage="silence_day1",
            re_engagement_last_sent_at=datetime(2026, 6, 14, 6, 0, tzinfo=timezone.utc),
            last_user_message_at=datetime(2026, 6, 13, 5, 0, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 16, 6, 0))  # 73h since last message
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "silence_day2"
        assert action.message  # GPT-generated

    def test_day2_skipped_before_72h(self):
        """Silence day 1 + only 71h elapsed -> no progression."""
        svc, _, _ = _make_service()
        user = _make_user(
            re_engagement_stage="silence_day1",
            re_engagement_last_sent_at=datetime(2026, 6, 14, 6, 0, tzinfo=timezone.utc),
            last_user_message_at=datetime(2026, 6, 13, 7, 0, tzinfo=timezone.utc),
        )
        # 71h since last message
        clock = _clock(datetime(2026, 6, 16, 6, 0))
        action = svc.check_re_engagement(user, clock)

        assert action is None

    def test_day3_after_96h(self):
        """Silence day 2 + 96h elapsed -> GPT context message."""
        svc, _, _ = _make_service()
        # last message 97h before clock, last sent on previous day
        user = _make_user(
            re_engagement_stage="silence_day2",
            re_engagement_last_sent_at=datetime(2026, 6, 15, 6, 0, tzinfo=timezone.utc),
            last_user_message_at=datetime(2026, 6, 12, 5, 0, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 16, 6, 0))  # 97h since message
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "silence_day3"
        assert action.message  # GPT-generated

    def test_silenced_after_120h(self):
        """Silence day 3 + 120h elapsed -> transition to silenced, no message."""
        svc, _, _ = _make_service()
        # 121h since last message
        user = _make_user(
            re_engagement_stage="silence_day3",
            re_engagement_last_sent_at=datetime(2026, 6, 16, 6, 0, tzinfo=timezone.utc),
            last_user_message_at=datetime(2026, 6, 11, 5, 0, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 16, 6, 0))  # 120h+ since message
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "silenced"
        assert action.message is None  # silent transition

    def test_total_suppression_blocks_everything(self):
        """Silenced -> TOTAL suppression."""
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="silenced")
        assert svc.get_suppression_level(user) == SuppressionLevel.TOTAL

    def test_silence_days_allow_weekly_only(self):
        """During silence days 1-3 -> ALLOW_WEEKLY_ONLY."""
        svc, _, _ = _make_service()
        for stage in ("silence_day1", "silence_day2", "silence_day3"):
            user = _make_user(re_engagement_stage=stage)
            assert svc.get_suppression_level(user) == SuppressionLevel.ALLOW_WEEKLY_ONLY

    def test_silenced_returns_none(self):
        """Already silenced -> check returns None (no action needed)."""
        svc, _, _ = _make_service()
        user = _make_user(
            re_engagement_stage="silenced",
            last_user_message_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)

        assert action is None


# ---------------------------------------------------------------------------
# Transitions and resets
# ---------------------------------------------------------------------------

class TestTransitions:
    def test_pipeline_a_transitions_to_b_when_silent_48h(self):
        """food_nudge_pending + 48h+ silence -> silence_day1 (B overrides A)."""
        svc, _, _ = _make_service()
        # 49h since last message
        user = _make_user(
            re_engagement_stage="food_nudge_pending",
            re_engagement_last_sent_at=datetime(2026, 6, 13, 6, 0, tzinfo=timezone.utc),
            last_user_message_at=datetime(2026, 6, 13, 5, 0, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 15, 6, 0))  # 49h since last message
        action = svc.check_re_engagement(user, clock)

        assert action is not None
        assert action.new_stage == "silence_day1"

    def test_transition_stage_updates_db(self):
        """transition_stage writes to user_repo."""
        svc, user_repo, _ = _make_service()
        svc.transition_stage(123, "silence_day1")

        user_repo.update_fields.assert_called_once()
        call_args = user_repo.update_fields.call_args
        assert call_args[0][0] == 123
        fields = call_args[0][1]
        assert fields["re_engagement_stage"] == "silence_day1"
        assert "re_engagement_last_sent_at" in fields


# ---------------------------------------------------------------------------
# Welcome back
# ---------------------------------------------------------------------------

class TestWelcomeBack:
    def test_handle_return_resets_stage(self):
        """handle_return sets stage to 'none'."""
        svc, user_repo, _ = _make_service()
        user = _make_user(
            re_engagement_stage="silence_day2",
            toggles=Toggles(
                sleep=ToggleState(status="active", consecutive_unanswered=3),
                workouts=ToggleState(status="active", consecutive_unanswered=2),
            ),
        )
        svc.handle_return(user, 123)

        # Should reset stage
        calls = user_repo.update_fields.call_args_list
        assert len(calls) >= 1
        fields = calls[0][0][1]
        assert fields["re_engagement_stage"] == "none"

    def test_handle_return_resets_consecutive_unanswered(self):
        """handle_return resets consecutive_unanswered on all active toggles."""
        svc, user_repo, _ = _make_service()
        user = _make_user(
            re_engagement_stage="silenced",
            toggles=Toggles(
                sleep=ToggleState(status="active", consecutive_unanswered=3),
                workouts=ToggleState(status="active", consecutive_unanswered=2),
                self_care=ToggleState(status="cancelled", consecutive_unanswered=1),
            ),
        )
        svc.handle_return(user, 123)

        calls = user_repo.update_fields.call_args_list
        fields = calls[0][0][1]
        # Active toggles should be reset
        assert fields.get("toggles.sleep.consecutive_unanswered") == 0
        assert fields.get("toggles.workouts.consecutive_unanswered") == 0
        # Cancelled toggle should NOT be reset
        assert "toggles.self_care.consecutive_unanswered" not in fields

    def test_handle_return_generates_welcome_message(self):
        """handle_return generates a GPT welcome-back message."""
        svc, _, _ = _make_service()
        user = _make_user(
            re_engagement_stage="silenced",
            name="Test",
            toggles=Toggles(
                sleep=ToggleState(status="active"),
                workouts=ToggleState(status="active"),
            ),
        )
        message = svc.handle_return(user, 123)

        assert message is not None
        assert isinstance(message, str)
        assert len(message) > 0

    def test_handle_return_none_for_food_nudge(self):
        """No welcome back for food_nudge_pending (user was active)."""
        svc, _, _ = _make_service()
        user = _make_user(re_engagement_stage="food_nudge_pending")
        message = svc.handle_return(user, 123)

        assert message is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_user_clock_timezone_safety(self):
        """Yesterday calculation uses UserClock, not naive .date()."""
        svc, _, _ = _make_service()
        # 23:30 UTC = 02:30 Israel time (next day)
        # So "yesterday" in Israel is actually "today" in UTC
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 14, 23, 30, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 15, 6, 0))  # 09:00 Israel
        # User messaged "yesterday" in Israel time (02:30 AM June 15 Israel = June 14 23:30 UTC)
        # That's today in Israel, so user is NOT silent
        action = svc.check_re_engagement(user, clock)
        # Should be food nudge (no food yesterday) not silence pipeline
        if action:
            assert action.new_stage != "silence_day1"

    def test_no_re_engagement_for_brand_new_user(self):
        """User who never sent a message -> skip entirely."""
        svc, _, _ = _make_service()
        user = _make_user(last_user_message_at=None)
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)
        assert action is None

    def test_food_yesterday_but_not_today_no_nudge(self):
        """Food exists yesterday, not today -> no nudge (we check yesterday only)."""
        yesterday = "14/06/2026"
        svc, _, _ = _make_service(food_entries_by_date={
            yesterday: [{"description": "pizza"}],
        })
        user = _make_user(
            last_user_message_at=datetime(2026, 6, 15, 5, 0, tzinfo=timezone.utc),
        )
        clock = _morning_clock()
        action = svc.check_re_engagement(user, clock)
        assert action is None

    def test_silence_day_progression_requires_elapsed_hours(self):
        """Can't jump from day1 to day2 before 72h total elapsed."""
        svc, _, _ = _make_service()
        # Last message 50h ago (past 48h threshold for day1)
        # but not yet 72h for day2
        user = _make_user(
            re_engagement_stage="silence_day1",
            re_engagement_last_sent_at=datetime(2026, 6, 15, 6, 0, tzinfo=timezone.utc),
            last_user_message_at=datetime(2026, 6, 13, 4, 0, tzinfo=timezone.utc),
        )
        clock = _clock(datetime(2026, 6, 15, 6, 0))  # 50h since message
        action = svc.check_re_engagement(user, clock)
        assert action is None  # Not yet 72h
