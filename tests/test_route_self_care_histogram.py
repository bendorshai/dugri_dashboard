"""
test_route_self_care_histogram - TDD tests for histogram update on self-care logging.

Expected behavior:
- route_self_care normalizes the description via GPT and increments the histogram
- Without analyzer (backward compat), self-care is still logged normally
- If normalization fails, self-care is still logged (no error to user)
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from services.message_router_service import MessageRouterService
from services.habit_service import HabitService
from repositories.user_repository import UserRepository


class TestRouteSelfCareHistogram:
    def _make_router(self, analyzer=None, user_repo=None):
        habit = MagicMock(spec=HabitService)
        qa = MagicMock()
        help_svc = MagicMock()
        return MessageRouterService(
            habit, qa, help_svc,
            analyzer=analyzer,
            user_repo=user_repo,
        )

    def test_normalizes_and_increments(self):
        """When analyzer succeeds, histogram is incremented with normalized name."""
        analyzer = MagicMock()
        analyzer.normalize_self_care_activity.return_value = "הליכה לים"
        user_repo = MagicMock(spec=UserRepository)

        router = self._make_router(analyzer=analyzer, user_repo=user_repo)
        result = router.route_self_care(123, "הלכתי לים עם המשפחה", "09/06/2026")

        analyzer.normalize_self_care_activity.assert_called_once_with("הלכתי לים עם המשפחה")
        user_repo.increment_activity.assert_called_once_with(123, "הליכה לים")
        assert result.light_confirmation

    def test_without_analyzer_still_logs(self):
        """Backward compat: no analyzer -> self-care still logged, no crash."""
        router = self._make_router(analyzer=None, user_repo=None)
        result = router.route_self_care(123, "הלכתי לים", "09/06/2026")

        router._habit.log_self_care.assert_called_once()
        assert result.light_confirmation

    def test_normalization_failure_still_logs(self):
        """GPT failure -> self-care still logged, histogram not updated."""
        analyzer = MagicMock()
        analyzer.normalize_self_care_activity.return_value = None
        user_repo = MagicMock(spec=UserRepository)

        router = self._make_router(analyzer=analyzer, user_repo=user_repo)
        result = router.route_self_care(123, "הלכתי לים", "09/06/2026")

        router._habit.log_self_care.assert_called_once()
        user_repo.increment_activity.assert_not_called()
        assert result.light_confirmation
