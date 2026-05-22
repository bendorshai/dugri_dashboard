"""
test_constants — TDD tests for the constants module.

Verifies all expected constants exist with valid values.
"""

import pytest

import constants as C


class TestGateAndRetryConstants:
    def test_toggle_gate_days_is_positive(self):
        assert C.TOGGLE_GATE_DAYS == 4
        assert C.TOGGLE_GATE_DAYS > 0

    def test_target_retry_day(self):
        assert C.TARGET_RETRY_DAY == 9
        assert C.TARGET_RETRY_DAY > C.TOGGLE_GATE_DAYS

    def test_eating_window_retry_days(self):
        assert C.EATING_WINDOW_RETRY_DAYS == 11

    def test_dashboard_intro_day(self):
        assert C.DASHBOARD_INTRO_DAY == 16

    def test_weekly_summary_min_days(self):
        assert C.WEEKLY_SUMMARY_MIN_DAYS == 7


class TestAnchorDays:
    """Anchor days use Python weekday convention: 0=Monday, 6=Sunday."""

    def test_workouts_anchor_is_thursday(self):
        assert C.WORKOUTS_ANCHOR_DAY == 3  # Thursday

    def test_self_care_anchor_is_friday(self):
        assert C.SELF_CARE_ANCHOR_DAY == 4  # Friday

    def test_weekly_summary_anchor_is_sunday(self):
        assert C.WEEKLY_SUMMARY_ANCHOR_DAY == 6  # Sunday

    def test_anchors_are_all_different(self):
        anchors = [C.WORKOUTS_ANCHOR_DAY, C.SELF_CARE_ANCHOR_DAY, C.WEEKLY_SUMMARY_ANCHOR_DAY]
        assert len(set(anchors)) == len(anchors)


class TestRandomTimeWindows:
    """Each window is a (start_hour, end_hour) tuple."""

    def test_sleep_hook_window(self):
        start, end = C.SLEEP_HOOK_WINDOW
        assert start == 8
        assert end == 10
        assert start < end

    def test_workouts_hook_window(self):
        start, end = C.WORKOUTS_HOOK_WINDOW
        assert start == 16
        assert end == 20
        assert start < end

    def test_self_care_hook_window(self):
        start, end = C.SELF_CARE_HOOK_WINDOW
        assert start == 10
        assert end == 14
        assert start < end

    def test_weekly_summary_hook_window(self):
        start, end = C.WEEKLY_SUMMARY_HOOK_WINDOW
        assert start == 9
        assert end == 11
        assert start < end


class TestExitDoor:
    def test_exit_door_threshold(self):
        assert C.EXIT_DOOR_UNANSWERED_THRESHOLD == 2
        assert C.EXIT_DOOR_UNANSWERED_THRESHOLD > 0


class TestRotatingPromptCount:
    def test_rotating_prompt_count(self):
        assert C.ROTATING_PROMPT_COUNT == 5
