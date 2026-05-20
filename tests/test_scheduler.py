from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Stub heavy imports
for mod in [
    "telegram", "telegram.ext",
    "pymongo", "openai",
]:
    sys.modules.setdefault(mod, MagicMock())

from models.profile import UserProfile, EatingWindow, Targets
from scheduler import schedule_eating_window_jobs


def _make_profile(**kwargs):
    defaults = {
        "telegram_user_id": 123,
        "eating_window": EatingWindow(start="08:00", end="20:00"),
        "targets": Targets(calories=2000, protein=150),
        "timezone": "Asia/Jerusalem",
    }
    defaults.update(kwargs)
    return UserProfile(**defaults)


class TestScheduleEatingWindowJobs:
    def test_cancels_existing_jobs(self):
        job_queue = MagicMock()
        existing_job = MagicMock()
        job_queue.get_jobs_by_name.return_value = [existing_job]

        profile = _make_profile()
        schedule_eating_window_jobs(
            job_queue, 123, profile,
            MagicMock(), MagicMock(), MagicMock(),
            MagicMock(), MagicMock(),
        )

        existing_job.schedule_removal.assert_called()

    def test_schedules_two_daily_jobs(self):
        job_queue = MagicMock()
        job_queue.get_jobs_by_name.return_value = []

        profile = _make_profile()
        schedule_eating_window_jobs(
            job_queue, 123, profile,
            MagicMock(), MagicMock(), MagicMock(),
            MagicMock(), MagicMock(),
        )

        assert job_queue.run_daily.call_count == 2

        calls = job_queue.run_daily.call_args_list
        names = [c[1]["name"] for c in calls]
        assert "window_123_warning" in names
        assert "window_123_close" in names

    def test_passes_user_repo_to_both_jobs(self):
        job_queue = MagicMock()
        job_queue.get_jobs_by_name.return_value = []
        mock_user_repo = MagicMock()

        profile = _make_profile()
        schedule_eating_window_jobs(
            job_queue, 123, profile,
            mock_user_repo, MagicMock(), MagicMock(),
            MagicMock(), MagicMock(),
        )

        calls = job_queue.run_daily.call_args_list
        for call in calls:
            assert call[1]["data"]["user_repo"] is mock_user_repo
