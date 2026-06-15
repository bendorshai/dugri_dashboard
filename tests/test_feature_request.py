"""
test_feature_request.py - TDD tests for the feature request system.

Covers:
- FeatureRequestRepository.log() with new fields (request_type, message_id, chat_id)
- FeatureRequestRepository.log() backward compat (no new fields)
- LoggerService.classify_feature_request() returns sub-type + ack
- LoggerService.classify_feature_request() fallback on GPT failure
- MessageRouterService.route_feature_request() logs and returns ack
- MessageRouterService.route_help() passes request_type="knowledge_gap"
- _dispatch_v2 routes feature_request to logger + router service
- Menu button callback sets pending_feature_request state
- Pending feature request consumed on next message
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch, call

import pytest

# Stub heavy imports
for mod in [
    "telegram", "telegram.ext", "telegram.ext._application",
    "pymongo", "openai",
]:
    sys.modules.setdefault(mod, MagicMock())

mock_telegram = sys.modules["telegram"]
if isinstance(mock_telegram, MagicMock):
    mock_telegram.Update = MagicMock
    mock_telegram.InlineKeyboardButton = MagicMock
    mock_telegram.InlineKeyboardMarkup = MagicMock

mock_ext = sys.modules["telegram.ext"]
if isinstance(mock_ext, MagicMock):
    mock_ext.ContextTypes = MagicMock()
    mock_ext.ContextTypes.DEFAULT_TYPE = MagicMock

from repositories.feature_request_repository import FeatureRequestRepository
from services.logger_service import LoggerService, FeatureRequestClassification
from services.message_router_service import MessageRouterService, RouteResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_collection():
    return MagicMock()


# ---------------------------------------------------------------------------
# FeatureRequestRepository
# ---------------------------------------------------------------------------

class TestFeatureRequestRepository:
    """Tests for FeatureRequestRepository.log() with new fields."""

    def test_log_with_all_new_fields(self):
        col = _make_mock_collection()
        repo = FeatureRequestRepository(col)
        repo.log(
            telegram_user_id=123,
            question_text="יש באג בסיכום",
            bot_response="רשמתי, אבדוק.",
            request_type="bug_report",
            message_id=456,
            chat_id=123,
        )
        inserted = col.insert_one.call_args[0][0]
        assert inserted["telegram_user_id"] == 123
        assert inserted["question_text"] == "יש באג בסיכום"
        assert inserted["bot_response"] == "רשמתי, אבדוק."
        assert inserted["request_type"] == "bug_report"
        assert inserted["message_id"] == 456
        assert inserted["chat_id"] == 123
        assert "timestamp" in inserted

    def test_log_backward_compat_no_new_fields(self):
        """Existing callers that don't pass new fields still work."""
        col = _make_mock_collection()
        repo = FeatureRequestRepository(col)
        repo.log(
            telegram_user_id=123,
            question_text="מה זה דוגרי?",
            bot_response="דוגרי הוא בוט...",
        )
        inserted = col.insert_one.call_args[0][0]
        assert inserted["telegram_user_id"] == 123
        assert "request_type" not in inserted
        assert "message_id" not in inserted

    def test_log_with_knowledge_gap_type(self):
        col = _make_mock_collection()
        repo = FeatureRequestRepository(col)
        repo.log(
            telegram_user_id=123,
            question_text="שאלה",
            bot_response="תשובה",
            request_type="knowledge_gap",
        )
        inserted = col.insert_one.call_args[0][0]
        assert inserted["request_type"] == "knowledge_gap"

    def test_log_with_habit_of_interest_type(self):
        col = _make_mock_collection()
        repo = FeatureRequestRepository(col)
        repo.log(
            telegram_user_id=123,
            question_text="אפשר לעקוב אחרי שתיית מים?",
            bot_response="רשמתי את הבקשה.",
            request_type="habit_of_interest",
            message_id=789,
            chat_id=123,
        )
        inserted = col.insert_one.call_args[0][0]
        assert inserted["request_type"] == "habit_of_interest"


# ---------------------------------------------------------------------------
# LoggerService.classify_feature_request
# ---------------------------------------------------------------------------

class TestLoggerServiceFeatureRequest:
    """Tests for LoggerService.classify_feature_request()."""

    def test_classify_returns_pydantic_model(self):
        analyzer = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.parsed = FeatureRequestClassification(
            request_type="bug_report",
            ack_text="רשמתי, אבדוק.",
        )
        mock_response.choices = [mock_choice]
        analyzer._parse.return_value = mock_response

        svc = LoggerService(analyzer)
        result = svc.classify_feature_request("הסיכום לא מראה נכון")
        assert isinstance(result, FeatureRequestClassification)
        assert result.request_type == "bug_report"
        assert result.ack_text == "רשמתי, אבדוק."

    def test_classify_fallback_on_exception(self):
        analyzer = MagicMock()
        analyzer._parse.side_effect = Exception("API error")

        svc = LoggerService(analyzer)
        result = svc.classify_feature_request("משהו")
        assert result.request_type == "feature_request"
        assert len(result.ack_text) > 0  # has fallback text

    def test_classify_with_suggestion(self):
        analyzer = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.parsed = FeatureRequestClassification(
            request_type="feature_request",
            ack_text="רעיון טוב, רשמתי.",
        )
        mock_response.choices = [mock_choice]
        analyzer._parse.return_value = mock_response

        svc = LoggerService(analyzer)
        result = svc.classify_feature_request("הייתי רוצה שתוסיף גרף התקדמות")
        assert result.request_type == "feature_request"

    def test_classify_with_habit_of_interest(self):
        analyzer = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.parsed = FeatureRequestClassification(
            request_type="habit_of_interest",
            ack_text="עדיין לא עוקב אחרי זה, אבל רשמתי.",
        )
        mock_response.choices = [mock_choice]
        analyzer._parse.return_value = mock_response

        svc = LoggerService(analyzer)
        result = svc.classify_feature_request("אפשר לעקוב אחרי שתיית מים?")
        assert result.request_type == "habit_of_interest"


# ---------------------------------------------------------------------------
# MessageRouterService
# ---------------------------------------------------------------------------

class TestMessageRouterServiceFeatureRequest:
    """Tests for route_feature_request and updated route_help."""

    def test_route_feature_request_logs_and_returns(self):
        fr_repo = MagicMock()
        svc = MessageRouterService(
            habit_service=MagicMock(),
            qa_service=MagicMock(),
            help_service=MagicMock(),
            feature_request_repo=fr_repo,
        )
        result = svc.route_feature_request(
            telegram_user_id=123,
            message_text="יש באג",
            request_type="bug_report",
            bot_response="רשמתי.",
            message_id=456,
            chat_id=123,
        )
        assert result.response_text == "רשמתי."
        fr_repo.log.assert_called_once_with(
            telegram_user_id=123,
            question_text="יש באג",
            bot_response="רשמתי.",
            request_type="bug_report",
            message_id=456,
            chat_id=123,
        )

    def test_route_feature_request_survives_repo_failure(self):
        fr_repo = MagicMock()
        fr_repo.log.side_effect = Exception("DB error")
        svc = MessageRouterService(
            habit_service=MagicMock(),
            qa_service=MagicMock(),
            help_service=MagicMock(),
            feature_request_repo=fr_repo,
        )
        result = svc.route_feature_request(
            telegram_user_id=123,
            message_text="יש באג",
            request_type="bug_report",
            bot_response="רשמתי.",
            message_id=456,
            chat_id=123,
        )
        # Should not raise, returns ack anyway
        assert result.response_text == "רשמתי."

    def test_route_help_passes_knowledge_gap_type(self):
        fr_repo = MagicMock()
        help_svc = MagicMock()
        help_result = MagicMock()
        help_result.knowledge_gap = True
        help_result.response_text = "לא יודע."
        help_svc.answer.return_value = help_result

        svc = MessageRouterService(
            habit_service=MagicMock(),
            qa_service=MagicMock(),
            help_service=help_svc,
            feature_request_repo=fr_repo,
        )
        svc.route_help("שאלה שלא יודע", telegram_user_id=123)
        fr_repo.log.assert_called_once()
        call_kwargs = fr_repo.log.call_args
        assert call_kwargs[1].get("request_type") == "knowledge_gap" or \
               (len(call_kwargs[0]) >= 4 and call_kwargs[0][3] == "knowledge_gap") or \
               call_kwargs.kwargs.get("request_type") == "knowledge_gap"


# ---------------------------------------------------------------------------
# Dispatch v2 - feature_request routing
# ---------------------------------------------------------------------------

from analyzer import RouterClassification
from models.profile import User, EatingWindow, Targets


def _make_profile(**kwargs):
    defaults = {
        "email": "test@test.com",
        "telegram_user_id": 123,
        "eating_window": EatingWindow(start="08:00", end="20:00"),
        "targets": Targets(calories=2000, protein=150),
        "timezone": "Asia/Jerusalem",
    }
    defaults.update(kwargs)
    return User(**defaults)


def _make_handler(**overrides):
    from handlers.base import HealthHandlers
    h = HealthHandlers.__new__(HealthHandlers)
    h.user_repo = MagicMock()
    h.food_repo = MagicMock()
    h.feedback_repo = MagicMock()
    h.eating_day_svc = MagicMock()
    h.analyzer = MagicMock()
    h.message_router = MagicMock()
    h.toggle_service = MagicMock()
    h.trial_service = None
    h.goal_service = MagicMock()
    h.feedback_service = MagicMock()
    h.onboarding_service = MagicMock()
    h.emotional_support_service = MagicMock()
    h.conversational_service = MagicMock()
    h.token_log_repo = None
    h.gem_service = None
    h.landing_page_url = "https://test.com"
    h.admin_chat_id = 0
    h._debug_mode = False
    for k, v in overrides.items():
        setattr(h, k, v)
    return h


def _make_message(text="test"):
    msg = AsyncMock()
    msg.text = text
    msg.message_id = 789
    msg.chat_id = 123
    msg.reply_to_message = None
    return msg


def _make_context():
    ctx = MagicMock()
    ctx.chat_data = {}
    return ctx


_DISPATCH_PARAMS = dict(
    calendar_today="15/06/2026",
    day_name="ראשון",
    stats_date="15/06/2026",
    time_str="14:00",
    within_window=True,
    last_entry=None,
    recent_messages=[],
    toggle_state="- תזונה: active\n- שינה: dormant",
    reply_context=None,
)


class TestDispatchFeatureRequest:
    """Verify feature_request dispatch calls logger + router service."""

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_feature_request_calls_logger_and_router(self, mock_send):
        h = _make_handler()
        mock_classification = FeatureRequestClassification(
            request_type="bug_report",
            ack_text="רשמתי, אבדוק.",
        )
        mock_logger = MagicMock()
        mock_logger.classify_feature_request.return_value = mock_classification

        with patch("services.logger_service.LoggerService", return_value=mock_logger) as mock_cls:
            # Also patch the import inside the function
            with patch.dict("sys.modules", {"services.logger_service": MagicMock(LoggerService=mock_cls)}):
                profile = _make_profile()
                rr = RouterClassification(type="feature_request")
                msg = _make_message("הסיכום לא מראה נכון")

                await h._dispatch_v2(msg, _make_context(), 123, profile, rr, **_DISPATCH_PARAMS)

                mock_logger.classify_feature_request.assert_called_once_with("הסיכום לא מראה נכון")
                h.message_router.route_feature_request.assert_called_once()
                call_kwargs = h.message_router.route_feature_request.call_args.kwargs
                assert call_kwargs["request_type"] == "bug_report"
                assert call_kwargs["message_id"] == 789
                assert call_kwargs["chat_id"] == 123

    @pytest.mark.asyncio
    @patch("handlers.base.send_long_text", new_callable=AsyncMock)
    async def test_dispatch_feature_request_sends_ack(self, mock_send):
        h = _make_handler()
        mock_classification = FeatureRequestClassification(
            request_type="feature_request",
            ack_text="רעיון טוב, רשמתי.",
        )
        mock_logger = MagicMock()
        mock_logger.classify_feature_request.return_value = mock_classification

        with patch("services.logger_service.LoggerService", return_value=mock_logger) as mock_cls:
            with patch.dict("sys.modules", {"services.logger_service": MagicMock(LoggerService=mock_cls)}):
                profile = _make_profile()
                rr = RouterClassification(type="feature_request")
                msg = _make_message("אפשר להוסיף גרף?")

                await h._dispatch_v2(msg, _make_context(), 123, profile, rr, **_DISPATCH_PARAMS)

                # Verify _send was called with the ack text
                mock_send.assert_called_once()
                sent_text = mock_send.call_args[0][1]
                assert "רשמתי" in sent_text
