"""
_lazy_optin_helpers - Shared test infrastructure for lazy opt-in LLM tests.

This module provides realistic conversation stubs, helper functions, and
common imports used across all lazy opt-in test files. It is NOT a test
module (underscore prefix prevents pytest collection).

# ============================================================================
# TEST INFRASTRUCTURE
# --------------------
# History stubs: offer stubs (NUTRITION_OFFER, SLEEP_OFFER, etc.) use
# exact production messages from messages.py. Food response stubs are
# realistic approximations of GPT output (varies by nature).
#
# All test files that import from here must set their own:
#   pytestmark = pytest.mark.integration
# ============================================================================
"""

import json
import os
import sys
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from constants import HOOK_CONFIG, MAX_RECENT_MESSAGES
from openai import OpenAI

from analyzer import FoodAnalyzer
import messages as M

# Load API key from config
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
try:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        _CONFIG = json.load(f)
    _API_KEY = _CONFIG.get("openai", {}).get("api_key", "")
except FileNotFoundError:
    _API_KEY = os.environ.get("OPENAI_API_KEY", "")


# ============================================================================
# REALISTIC CONVERSATION STUBS
#
# These represent actual Dugri bot messages as they appear in production.
# Used to build realistic conversation histories for tests.
# ============================================================================

FOOD_RESPONSE_SCHNITZEL = (
    "• שניצל עם אורז\n"
    "  ~350 גרם | 650 קל׳ | 35 גרם חלבון\n\n"
    "סה\"כ: 650 קל׳ | 35 גרם חלבון\n\n"
    "📊 סיכום יומי:\n"
    "✅ קלוריות: 650/2000 (33%, נותרו: 1350)\n"
    "⚠️ גרם חלבון: 35/150 (23%, נותרו: 115)"
)

FOOD_RESPONSE_COFFEE = (
    "• קפה עם חלב\n"
    "  ~200 גרם | 50 קל׳ | 2 גרם חלבון\n\n"
    "📊 סיכום יומי:\n"
    "✅ קלוריות: 700/2000 (35%, נותרו: 1300)\n"
    "⚠️ גרם חלבון: 37/150 (25%, נותרו: 113)"
)

FOOD_RESPONSE_EGGS = (
    "• 2 ביצים\n"
    "  ~100 גרם | 155 קל׳ | 13 גרם חלבון\n"
    "• סלט ירקות\n"
    "  ~150 גרם | 45 קל׳ | 2 גרם חלבון\n\n"
    "סה\"כ: 200 קל׳ | 15 גרם חלבון\n\n"
    "📊 סיכום יומי:\n"
    "✅ קלוריות: 900/2000 (45%, נותרו: 1100)\n"
    "⚠️ גרם חלבון: 52/150 (35%, נותרו: 98)"
)

FOOD_RESPONSE_SALAD = (
    "• סלט טונה\n"
    "  ~200 גרם | 250 קל׳ | 25 גרם חלבון\n\n"
    "📊 סיכום יומי:\n"
    "✅ קלוריות: 1150/2000 (58%, נותרו: 850)\n"
    "⚠️ גרם חלבון: 77/150 (51%, נותרו: 73)"
)

NUTRITION_OFFER = (
    "אגב, אני יכול לחשב לך יעד קלוריות וחלבון יומי מותאם אישית. "
    "ככה תדע כל ארוחה איפה אתה עומד. רוצה שננסה?"
)

BODY_STATS_ASK = "בשביל החישוב אני צריך לדעת גובה, משקל וגיל. ספר לי."

WEIGHT_GOAL_ASK = "מה הכיוון? ירידה, שמירה, או עלייה במשקל?"

NUTRITION_SUGGESTION = (
    "לפי הנתונים שלך, אני ממליץ על 1800 קלוריות ו-160 גרם חלבון ביום. נשמע טוב?"
)

SLEEP_OFFER = (
    "אגב — בא לי להציע לך משהו חדש. אם תרשום לי מתי הלכת לישון, "
    "אני אעקוב איתך אחרי דפוס השינה. רוצה שננסה?"
)

SLEEP_GOAL_ASK = "באיזו שעה אתה רוצה ללכת לישון?"

EATING_WINDOW_OFFER = (
    "אגב - אם בא לך, אני יכול לעקוב גם אחרי חלון האכילה שלך. "
    "אני אחשב את זה אוטומטית מהארוחות שאתה מתעד. רוצה שננסה?"
)

WORKOUTS_OFFER = (
    "היי, יש משהו שבא לי להציע. אם בא לך, אני יכול לעקוב גם אחרי "
    "האימונים שלך — פעם בשבוע אשאל מה היה. אין לחץ, רק אם זה מעניין אותך. "
    "רוצה שננסה?"
)

SELF_CARE_OFFER = (
    "רוצה לנסות משהו נחמד? פעם בשבוע, בסוף השבוע, לרשום דבר אחד טוב "
    "שעשית לעצמך. לא כושר, לא אוכל — פשוט משהו שעשה לך טוב. "
    "רוצה שאזכיר לך בשישי?"
)

GOAL_REMIND_ASK = "בסדר. רוצה שאזכיר לך בעתיד?"

ONBOARDING_GREETING = M.ONBOARDING_GREETING


# ============================================================================
# TEST HELPERS
# ============================================================================

def _make_analyzer():
    """Create a FoodAnalyzer with the configured API key."""
    if not _API_KEY:
        pytest.skip("No OpenAI API key available")
    return FoodAnalyzer(_API_KEY)


def _build_toggle_state(**overrides) -> str:
    """Build a Hebrew toggle state summary string for the classifier."""
    defaults = {
        "nutrition": "dormant",
        "sleep": "dormant",
        "eating_window": "dormant",
        "workouts": "dormant",
        "self_care": "dormant",
        "weekly_summary": "active",
    }
    defaults.update(overrides)

    labels = {
        "nutrition": "תזונה",
        "sleep": "שינה",
        "eating_window": "חלון אכילה",
        "workouts": "אימונים",
        "self_care": "משהו לעצמי",
        "weekly_summary": "סיכום שבועי",
    }

    state_map = {
        "dormant": "dormant",
        "offered": "offered",
        "active_goal_pending": "active_goal_pending",
        "active": "active",
        "active_with_goal": "active",
        "remind_pending": "remind_pending",
        "cancelled": "cancelled",
    }

    lines = []
    for name, label in labels.items():
        state = defaults.get(name, "dormant")
        desc = state_map.get(state, state)
        lines.append(f"- {label}: {desc}")
    return "\n".join(lines)


def _build_history(*messages) -> list[dict]:
    """Build a conversation history list.

    Each message is a tuple: ("bot", "text") or ("user", "text")
    """
    result = []
    base_time = datetime.now(timezone.utc) - timedelta(minutes=len(messages) * 5)
    for i, (role, text) in enumerate(messages):
        msg = {
            "role": role,
            "text": text[:500],
            "timestamp": (base_time + timedelta(minutes=i * 5)).isoformat(),
        }
        result.append(msg)
    return result


def _route(analyzer, text, toggle_state=None, history=None, reply_context=None):
    """Convenience wrapper for route_message."""
    return analyzer.route_message(
        text=text,
        today_str=datetime.now().strftime("%d/%m/%Y"),
        last_entry=None,
        recent_messages=history or [],
        toggle_state=toggle_state or _build_toggle_state(),
        reply_context=reply_context,
    )


def llm_judge(question: str, text: str) -> bool:
    """Use a separate LLM call to judge whether text answers a yes/no question.

    Replaces brittle keyword matching in LLM integration tests.
    Returns True if the judge answers 'yes'.
    """
    client = OpenAI(api_key=_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        max_tokens=10,
        messages=[
            {"role": "system", "content": (
                "You are a strict yes/no judge. Answer ONLY 'yes' or 'no'. "
                "You will be given a piece of text (possibly in Hebrew) "
                "and a question about it."
            )},
            {"role": "user", "content": f"Text: {text}\n\nQuestion: {question}"},
        ],
    )
    answer = response.choices[0].message.content.strip().lower()
    return answer.startswith("yes") or answer == "כן"
