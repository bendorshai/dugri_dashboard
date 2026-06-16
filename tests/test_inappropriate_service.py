"""
test_inappropriate_service.py - TDD tests for InappropriateService.

# ============================================================================
# SPEC
# ============================================================================
#
# InappropriateService records strikes when messages are classified as
# inappropriate, logs them permanently, and bans after 3 strikes.
#
# record_strike(tid, message_text, profile) -> dict:
#   - Pushes Strike to user doc (reason="inappropriate_message")
#   - Logs message permanently to inappropriate_logs collection
#   - Returns {"action": "strike", "strike_number": N} for strikes 1-2
#   - Returns {"action": "ban", "logs": [...]} on 3rd strike
#   - Sets banned_at on user doc on 3rd strike
#
# format_ban_message(logs, gender) -> str:
#   - Builds numbered list of inappropriate messages with dates
#   - Uses gendered ban template
#
# is_banned(profile) -> bool:
#   - True if profile.banned_at is not None
#
# ============================================================================
"""

import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.profile import Strike, User
from services.inappropriate_service import InappropriateService


def _make_service():
    user_repo = MagicMock()
    inappropriate_log_repo = MagicMock()
    return InappropriateService(user_repo, inappropriate_log_repo), user_repo, inappropriate_log_repo


def _make_profile(inappropriate_strike_count=0, banned_at=None):
    strikes = []
    for i in range(inappropriate_strike_count):
        strikes.append(Strike(
            reason="inappropriate_message",
            detail=f"bad message {i + 1}",
            source="message_classifier",
            created_at=datetime(2026, 6, 10 + i, tzinfo=timezone.utc),
        ))
    return User(
        email="test@test.com",
        telegram_user_id=123,
        strikes=strikes,
        banned_at=banned_at,
    )


class TestRecordStrike:
    def test_first_strike_records_and_returns_strike(self):
        svc, user_repo, log_repo = _make_service()
        profile = _make_profile(inappropriate_strike_count=0)

        result = svc.record_strike(123, "לך תזדיין", profile)

        assert result["action"] == "strike"
        assert result["strike_number"] == 1
        user_repo.push_to_list.assert_called_once()
        args = user_repo.push_to_list.call_args[0]
        assert args[0] == 123
        assert args[1] == "strikes"
        assert args[2]["reason"] == "inappropriate_message"
        log_repo.log.assert_called_once_with(123, "לך תזדיין")

    def test_second_strike_returns_strike(self):
        svc, user_repo, log_repo = _make_service()
        profile = _make_profile(inappropriate_strike_count=1)

        result = svc.record_strike(123, "תראה לי בלי בגדים", profile)

        assert result["action"] == "strike"
        assert result["strike_number"] == 2
        user_repo.push_to_list.assert_called_once()
        log_repo.log.assert_called_once()

    def test_third_strike_triggers_ban(self):
        svc, user_repo, log_repo = _make_service()
        profile = _make_profile(inappropriate_strike_count=2)
        log_repo.get_by_user.return_value = [
            {"message_text": "msg1", "created_at": datetime(2026, 6, 10, tzinfo=timezone.utc)},
            {"message_text": "msg2", "created_at": datetime(2026, 6, 11, tzinfo=timezone.utc)},
            {"message_text": "msg3", "created_at": datetime(2026, 6, 12, tzinfo=timezone.utc)},
        ]

        result = svc.record_strike(123, "third bad message", profile)

        assert result["action"] == "ban"
        assert len(result["logs"]) == 3
        user_repo.update_fields.assert_called_once()
        ban_fields = user_repo.update_fields.call_args[0][1]
        assert "banned_at" in ban_fields

    def test_other_strike_reasons_dont_count(self):
        """Strikes from other sources (e.g. malicious_feedback_reaction) are not counted."""
        svc, user_repo, log_repo = _make_service()
        profile = _make_profile(inappropriate_strike_count=0)
        # Add 2 strikes with different reason
        profile.strikes.append(Strike(
            reason="malicious_feedback_reaction",
            detail="some prompt injection",
            source="feedback_service",
        ))
        profile.strikes.append(Strike(
            reason="malicious_feedback_reaction",
            detail="another attempt",
            source="feedback_service",
        ))

        result = svc.record_strike(123, "לך תזדיין", profile)

        assert result["action"] == "strike"
        assert result["strike_number"] == 1  # only counts inappropriate_message

    def test_strike_detail_truncated(self):
        svc, user_repo, log_repo = _make_service()
        profile = _make_profile(inappropriate_strike_count=0)
        long_message = "א" * 500

        svc.record_strike(123, long_message, profile)

        args = user_repo.push_to_list.call_args[0]
        assert len(args[2]["detail"]) <= 200


class TestFormatBanMessage:
    def test_format_ban_message_male(self):
        svc, _, _ = _make_service()
        logs = [
            {"message_text": "הודעה ראשונה", "created_at": datetime(2026, 6, 10, 14, 30, tzinfo=timezone.utc)},
            {"message_text": "הודעה שנייה", "created_at": datetime(2026, 6, 11, 9, 0, tzinfo=timezone.utc)},
            {"message_text": "הודעה שלישית", "created_at": datetime(2026, 6, 12, 18, 45, tzinfo=timezone.utc)},
        ]

        result = svc.format_ban_message(logs, "male")

        assert "הודעה ראשונה" in result
        assert "הודעה שנייה" in result
        assert "הודעה שלישית" in result
        assert "הופסק" in result or "לצמיתות" in result

    def test_format_ban_message_female(self):
        svc, _, _ = _make_service()
        logs = [
            {"message_text": "msg1", "created_at": datetime(2026, 6, 10, tzinfo=timezone.utc)},
            {"message_text": "msg2", "created_at": datetime(2026, 6, 11, tzinfo=timezone.utc)},
            {"message_text": "msg3", "created_at": datetime(2026, 6, 12, tzinfo=timezone.utc)},
        ]

        result = svc.format_ban_message(logs, "female")

        assert "תשמעי" in result


class TestIsBanned:
    def test_is_banned_true(self):
        svc, _, _ = _make_service()
        profile = _make_profile(banned_at=datetime(2026, 6, 12, tzinfo=timezone.utc))
        assert svc.is_banned(profile) is True

    def test_is_banned_false(self):
        svc, _, _ = _make_service()
        profile = _make_profile()
        assert svc.is_banned(profile) is False
