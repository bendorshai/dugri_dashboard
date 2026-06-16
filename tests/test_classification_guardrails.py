"""
test_classification_guardrails.py - Tests for context-aware classification guardrails.

Pure unit tests: no LLM calls, no MongoDB, no mocks needed.
Tests the validate_classification function which is pure logic.

Guardrails gate classifications that are only valid in specific contexts:
- feedback_reaction: only valid when feedback was given within last 2 messages
- correction: only valid when there's a correctable entry in context
- name_declaration: only valid when name is not yet set
- gender_declaration: only valid when gender is not yet set

When gated, classification falls back to 'conversational'.
"""

from __future__ import annotations

import pytest

from classification_guardrails import validate_classification
from models.analyzer_models import RouterClassification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify(rtype, **kwargs):
    return RouterClassification(type=rtype, **kwargs)


def _user_msg(text, classification=None):
    msg = {"role": "user", "text": text, "timestamp": "2026-06-16T00:00:00+00:00"}
    if classification:
        msg["classification"] = classification
    return msg


def _bot_msg(text, classification=None):
    msg = {"role": "bot", "text": text, "timestamp": "2026-06-16T00:00:01+00:00"}
    if classification:
        msg["classification"] = classification
    return msg


# ---------------------------------------------------------------------------
# feedback_reaction guardrail
# ---------------------------------------------------------------------------

class TestFeedbackReactionGuardrail:
    """feedback_reaction is only valid when feedback was given within last 2 messages."""

    def test_no_feedback_in_history_returns_conversational(self):
        """No feedback in recent history -> conversational."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=[
                _bot_msg("שווארמה ≈ 720 קל׳, 38 ג' חלבון", classification="meal"),
                _user_msg("תודה דוגרי"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"

    def test_no_history_at_all_returns_conversational(self):
        """Empty/None history -> conversational."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=None,
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"

    def test_empty_history_returns_conversational(self):
        """Empty list history -> conversational."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"

    def test_feedback_1_message_ago_allowed(self):
        """Feedback is the last bot message -> allowed."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=[
                _bot_msg("💬 הנה הסיכום השבועי שלך...", classification="feedback_request"),
                _user_msg("תודה, מעניין"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "feedback_reaction"

    def test_feedback_2_messages_ago_allowed(self):
        """Feedback with one user+bot exchange after -> still allowed (within 2 messages)."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=[
                _bot_msg("💬 הנה הסיכום השבועי שלך...", classification="feedback_request"),
                _user_msg("מעניין"),
                _bot_msg("תודה, רשמתי. הפידבק הבא יהיה מותאם יותר.", classification="feedback_reaction"),
                _user_msg("עוד משהו על הפידבק"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "feedback_reaction"

    def test_feedback_3_messages_ago_returns_conversational(self):
        """Feedback was 3+ messages ago -> too old, conversational."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=[
                _bot_msg("💬 הנה הסיכום השבועי שלך...", classification="feedback_request"),
                _user_msg("מעניין"),
                _bot_msg("תודה, רשמתי.", classification="feedback_reaction"),
                _user_msg("אכלתי סלט"),
                _bot_msg("סלט ≈ 200 קל׳, 5 ג' חלבון", classification="meal"),
                _user_msg("תודה דוגרי"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"

    def test_fallback_emoji_check_no_classification(self):
        """Old message without classification field but with 💬 emoji -> allowed."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=[
                _bot_msg("💬 הנה הסיכום השבועי שלך..."),  # no classification field
                _user_msg("מעניין"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "feedback_reaction"

    def test_only_user_messages_no_bot_feedback(self):
        """Only user messages in recent history, no bot feedback -> conversational."""
        result = validate_classification(
            _classify("feedback_reaction"),
            recent_messages=[
                _user_msg("שלום"),
                _user_msg("תודה דוגרי"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"


# ---------------------------------------------------------------------------
# correction guardrail
# ---------------------------------------------------------------------------

class TestCorrectionGuardrail:
    """correction is only valid when there's a correctable entry in context."""

    def test_reply_to_food_entry_allowed(self):
        """Telegram reply to food entry (calorie markers in reply_context) -> allowed."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[],
            last_entry=None,
            reply_context="שווארמה בלאפה ≈ 720 קל׳, 38 ג' חלבון",
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_reply_to_habit_entry_allowed(self):
        """Telegram reply to habit entry (e.g. sleep confirmation) -> allowed.

        Habit confirmations don't have calorie markers, but the reply_context
        still signals a reply to an entry. The guardrail should allow any
        reply_context that is present (the router already determined it's a
        correction based on context).
        """
        result = validate_classification(
            _classify("correction"),
            recent_messages=[],
            last_entry=None,
            reply_context="רשמתי שינה ב-23:00.",
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_last_entry_exists_allowed(self):
        """In-memory last_entry present -> allowed."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[],
            last_entry={"description": "שווארמה", "calories": 720, "protein": 38, "entry_id": "abc"},
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_meal_classification_1_message_ago_allowed(self):
        """Bot meal message classified within last 2 messages -> allowed."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[
                _bot_msg("שווארמה ≈ 720 קל׳, 38 ג' חלבון", classification="meal"),
                _user_msg("בלי אורז"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_habit_classification_1_message_ago_allowed(self):
        """Bot habit entry (sleep/workout/self_care) within last 2 messages -> allowed."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[
                _bot_msg("רשמתי שינה ב-23:00.", classification="sleep"),
                _user_msg("לא, זה היה אתמול"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_workout_classification_1_message_ago_allowed(self):
        """Bot workout entry within last 2 messages -> allowed."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[
                _bot_msg("רשמתי אימון.", classification="workout"),
                _user_msg("לא, זה היה אתמול"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_self_care_classification_1_message_ago_allowed(self):
        """Bot self_care entry within last 2 messages -> allowed."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[
                _bot_msg("יפה. רשמתי 'משהו לעצמי' השבוע.", classification="self_care"),
                _user_msg("לא, זה היה שבוע שעבר"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_no_correctable_context_returns_conversational(self):
        """No reply, no last_entry, no recent entry message -> conversational."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[
                _bot_msg("מה נשמע?", classification="conversational"),
                _user_msg("בלי אורז"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"

    def test_no_history_no_context_returns_conversational(self):
        """Empty history, no last_entry, no reply -> conversational."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"

    def test_fallback_calorie_markers_no_classification(self):
        """Old bot message without classification but with calorie markers -> allowed."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[
                _bot_msg("שווארמה ≈ 720 קל׳, 38 ג' חלבון"),  # no classification field
                _user_msg("בלי אורז"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "correction"

    def test_entry_3_messages_ago_returns_conversational(self):
        """Entry confirmation 3+ messages ago -> too old, conversational."""
        result = validate_classification(
            _classify("correction"),
            recent_messages=[
                _bot_msg("שווארמה ≈ 720 קל׳, 38 ג' חלבון", classification="meal"),
                _user_msg("תודה"),
                _bot_msg("בכיף.", classification="conversational"),
                _user_msg("מה שלומך?"),
                _bot_msg("הכל טוב.", classification="conversational"),
                _user_msg("בלי אורז"),
            ],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "conversational"


# ---------------------------------------------------------------------------
# name_declaration guardrail
# ---------------------------------------------------------------------------

class TestNameDeclarationGuardrail:
    """name_declaration is only valid when name is not yet set."""

    def test_name_already_set_returns_conversational(self):
        """Name is set (e.g. 'שי') -> conversational."""
        result = validate_classification(
            _classify("name_declaration"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name="שי",
            gender=None,
        )
        assert result.type == "conversational"

    def test_name_not_set_allowed(self):
        """Name is None -> allowed."""
        result = validate_classification(
            _classify("name_declaration"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "name_declaration"

    def test_name_empty_string_allowed(self):
        """Name is empty string -> treated as not set, allowed."""
        result = validate_classification(
            _classify("name_declaration"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name="",
            gender=None,
        )
        assert result.type == "name_declaration"


# ---------------------------------------------------------------------------
# gender_declaration guardrail
# ---------------------------------------------------------------------------

class TestGenderDeclarationGuardrail:
    """gender_declaration is only valid when gender is not yet set."""

    def test_gender_already_set_returns_conversational(self):
        """Gender is set (e.g. 'male') -> conversational."""
        result = validate_classification(
            _classify("gender_declaration"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name=None,
            gender="male",
        )
        assert result.type == "conversational"

    def test_gender_female_set_returns_conversational(self):
        """Gender is 'female' -> conversational."""
        result = validate_classification(
            _classify("gender_declaration"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name=None,
            gender="female",
        )
        assert result.type == "conversational"

    def test_gender_not_set_allowed(self):
        """Gender is None -> allowed."""
        result = validate_classification(
            _classify("gender_declaration"),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name=None,
            gender=None,
        )
        assert result.type == "gender_declaration"


# ---------------------------------------------------------------------------
# Passthrough: ungated classifications
# ---------------------------------------------------------------------------

class TestPassthrough:
    """Classifications that should never be gated."""

    @pytest.mark.parametrize("rtype", [
        "meal", "conversational", "feedback_request", "feature_request",
        "emotional", "inappropriate", "opt_in", "sleep", "workout", "self_care",
    ])
    def test_ungated_types_pass_through(self, rtype):
        """All ungated classification types pass through unchanged."""
        result = validate_classification(
            _classify(rtype),
            recent_messages=[],
            last_entry=None,
            reply_context=None,
            name="שי",
            gender="male",
        )
        assert result.type == rtype
