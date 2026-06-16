"""
test_trial_expiry_llm - LLM integration tests for trial-ended conversational mode.

Covers:
- When trial is over and user tries to log a meal: Dugri politely says
  logging is no longer available AND suggests purchasing a plan.
- Same for: sleep log, workout log, self_care log, goal setting, photo log.
- General conversational still works normally after trial ends.
- First message after trial end acknowledges the trial is over.

All assertions use llm_judge (no keyword matching on GPT output).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from pathlib import Path
from _lazy_optin_helpers import _make_analyzer, _build_toggle_state, llm_judge

from services.conversational_service import ConversationalService

pytestmark = pytest.mark.integration

KNOWLEDGE_PATH = Path(__file__).parent.parent / "knowledge" / "dugri-self-knowledge.md"
TRIAL_SALES_PATH = Path(__file__).parent.parent / "knowledge" / "dugri-trial-sales.md"
TODAY_DATE = "16/06/2026 (יום שני)"
USER_CONTEXT = "שם: דני\nגובה: 175 ס\"מ\nמשקל: 80 ק\"ג\nיעד קלוריות: 2000\nיעד חלבון: 150"


def _make_service():
    analyzer = _make_analyzer()
    return ConversationalService(
        analyzer,
        knowledge_path=KNOWLEDGE_PATH,
        trial_sales_path=TRIAL_SALES_PATH,
    )


def _respond_trial_ended(service, text, recent_messages=None, is_first_post_trial=False):
    return service.respond(
        user_text=text,
        user_context=USER_CONTEXT,
        toggle_state=_build_toggle_state(),
        today_date=TODAY_DATE,
        recent_messages=recent_messages,
        trial_over_context=service.get_trial_over_context(),
        is_first_post_trial=is_first_post_trial,
    )


# ---------------------------------------------------------------------------
# Blocked actions
# ---------------------------------------------------------------------------

class TestTrialEndedBlockedActions:
    """When trial is over, Dugri politely refuses action requests and suggests a plan."""

    def test_meal_log_blocked_politely(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "אכלתי שניצל עם אורז")
        assert llm_judge(
            "Does this Hebrew text politely indicate that food logging is no longer available?",
            response,
        ), f"Expected polite refusal for meal log, got: {response}"
        assert llm_judge(
            "Does this Hebrew text mention or suggest purchasing a subscription plan or continuing with a paid plan?",
            response,
        ), f"Expected plan suggestion, got: {response}"

    def test_photo_log_blocked_politely(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "[המשתמש שלח תמונה לתיעוד אוכל]")
        assert llm_judge(
            "Does this Hebrew text indicate that food logging (including photos) is no longer available?",
            response,
        ), f"Expected polite refusal for photo log, got: {response}"

    def test_sleep_log_blocked(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "הלכתי לישון אתמול ב-23:00")
        assert llm_judge(
            "Does this Hebrew text politely indicate that sleep logging is no longer available?",
            response,
        ), f"Expected polite refusal for sleep log, got: {response}"
        assert llm_judge(
            "Does this Hebrew text mention or suggest purchasing a subscription plan?",
            response,
        ), f"Expected plan suggestion, got: {response}"

    def test_workout_log_blocked(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "עשיתי אימון כוח היום")
        assert llm_judge(
            "Does this Hebrew text politely indicate that workout logging is no longer available?",
            response,
        ), f"Expected polite refusal for workout log, got: {response}"

    def test_self_care_blocked(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "עשיתי יוגה אתמול")
        assert llm_judge(
            "Does this Hebrew text politely indicate that activity logging is no longer available?",
            response,
        ), f"Expected polite refusal for self care, got: {response}"

    def test_goal_setting_blocked(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "רוצה להגדיר יעד של 1800 קלוריות")
        assert llm_judge(
            "Does this Hebrew text politely indicate that goal setting is no longer available?",
            response,
        ), f"Expected polite refusal for goal setting, got: {response}"


# ---------------------------------------------------------------------------
# Conversational still works
# ---------------------------------------------------------------------------

class TestTrialEndedConversationalWorks:
    """General conversational questions still get proper answers."""

    def test_general_question_answered(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "למה דוגרי עוקב רק אחרי 5 הרגלים?")
        assert llm_judge(
            "Does this Hebrew text explain why Dugri tracks only 5 habits?",
            response,
        ), f"Expected explanation about 5 habits, got: {response}"

    def test_first_message_mentions_trial_ended(self):
        svc = _make_service()
        response = _respond_trial_ended(svc, "היי, מה נשמע?", is_first_post_trial=True)
        assert llm_judge(
            "Does this Hebrew text mention that the trial period has ended or is over?",
            response,
        ), f"Expected trial ended mention, got: {response}"
