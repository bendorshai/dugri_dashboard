from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Stub heavy imports
for mod in [
    "telegram", "telegram.ext",
    "pymongo", "openai", "gspread",
    "google", "google.oauth2", "google.oauth2.service_account",
]:
    sys.modules.setdefault(mod, MagicMock())

from scheduler import schedule_eating_window_jobs


class TestScheduleEatingWindowJobs:
    def test_cancels_existing_jobs(self):
        job_queue = MagicMock()
        existing_job = MagicMock()
        job_queue.get_jobs_by_name.return_value = [existing_job]

        profile = {
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }

        schedule_eating_window_jobs(
            job_queue, 123, profile,
            MagicMock(), MagicMock(), MagicMock(),
        )

        existing_job.schedule_removal.assert_called()

    def test_schedules_two_daily_jobs(self):
        job_queue = MagicMock()
        job_queue.get_jobs_by_name.return_value = []

        profile = {
            "eating_window_start": "08:00",
            "eating_window_end": "20:00",
            "timezone": "Asia/Jerusalem",
        }

        schedule_eating_window_jobs(
            job_queue, 123, profile,
            MagicMock(), MagicMock(), MagicMock(),
        )

        assert job_queue.run_daily.call_count == 2

        calls = job_queue.run_daily.call_args_list
        names = [c[1]["name"] for c in calls]
        assert "window_123_warning" in names
        assert "window_123_close" in names
