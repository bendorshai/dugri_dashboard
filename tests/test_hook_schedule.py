"""
test_hook_schedule - TDD tests for randomized hook timing.

Dugri picks a random fire time within each hook's window (once per day for
daily hooks, once per week for weekly hooks). All users share the same random
times. The poller fires the hook on the first tick AFTER the random time -
even if that tick lands outside the window.

Tests use a mock MongoDB collection to verify the store's behavior.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from repositories.hook_schedule_repository import HookScheduleStore


def _make_store(existing_doc=None):
    """Create a HookScheduleStore with a mocked MongoDB collection."""
    col = MagicMock()
    col.find_one.return_value = existing_doc
    return HookScheduleStore(col), col


class TestGetOrGenerate:
    def test_generates_time_within_window(self):
        store, col = _make_store(existing_doc=None)
        now = datetime(2026, 6, 5, 7, 0, tzinfo=timezone.utc)
        hour, minute = store.get_or_generate("sleep", (8, 10), "daily", now)
        assert 8 <= hour <= 9  # hour in [start, end)
        assert 0 <= minute <= 59

    def test_returns_cached_time_on_same_day_for_daily(self):
        doc = {
            "_id": "hook_schedule",
            "sleep": {"hour": 9, "minute": 23, "date": "2026-06-05"},
        }
        store, col = _make_store(existing_doc=doc)
        now = datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)
        hour, minute = store.get_or_generate("sleep", (8, 10), "daily", now)
        assert (hour, minute) == (9, 23)
        # Should NOT have written to DB (still current)
        col.update_one.assert_not_called()

    def test_regenerates_on_new_day_for_daily(self):
        doc = {
            "_id": "hook_schedule",
            "sleep": {"hour": 9, "minute": 23, "date": "2026-06-04"},  # yesterday
        }
        store, col = _make_store(existing_doc=doc)
        now = datetime(2026, 6, 5, 7, 0, tzinfo=timezone.utc)
        hour, minute = store.get_or_generate("sleep", (8, 10), "daily", now)
        assert 8 <= hour <= 9
        assert 0 <= minute <= 59
        col.update_one.assert_called_once()

    def test_returns_cached_time_on_same_week_for_weekly(self):
        doc = {
            "_id": "hook_schedule",
            "workouts": {"hour": 17, "minute": 45, "week": "2026-W23"},
        }
        store, col = _make_store(existing_doc=doc)
        # 2026-06-05 is in week 23
        now = datetime(2026, 6, 5, 16, 0, tzinfo=timezone.utc)
        hour, minute = store.get_or_generate("workouts", (16, 20), "weekly", now)
        assert (hour, minute) == (17, 45)
        col.update_one.assert_not_called()

    def test_regenerates_on_new_week_for_weekly(self):
        doc = {
            "_id": "hook_schedule",
            "workouts": {"hour": 17, "minute": 45, "week": "2026-W22"},  # last week
        }
        store, col = _make_store(existing_doc=doc)
        # 2026-06-05 is in week 23
        now = datetime(2026, 6, 5, 16, 0, tzinfo=timezone.utc)
        hour, minute = store.get_or_generate("workouts", (16, 20), "weekly", now)
        assert 16 <= hour <= 19
        assert 0 <= minute <= 59
        col.update_one.assert_called_once()

    def test_upserts_on_empty_collection(self):
        store, col = _make_store(existing_doc=None)
        now = datetime(2026, 6, 5, 7, 0, tzinfo=timezone.utc)
        store.get_or_generate("sleep", (8, 10), "daily", now)
        # Should upsert (create doc if not exists)
        call_args = col.update_one.call_args
        assert call_args[0][0] == {"_id": "hook_schedule"}  # filter
        assert call_args[1].get("upsert") is True

    def test_different_hooks_independent(self):
        doc = {
            "_id": "hook_schedule",
            "sleep": {"hour": 9, "minute": 10, "date": "2026-06-05"},
        }
        store, col = _make_store(existing_doc=doc)
        now = datetime(2026, 6, 5, 7, 0, tzinfo=timezone.utc)
        # sleep is cached, workouts needs generation
        sh, sm = store.get_or_generate("sleep", (8, 10), "daily", now)
        assert (sh, sm) == (9, 10)

        wh, wm = store.get_or_generate("workouts", (16, 20), "weekly", now)
        assert 16 <= wh <= 19
        col.update_one.assert_called_once()  # only workouts wrote


class TestRandomTimeBounds:
    """Verify random times always stay within the configured window."""

    @pytest.mark.parametrize("window", [(8, 10), (16, 20), (10, 14), (9, 11)])
    def test_generated_time_within_bounds(self, window):
        store, _ = _make_store(existing_doc=None)
        now = datetime(2026, 6, 5, 7, 0, tzinfo=timezone.utc)
        for _ in range(50):  # statistical confidence
            hour, minute = store.get_or_generate("test_hook", window, "daily", now)
            assert window[0] <= hour < window[1], f"hour {hour} outside {window}"
            assert 0 <= minute <= 59
            # Reset mock so next call generates fresh
            store._collection.find_one.return_value = None
