"""
test_phase4 — TDD tests for Phase 4: feedback, trial, tone.
"""

import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

for mod in [
    "telegram", "telegram.ext",
    "pymongo", "openai",
]:
    sys.modules.setdefault(mod, MagicMock())

from models.profile import UserProfile, Targets
from services.trial_service import TrialService, TRIAL_DAYS
from services.feedback_service import FeedbackService
from repositories.user_repository import UserRepository
from repositories.food_repository import FoodRepository
from repositories.feedback_repository import WeeklyFeedbackRepository


def _make_profile(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123, "targets": Targets(calories=2000, protein=150)}
    defaults.update(kwargs)
    return UserProfile(**defaults)


# ---------------------------------------------------------------------------
# TrialService
# ---------------------------------------------------------------------------

class TestTrialService:
    def _make_service(self):
        repo = MagicMock(spec=UserRepository)
        return TrialService(repo), repo

    def test_expire_after_21_days(self):
        svc, repo = self._make_service()
        started = datetime.now(timezone.utc) - timedelta(days=22)
        profile = _make_profile(subscription_status="trial_active", trial_started_at=started)
        now = datetime.now(timezone.utc)

        result = svc.check_and_expire(profile, now)
        assert result is True
        repo.update_fields.assert_called_once()
        assert repo.update_fields.call_args[0][1]["subscription_status"] == "trial_ended"

    def test_no_expire_before_21_days(self):
        svc, repo = self._make_service()
        started = datetime.now(timezone.utc) - timedelta(days=10)
        profile = _make_profile(subscription_status="trial_active", trial_started_at=started)
        now = datetime.now(timezone.utc)

        result = svc.check_and_expire(profile, now)
        assert result is False
        repo.update_fields.assert_not_called()

    def test_is_blocked_when_trial_ended(self):
        svc, _ = self._make_service()
        profile = _make_profile(subscription_status="trial_ended")
        assert svc.is_blocked(profile) is True

    def test_not_blocked_when_paid(self):
        svc, _ = self._make_service()
        profile = _make_profile(subscription_status="paid")
        assert svc.is_blocked(profile) is False

    def test_not_blocked_when_trial_active(self):
        svc, _ = self._make_service()
        profile = _make_profile(subscription_status="trial_active")
        assert svc.is_blocked(profile) is False

    def test_no_expire_when_not_trial_active(self):
        svc, repo = self._make_service()
        profile = _make_profile(subscription_status="paid")
        result = svc.check_and_expire(profile, datetime.now(timezone.utc))
        assert result is False

    def test_blocked_message_contains_price(self):
        svc, _ = self._make_service()
        msg = svc.get_blocked_message()
        assert "47" in msg


# ---------------------------------------------------------------------------
# FeedbackService
# ---------------------------------------------------------------------------

class TestFeedbackService:
    def _make_service(self):
        analyzer = MagicMock()
        food_repo = MagicMock(spec=FoodRepository)
        user_repo = MagicMock(spec=UserRepository)
        feedback_repo = MagicMock(spec=WeeklyFeedbackRepository)

        food_repo.get_by_user_and_dates.return_value = [
            MagicMock(date="05/05/2026", time="12:00", description="test", calories=500, protein=30),
        ]
        feedback_repo.get_recent.return_value = []
        analyzer.generate_weekly_feedback.return_value = {"feedback_text": "עובד!"}

        svc = FeedbackService(analyzer, food_repo, user_repo, feedback_repo)
        return svc, analyzer, food_repo, user_repo, feedback_repo

    def test_give_feedback_first_time_has_full_closing(self):
        svc, _, _, _, _ = self._make_service()
        result = svc.give_feedback(123, "05/05/2026", 2000, 150, None, is_first_feedback=True)
        assert "עובד!" in result
        assert "לומדים להכיר" in result

    def test_give_feedback_subsequent_has_terse_closing(self):
        svc, _, _, _, _ = self._make_service()
        result = svc.give_feedback(123, "05/05/2026", 2000, 150, None, is_first_feedback=False)
        assert "עובד!" in result
        assert "לומדים להכיר" not in result
        assert "עבד לך" in result or "יותר מדי" in result

    def test_give_feedback_saves_to_repo(self):
        svc, _, _, _, feedback_repo = self._make_service()
        svc.give_feedback(123, "05/05/2026", 2000, 150, None, is_first_feedback=False)
        feedback_repo.save.assert_called_once()

    def test_give_feedback_no_entries(self):
        svc, _, food_repo, _, _ = self._make_service()
        food_repo.get_by_user_and_dates.return_value = []
        result = svc.give_feedback(123, "05/05/2026", 2000, 150, None, is_first_feedback=True)
        assert "אין נתונים" in result

    def test_process_reaction_saves_steering(self):
        svc, analyzer, _, user_repo, _ = self._make_service()
        analyzer.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="updated steering"))]
        )
        result = svc.process_reaction(123, "פחות מספרים", "old steering")
        user_repo.update_fields.assert_called_once()
        call_fields = user_repo.update_fields.call_args[0][1]
        assert call_fields["feedback_steering_prompt"] == "updated steering"

    def test_is_first_feedback_true_when_empty(self):
        svc, _, _, _, feedback_repo = self._make_service()
        feedback_repo.get_recent.return_value = []
        assert svc.is_first_feedback(123) is True

    def test_is_first_feedback_false_when_has_history(self):
        svc, _, _, _, feedback_repo = self._make_service()
        feedback_repo.get_recent.return_value = [{"feedback_text": "past"}]
        assert svc.is_first_feedback(123) is False

    def test_should_offer_weekly_when_never_offered(self):
        svc, _, _, _, _ = self._make_service()
        assert svc.should_offer_weekly(None, datetime.now(timezone.utc)) is True

    def test_should_offer_weekly_after_7_days(self):
        svc, _, _, _, _ = self._make_service()
        last = datetime.now(timezone.utc) - timedelta(days=8)
        assert svc.should_offer_weekly(last, datetime.now(timezone.utc)) is True

    def test_should_not_offer_weekly_before_7_days(self):
        svc, _, _, _, _ = self._make_service()
        last = datetime.now(timezone.utc) - timedelta(days=3)
        assert svc.should_offer_weekly(last, datetime.now(timezone.utc)) is False
