"""
test_trial_service - Tests for trial expiry logic.

Covers:
- Config loading: trial_periods.yaml cohort matching, default fallback
- Expiry datetime computation: 19:00 local cutoff after N trial days
  - If raw expiry (trial_started_at + N days) local time is before 19:00 -> same day 19:00
  - If raw expiry local time is >= 19:00 -> next day 19:00
- check_and_expire: status transitions, idempotency
- Edge cases: exactly at 19:00 boundary, one second before/after
"""

import sys
from unittest.mock import MagicMock

for mod in ["telegram", "telegram.ext", "telegram.ext._application", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from datetime import datetime, timezone, timedelta, date, time
from pathlib import Path
import tempfile
import textwrap

import pytz
import pytest

from user_clock import UserClock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ISR = "Asia/Jerusalem"
ISR_TZ = pytz.timezone(ISR)


def _utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=timezone.utc)


def _make_profile(**kwargs):
    """Minimal profile stub with defaults."""
    from models.profile import User
    defaults = dict(
        email="test@example.com",
        telegram_user_id=12345,
        subscription_status="trial_active",
        trial_started_at=_utc(2026, 6, 1, 10, 0, 0),
        timezone=ISR,
    )
    defaults.update(kwargs)
    return User(**defaults)


def _make_repo():
    repo = MagicMock()
    repo.update_fields = MagicMock()
    return repo


def _write_config(tmp_path, yaml_text):
    p = tmp_path / "trial_periods.yaml"
    p.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return p


def _make_service(user_repo=None, config_path=None):
    from services.trial_service import TrialService
    return TrialService(
        user_repo=user_repo or _make_repo(),
        landing_page_url="https://www.dugri.life",
        config_path=config_path,
    )


# ---------------------------------------------------------------------------
# TestGetTrialDays
# ---------------------------------------------------------------------------

class TestGetTrialDays:
    def test_default_config_returns_12(self, tmp_path):
        cfg = _write_config(tmp_path, """\
            cohorts:
              - trial_days: 12
        """)
        svc = _make_service(config_path=cfg)
        profile = _make_profile(trial_started_at=_utc(2026, 6, 10))
        assert svc.get_trial_days(profile) == 12

    def test_matching_cohort_by_date_range(self, tmp_path):
        cfg = _write_config(tmp_path, """\
            cohorts:
              - start_date: "2026-06-01"
                end_date: "2026-07-01"
                trial_days: 14
              - trial_days: 12
        """)
        svc = _make_service(config_path=cfg)
        # User signed up June 15 - matches first cohort
        profile = _make_profile(trial_started_at=_utc(2026, 6, 15))
        assert svc.get_trial_days(profile) == 14

    def test_no_matching_cohort_falls_back_to_default(self, tmp_path):
        cfg = _write_config(tmp_path, """\
            cohorts:
              - start_date: "2026-01-01"
                end_date: "2026-02-01"
                trial_days: 30
              - trial_days: 12
        """)
        svc = _make_service(config_path=cfg)
        # User signed up June 15 - no date range matches, falls back
        profile = _make_profile(trial_started_at=_utc(2026, 6, 15))
        assert svc.get_trial_days(profile) == 12

    def test_trial_started_at_none_returns_default(self, tmp_path):
        cfg = _write_config(tmp_path, """\
            cohorts:
              - trial_days: 12
        """)
        svc = _make_service(config_path=cfg)
        profile = _make_profile(trial_started_at=None)
        assert svc.get_trial_days(profile) == 12


# ---------------------------------------------------------------------------
# TestTrialExpiryDatetime
# ---------------------------------------------------------------------------

class TestTrialExpiryDatetime:
    """The 19:00 local cutoff rule:
    - Add trial_days to trial_started_at in local time
    - If the resulting local time is before 19:00 -> same day 19:00
    - If >= 19:00 -> next day 19:00
    """

    def test_started_morning_expires_day_n_at_1900(self, tmp_path):
        """Started 08:00 local -> raw expiry is day 12 at 08:00 -> same day 19:00."""
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        svc = _make_service(config_path=cfg)
        # June 1 08:00 Israel = June 1 05:00 UTC (IDT = UTC+3)
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 5, 0, 0))
        clock = UserClock(ISR)

        expiry = svc.trial_expiry_dt(profile, clock)
        assert expiry is not None

        # Should be June 13 19:00 Israel = June 13 16:00 UTC
        expiry_local = expiry.astimezone(ISR_TZ)
        assert expiry_local.date() == date(2026, 6, 13)
        assert expiry_local.time() == time(19, 0, 0)
        assert expiry.tzinfo is not None  # UTC-aware

    def test_started_evening_expires_next_day_at_1900(self, tmp_path):
        """Started 20:00 local -> raw expiry is day 12 at 20:00 (>= 19:00) -> next day 19:00."""
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        svc = _make_service(config_path=cfg)
        # June 1 20:00 Israel = June 1 17:00 UTC
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 17, 0, 0))
        clock = UserClock(ISR)

        expiry = svc.trial_expiry_dt(profile, clock)
        expiry_local = expiry.astimezone(ISR_TZ)
        # Raw expiry: June 13 20:00 -> rounds to June 14 19:00
        assert expiry_local.date() == date(2026, 6, 14)
        assert expiry_local.time() == time(19, 0, 0)

    def test_started_at_1859_expires_same_day_1900(self, tmp_path):
        """Started 18:59 local -> raw expiry at 18:59 (< 19:00) -> same day 19:00."""
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        svc = _make_service(config_path=cfg)
        # June 1 18:59 Israel = June 1 15:59 UTC
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 15, 59, 0))
        clock = UserClock(ISR)

        expiry = svc.trial_expiry_dt(profile, clock)
        expiry_local = expiry.astimezone(ISR_TZ)
        assert expiry_local.date() == date(2026, 6, 13)
        assert expiry_local.time() == time(19, 0, 0)

    def test_started_exactly_1900_expires_next_day_1900(self, tmp_path):
        """Started exactly 19:00 local -> raw expiry at 19:00 (>= 19:00) -> next day 19:00."""
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        svc = _make_service(config_path=cfg)
        # June 1 19:00 Israel = June 1 16:00 UTC
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 16, 0, 0))
        clock = UserClock(ISR)

        expiry = svc.trial_expiry_dt(profile, clock)
        expiry_local = expiry.astimezone(ISR_TZ)
        assert expiry_local.date() == date(2026, 6, 14)
        assert expiry_local.time() == time(19, 0, 0)

    def test_trial_started_at_none_returns_none(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        svc = _make_service(config_path=cfg)
        profile = _make_profile(trial_started_at=None)
        clock = UserClock(ISR)

        assert svc.trial_expiry_dt(profile, clock) is None

    def test_result_is_utc_aware(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        svc = _make_service(config_path=cfg)
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 10, 0, 0))
        clock = UserClock(ISR)

        expiry = svc.trial_expiry_dt(profile, clock)
        assert expiry.tzinfo is not None
        # Convert to UTC and verify
        utc_expiry = expiry.astimezone(timezone.utc)
        assert utc_expiry.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# TestCheckAndExpire
# ---------------------------------------------------------------------------

class TestCheckAndExpire:
    def test_not_yet_expired_returns_false(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        repo = _make_repo()
        svc = _make_service(user_repo=repo, config_path=cfg)
        # Started June 1 10:00 Israel, check on June 5 (well before expiry)
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 7, 0, 0))

        result = svc.check_and_expire(profile, _utc(2026, 6, 5, 12, 0, 0))
        assert result is False
        repo.update_fields.assert_not_called()

    def test_just_expired_returns_true_and_flips_status(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        repo = _make_repo()
        svc = _make_service(user_repo=repo, config_path=cfg)
        # Started June 1 08:00 Israel (05:00 UTC) -> expiry June 13 19:00 Israel (16:00 UTC)
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 5, 0, 0))

        # Check at exactly the expiry moment
        result = svc.check_and_expire(profile, _utc(2026, 6, 13, 16, 0, 0))
        assert result is True
        repo.update_fields.assert_called_once()
        call_args = repo.update_fields.call_args
        assert call_args[0][1]["subscription_status"] == "trial_ended"

    def test_already_trial_ended_returns_false(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        repo = _make_repo()
        svc = _make_service(user_repo=repo, config_path=cfg)
        profile = _make_profile(subscription_status="trial_ended")

        result = svc.check_and_expire(profile, _utc(2026, 7, 1))
        assert result is False
        repo.update_fields.assert_not_called()

    def test_trial_pending_returns_false(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        repo = _make_repo()
        svc = _make_service(user_repo=repo, config_path=cfg)
        profile = _make_profile(subscription_status="trial_pending")

        result = svc.check_and_expire(profile, _utc(2026, 7, 1))
        assert result is False
        repo.update_fields.assert_not_called()


# ---------------------------------------------------------------------------
# TestEdgeCasesAt1900
# ---------------------------------------------------------------------------

class TestEdgeCasesAt1900:
    """Second-level precision at the 19:00 boundary."""

    def test_one_second_before_1900_not_expired(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        repo = _make_repo()
        svc = _make_service(user_repo=repo, config_path=cfg)
        # Started June 1 08:00 Israel -> expiry June 13 19:00 Israel = 16:00 UTC
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 5, 0, 0))

        # One second before: June 13 15:59:59 UTC = 18:59:59 Israel
        result = svc.check_and_expire(profile, _utc(2026, 6, 13, 15, 59, 59))
        assert result is False

    def test_exactly_at_1900_expired(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        repo = _make_repo()
        svc = _make_service(user_repo=repo, config_path=cfg)
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 5, 0, 0))

        # Exactly at: June 13 16:00:00 UTC = 19:00:00 Israel
        result = svc.check_and_expire(profile, _utc(2026, 6, 13, 16, 0, 0))
        assert result is True

    def test_one_second_after_1900_expired(self, tmp_path):
        cfg = _write_config(tmp_path, "cohorts:\n  - trial_days: 12")
        repo = _make_repo()
        svc = _make_service(user_repo=repo, config_path=cfg)
        profile = _make_profile(trial_started_at=_utc(2026, 6, 1, 5, 0, 0))

        # One second after: June 13 16:00:01 UTC = 19:00:01 Israel
        result = svc.check_and_expire(profile, _utc(2026, 6, 13, 16, 0, 1))
        assert result is True
