"""
test_self_knowledge — TDD tests for self-knowledge feature.

Tests HelpService (knowledge doc + conversation history + structured response),
FeatureRequestRepository (knowledge gap logging),
and MessageRouterService integration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

import pytest
from pydantic import BaseModel

from services.help_service import HelpService, HelpResponse
from repositories.feature_request_repository import FeatureRequestRepository
from services.message_router_service import MessageRouterService, RouteResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_collection():
    return MagicMock()


def _make_analyzer_mock():
    analyzer = MagicMock()
    analyzer.client = MagicMock()
    return analyzer


def _make_help_response(text: str = "אני בוט.", knowledge_gap: bool = False):
    return HelpResponse(response_text=text, knowledge_gap=knowledge_gap)


SAMPLE_MESSAGES = [
    {"role": "bot", "text": "מה אכלת היום?", "timestamp": "2026-06-06T10:00:00"},
    {"role": "user", "text": "שווארמה בלאפה", "timestamp": "2026-06-06T10:01:00"},
    {"role": "bot", "text": "רשמתי. 650 קלוריות, 40 חלבון.", "timestamp": "2026-06-06T10:01:05"},
]


# ---------------------------------------------------------------------------
# HelpService
# ---------------------------------------------------------------------------

class TestHelpService:
    def test_loads_knowledge_doc_at_init(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("# ידע עצמי\nדוגרי הוא חבר.", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        service = HelpService(analyzer, knowledge_path=doc)

        assert "דוגרי הוא חבר" in service._knowledge_doc

    def test_works_without_knowledge_path(self):
        analyzer = _make_analyzer_mock()
        service = HelpService(analyzer)
        assert service._knowledge_doc == ""

    def test_works_with_missing_knowledge_file(self, tmp_path):
        missing = tmp_path / "nonexistent.md"
        analyzer = _make_analyzer_mock()
        service = HelpService(analyzer, knowledge_path=missing)
        assert service._knowledge_doc == ""

    def test_system_prompt_contains_knowledge_doc(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("דוגרי הוא חבר ישראלי.", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = _make_help_response()
        analyzer.answer_help.return_value = mock_response

        service = HelpService(analyzer, knowledge_path=doc)
        service.answer("מי אתה?")

        call_args = analyzer.answer_help.call_args
        messages = call_args[0][0]
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "דוגרי הוא חבר ישראלי" in system_msg["content"]

    def test_includes_conversation_history(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("ידע עצמי", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = _make_help_response()
        analyzer.answer_help.return_value = mock_response

        service = HelpService(analyzer, knowledge_path=doc)
        service.answer("למה רק 5 הרגלים?", recent_messages=SAMPLE_MESSAGES)

        call_args = analyzer.answer_help.call_args
        messages = call_args[0][0]

        # system + 3 history messages + 1 user question = 5
        assert len(messages) == 5
        assert messages[1]["role"] == "assistant"  # bot -> assistant
        assert messages[1]["content"] == "מה אכלת היום?"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "שווארמה בלאפה"
        assert messages[4]["role"] == "user"
        assert messages[4]["content"] == "למה רק 5 הרגלים?"

    def test_returns_structured_help_response(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("ידע", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = HelpResponse(
            response_text="כי 5 שבאמת משנים עדיפים על 15.",
            knowledge_gap=False,
        )
        analyzer.answer_help.return_value = mock_response

        service = HelpService(analyzer, knowledge_path=doc)
        result = service.answer("למה רק 5 הרגלים?")

        assert isinstance(result, HelpResponse)
        assert result.response_text == "כי 5 שבאמת משנים עדיפים על 15."
        assert result.knowledge_gap is False

    def test_returns_knowledge_gap_true(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("ידע", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = HelpResponse(
            response_text="לא יודע לענות על זה.",
            knowledge_gap=True,
        )
        analyzer.answer_help.return_value = mock_response

        service = HelpService(analyzer, knowledge_path=doc)
        result = service.answer("למה אתה לא עוקב אחרי רגשות?")

        assert result.knowledge_gap is True

    def test_fallback_on_parse_none(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("ידע", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = None
        analyzer.answer_help.return_value = mock_response

        service = HelpService(analyzer, knowledge_path=doc)
        result = service.answer("שאלה כלשהי")

        assert isinstance(result, HelpResponse)
        assert result.response_text != ""

    def test_fallback_on_exception(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("ידע", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        analyzer.answer_help.side_effect = Exception("API error")

        service = HelpService(analyzer, knowledge_path=doc)
        result = service.answer("שאלה כלשהי")

        assert isinstance(result, HelpResponse)
        assert result.response_text != ""
        assert result.knowledge_gap is False

    def test_uses_answer_help_method(self, tmp_path):
        doc = tmp_path / "knowledge.md"
        doc.write_text("ידע", encoding="utf-8")

        analyzer = _make_analyzer_mock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = _make_help_response()
        analyzer.answer_help.return_value = mock_response

        service = HelpService(analyzer, knowledge_path=doc)
        service.answer("שאלה")

        analyzer.answer_help.assert_called_once()
        call_args = analyzer.answer_help.call_args
        assert call_args[0][1] is HelpResponse
        assert call_args[1]["max_tokens"] == 1000


# ---------------------------------------------------------------------------
# FeatureRequestRepository
# ---------------------------------------------------------------------------

class TestFeatureRequestRepository:
    def test_log_inserts_document(self):
        col = _make_mock_collection()
        repo = FeatureRequestRepository(col)

        repo.log(
            telegram_user_id=123,
            question_text="למה אתה לא עוקב אחרי רגשות?",
            bot_response="לא יודע לענות.",
        )

        col.insert_one.assert_called_once()
        doc = col.insert_one.call_args[0][0]
        assert doc["telegram_user_id"] == 123
        assert doc["question_text"] == "למה אתה לא עוקב אחרי רגשות?"
        assert doc["bot_response"] == "לא יודע לענות."
        assert isinstance(doc["timestamp"], datetime)

    def test_creates_ttl_index(self):
        col = _make_mock_collection()
        FeatureRequestRepository(col)

        col.create_index.assert_called_once_with(
            "timestamp",
            expireAfterSeconds=90 * 24 * 60 * 60,
        )


# ---------------------------------------------------------------------------
# MessageRouterService — route_help integration
# ---------------------------------------------------------------------------

class TestRouteHelpIntegration:
    def _make_router(self, help_response, feature_request_repo=None):
        help_service = MagicMock()
        help_service.answer.return_value = help_response
        router = MessageRouterService(
            habit_service=MagicMock(),
            qa_service=MagicMock(),
            help_service=help_service,
            feature_request_repo=feature_request_repo,
        )
        return router, help_service

    def test_passes_recent_messages_to_help_service(self):
        router, help_svc = self._make_router(_make_help_response())

        router.route_help("מי אתה?", recent_messages=SAMPLE_MESSAGES, telegram_user_id=123)

        help_svc.answer.assert_called_once_with("מי אתה?", recent_messages=SAMPLE_MESSAGES)

    def test_logs_feature_request_on_knowledge_gap(self):
        repo = MagicMock()
        router, _ = self._make_router(
            _make_help_response("לא יודע.", knowledge_gap=True),
            feature_request_repo=repo,
        )

        router.route_help("למה לא רגשות?", recent_messages=None, telegram_user_id=456)

        repo.log.assert_called_once_with(
            telegram_user_id=456,
            question_text="למה לא רגשות?",
            bot_response="לא יודע.",
            request_type="knowledge_gap",
            chat_history=None,
        )

    def test_no_log_when_no_knowledge_gap(self):
        repo = MagicMock()
        router, _ = self._make_router(
            _make_help_response("כי 5 מספיק.", knowledge_gap=False),
            feature_request_repo=repo,
        )

        router.route_help("למה 5?", recent_messages=None, telegram_user_id=456)

        repo.log.assert_not_called()

    def test_no_log_when_no_repo(self):
        router, _ = self._make_router(
            _make_help_response("תשובה.", knowledge_gap=True),
            feature_request_repo=None,
        )

        # Should not raise
        result = router.route_help("שאלה", recent_messages=None, telegram_user_id=123)
        assert isinstance(result, RouteResult)

    def test_silent_error_on_repo_failure(self):
        repo = MagicMock()
        repo.log.side_effect = Exception("DB error")
        router, _ = self._make_router(
            _make_help_response("תשובה.", knowledge_gap=True),
            feature_request_repo=repo,
        )

        # Should not raise, response still returned
        result = router.route_help("שאלה", recent_messages=None, telegram_user_id=123)
        assert result.response_text == "תשובה."

    def test_returns_route_result(self):
        router, _ = self._make_router(_make_help_response("אני בוט."))

        result = router.route_help("מי אתה?", recent_messages=None, telegram_user_id=123)

        assert isinstance(result, RouteResult)
        assert result.response_text == "אני בוט."
