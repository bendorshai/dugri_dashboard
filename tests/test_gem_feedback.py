"""
test_gem_feedback.py - Tests for gem feedback (like/dislike) handling.

Expected behavior:
- Like decreases threshold by 1% (GEM_THRESHOLD_LIKE_DELTA = -0.01)
- Dislike increases threshold by 10% (GEM_THRESHOLD_DISLIKE_DELTA = 0.10)
- Floor (-0.15) and ceiling (0.30) are respected
- Feedback is recorded in gem_state.feedbacks
- Keyboard has like and dislike buttons with correct callback data
"""

from unittest.mock import MagicMock

from models.profile import User, GemState


def _make_user(**kwargs) -> User:
    from datetime import datetime, timezone
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "trial_started_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return User(**defaults)


def _make_service():
    from services.gem_service import GemService
    user_repo = MagicMock()
    pattern_detector = MagicMock()
    toggle_service = MagicMock()
    analyzer = MagicMock()
    svc = GemService(user_repo, pattern_detector, toggle_service, analyzer)
    return svc, user_repo


class TestFeedbackThreshold:

    def test_like_decreases_by_1_percent(self):
        svc, user_repo = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=0.0))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "like")
        fields = user_repo.update_fields.call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] == -0.01

    def test_dislike_increases_by_10_percent(self):
        svc, user_repo = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=0.0))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "dislike")
        fields = user_repo.update_fields.call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] == 0.10

    def test_floor_prevents_going_below(self):
        svc, user_repo = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=-0.15))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "like")
        fields = user_repo.update_fields.call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] == -0.15

    def test_ceiling_prevents_going_above(self):
        svc, user_repo = _make_service()
        user = _make_user(gem_state=GemState(threshold_adjustment=0.25))
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "dislike")
        fields = user_repo.update_fields.call_args[0][1]
        assert fields["gem_state.threshold_adjustment"] == 0.30

    def test_feedback_recorded(self):
        svc, user_repo = _make_service()
        user = _make_user()
        user_repo.get.return_value = user
        svc.handle_feedback(123, "gem_01", "like")
        push_args = user_repo.push_to_list.call_args
        assert push_args[0][1] == "gem_state.feedbacks"
        feedback = push_args[0][2]
        assert feedback["gem_id"] == "gem_01"
        assert feedback["reaction"] == "like"


class TestGemKeyboard:

    def test_keyboard_has_like_dislike(self):
        from keyboards import make_gem_feedback_keyboard
        kb = make_gem_feedback_keyboard("gem_01")
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 2
        assert "gem_like_gem_01" in buttons[0].callback_data
        assert "gem_dislike_gem_01" in buttons[1].callback_data
