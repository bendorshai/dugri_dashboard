"""
test_lazy_optin_llm.py - TDD for the entire lazy opt-in lifecycle.

These tests call the actual GPT-4o-mini classifier to verify that the LLM
classifies user messages correctly in every opt-in scenario. They are
integration tests that require an OpenAI API key and network access.

Run with: pytest tests/test_lazy_optin_llm.py -v -m integration
Skip in CI: pytest -m "not integration"

# ============================================================================
# LAZY OPT-IN SPECIFICATION (Single Source of Truth)
#
# This comment defines the complete expected behavior of Dugri's lazy opt-in
# system. Every test in this file verifies one aspect of this spec. When a
# feature changes, UPDATE THIS COMMENT FIRST, then update/add tests, then
# fix code to pass.
#
# ============================================================================
#
# OVERVIEW
# --------
# Dugri introduces habit tracking gradually, one habit at a time, via
# "inline hooks" - messages that piggyback on food entries. Each habit has:
#   - A gate (minimum days since trial start before revealing)
#   - An optional anchor day (weekday restriction)
#   - An optional goal (quantitative target the user can set)
#   - A reminder cycle for declined/ghosted goals
#
# All timing parameters are in constants.py HOOK_CONFIG. This spec references
# them by name, not by value, so changing a number in config doesn't
# invalidate the spec.
#
# HABIT SEQUENCE (order of introduction)
# ----------------------------------------
# 1. NUTRITION
#    - Gate: HOOK_CONFIG["nutrition"]["gate_days"] (0 = after first meal)
#    - Trigger: inline hook after first food entry (5s delay)
#    - Goal: calorie + protein daily targets
#    - Flow: offer tracking -> collect body stats (height, weight, age in
#      one message, any format) -> ask weight goal (lose/keep/gain) ->
#      GPT calculates suggestion (Mifflin-St Jeor, 3 retries) -> present
#      suggestion -> user accepts or corrects numbers
#
# 2. SLEEP
#    - Gate: HOOK_CONFIG["sleep"]["gate_days"] (1 = after first night)
#    - Trigger: inline hook after food entry, any day
#    - Goal: target sleep time (HH:MM)
#    - Flow: offer tracking -> accept -> ask "what time do you aim to sleep?"
#      -> user sends time in any format -> GPT extracts -> goal set
#
# 3. EATING WINDOW
#    - Gate: HOOK_CONFIG["eating_window"]["gate_days"] (4)
#    - Trigger: inline hook after food entry
#    - Goal: the window itself (start-end times). Dugri measures daily
#      compliance (did user eat within the window?). User can update
#      window later with natural language ("update my eating window").
#      Weekly summary reports how many days window was kept.
#    - Flow: offer tracking -> accept -> ask "when do you start and stop
#      eating?" -> user sends times in any format -> GPT extracts -> set
#
# 4. WORKOUTS
#    - Gate: HOOK_CONFIG["workouts"]["gate_days"] (4) + anchor day (Thursday)
#    - Trigger: inline hook after food entry, only on Thursday
#    - Goal: weekly workout count
#    - Flow: offer tracking -> accept -> ask "how many times per week?"
#      -> user sends number in any format -> GPT extracts -> goal set
#
# 5. SELF-CARE
#    - Gate: HOOK_CONFIG["self_care"]["gate_days"] (4) + anchor day (Friday)
#    - Trigger: inline hook after food entry, only on Friday
#    - Goal: NONE. No goal question. Just activate tracking.
#    - Flow: offer tracking -> accept -> "great, I'll remind you weekly"
#    - Dugri reminds weekly to log something good the user did for themselves
#
# 6. WEEKLY SUMMARY
#    - Born active (opt-out). No opt-in flow.
#    - User can cancel anytime with natural language.
#    - Fires on HOOK_CONFIG["weekly_summary"]["anchor_day"] (Sunday)
#
# PER-STEP CASES (applies to every habit unless noted)
# ----------------------------------------------------
#
# OFFER STEP (Dugri proposes tracking):
#   - ACCEPT: user cooperates ("יאללה", "אשמח", "בוא", "כן", or any
#     affirmative in natural Israeli Hebrew)
#     -> classifier: conversation_reply
#     -> activate toggle, proceed to goal (or done for self-care)
#
#   - DECLINE: user refuses ("לא", "עזוב", "לא מעניין")
#     -> classifier: toggle_cancel
#     -> Dugri asks "want me to remind you later?"
#     -> pending_state = awaiting_goal_remind
#
#   - GHOST: user doesn't reply, sends food or nothing
#     -> if food: classifier: meal, food logged, pending stays
#     -> after PENDING_TTL_SECONDS (1 hour): ghosting handler fires
#     -> sets goal_remind_at = now + goal_reminder_days
#     -> Dugri does NOT re-offer inline. Waits for scheduled reminder.
#
#   - LATE REPLY: user replies after TTL expired (hours/days later)
#     -> classifier uses toggle_state ("offered but not activated") +
#        conversation history to identify as conversation_reply
#     -> late reply recovery: activate toggle, proceed
#
# GOAL STEP (Dugri asks about setting a goal):
#   - ACCEPT: user cooperates -> collect goal value
#   - DECLINE: user refuses -> ask remind -> accept/decline reminder
#   - GHOST: same as offer ghost -> reminder after N days
#
# GOAL VALUE STEP (user provides the actual value):
#   - VALID: GPT extracts structured data from natural text (no format
#     requirements). Sleep: "23 בלילה" -> 23:00. Workouts: "3 פעמים" -> 3.
#   - INVALID: GPT can't extract -> Dugri asks again naturally (no format
#     instructions like "send HH:MM")
#
# REMIND STEP ("want me to remind you later?"):
#   - ACCEPT REMINDER: conversation_reply -> set reminder, done
#   - DECLINE REMINDER: toggle_cancel -> goal_status = declined, never ask
#   - GHOST: same as above -> auto-reminder
#
# GHOSTING RULES (cross-cutting)
# --------------------------------
# - Ghost during ANY step -> auto-set reminder after goal_reminder_days
# - Dugri does NOT re-offer inline on next food entry. Not pushy.
# - Reminder fires via 28-min poller when goal_remind_at is reached
# - If ghosted again after reminder -> same cycle (remind, wait, remind)
# - User can always explicitly activate via natural language at any time
#   ("אני רוצה לעקוב אחרי שינה") -> toggle_activate
#
# FOOD DURING PENDING (cross-cutting)
# ------------------------------------
# - User sends food while Dugri is waiting for an opt-in answer
# - classifier: meal (food ALWAYS wins, even with pending state)
# - Food is logged normally
# - pending_state stays untouched
# - User can answer the opt-in question later
#
# TELEGRAM REPLY-TO-MESSAGE (cross-cutting)
# ------------------------------------------
# - User swipe-replies to a specific bot message
# - reply_to_message.text is injected into classifier context
# - Gives GPT exact context for what the user is responding to
# - Especially useful for late replies (replying to an old offer)
#
# CLASSIFIER CONTEXT (always present on every call)
# --------------------------------------------------
# 1. Pending state description (from PENDING_DESCRIPTIONS in prompts.py)
# 2. Toggle state summary (all habits: active/offered/dormant/cancelled)
# 3. Conversation history (last MAX_RECENT_MESSAGES messages)
# 4. Reply-to-message context (if Telegram reply)
# 5. Last food entry (for corrections)
# 6. Israeli Hebrew cultural context (informal slang = cooperation)
#
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
from analyzer import FoodAnalyzer

# Load API key from config
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
try:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        _CONFIG = json.load(f)
    _API_KEY = _CONFIG.get("openai", {}).get("api_key", "")
except FileNotFoundError:
    _API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Skip all tests if no API key
pytestmark = pytest.mark.integration


# ============================================================================
# TEST INFRASTRUCTURE
# ============================================================================

def _make_analyzer():
    """Create a FoodAnalyzer with the configured API key."""
    if not _API_KEY:
        pytest.skip("No OpenAI API key available")
    return FoodAnalyzer(_API_KEY)


def _build_toggle_state(**overrides) -> str:
    """Build a Hebrew toggle state summary string for the classifier.

    Default: all dormant, weekly_summary active. Override with kwargs:
        _build_toggle_state(nutrition="offered", sleep="active_with_goal")
    """
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
        "dormant": "לא הוצע עדיין",
        "offered": "הוצע אבל לא הופעל",
        "active": "פעיל, בלי יעד",
        "active_with_goal": "פעיל, עם יעד",
        "cancelled": "בוטל",
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
    base_time = datetime.now(timezone.utc) - timedelta(minutes=len(messages))
    for i, (role, text) in enumerate(messages):
        msg = {
            "role": role,
            "text": text,
            "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
        }
        result.append(msg)
    return result


def _classify(analyzer, text, pending=None, toggle_state=None,
              history=None, reply_context=None):
    """Convenience wrapper for classify_message with all context."""
    return analyzer.classify_message(
        text=text,
        today_str=datetime.now().strftime("%d/%m/%Y"),
        last_entry=None,
        recent_messages=history or [],
        pending_state=pending,
        toggle_state=toggle_state or _build_toggle_state(),
        reply_context=reply_context,
    )


# ============================================================================
# PHASE 1: NUTRITION (day 0, after first meal)
# ============================================================================

class TestNutritionOffer:
    """Tests for the initial nutrition tracking offer after first food entry."""

    def test_yalla_accepted(self):
        """User says 'יאללה' to nutrition offer -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "יאללה",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("bot", "אגב, אני יכול לחשב לך יעד קלוריות וחלבון. רוצה שננסה?"),
            ),
        )
        assert result.type == "conversation_reply"

    def test_ashma_accepted(self):
        """User says 'אשמח' to nutrition offer -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="offered"),
        )
        assert result.type == "conversation_reply"

    def test_okay_accepted(self):
        """User says 'אוקיי' -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אוקיי",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="offered"),
        )
        assert result.type == "conversation_reply"

    def test_declined(self):
        """User says 'לא מעניין אותי' -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא מעניין אותי",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="offered"),
        )
        assert result.type == "toggle_cancel"

    def test_food_during_pending(self):
        """User sends food while nutrition offer is pending -> meal."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שניצל עם אורז וסלט",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="offered"),
        )
        assert result.type == "meal"

    def test_late_reply_no_pending(self):
        """User says 'אשמח' after TTL expired (no pending) but toggle shows offered."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח",
            pending=None,  # expired
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("bot", "אגב, אני יכול לחשב לך יעד קלוריות וחלבון. רוצה שננסה?"),
                ("user", "חביתה עם גבינה"),  # food, not an answer
                ("bot", "קלטתי. 300 קלוריות."),
            ),
        )
        assert result.type in ("conversation_reply", "toggle_activate")

    def test_late_reply_swipe_reply(self):
        """User swipe-replies 'אשמח' to the original offer -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח",
            pending=None,
            toggle_state=_build_toggle_state(nutrition="offered"),
            reply_context="אגב, אני יכול לחשב לך יעד קלוריות וחלבון. רוצה שננסה?",
        )
        assert result.type in ("conversation_reply", "toggle_activate")

    def test_explicit_request_no_prior_offer(self):
        """User proactively asks to track nutrition -> toggle_activate."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח לעקוב אחרי הרגלי תזונה",
            pending=None,
            toggle_state=_build_toggle_state(nutrition="dormant"),
        )
        assert result.type == "toggle_activate"
        assert result.toggle_name == "nutrition"

    def test_user_asks_why_protein(self):
        """User asks 'why protein?' during offer -> help (not meal, not none)."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "למה חלבון? מה זה נותן?",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="offered"),
        )
        assert result.type == "help"


class TestNutritionBodyStats:
    """Tests for body stats collection step."""

    def test_comma_separated(self):
        """Body stats in comma format -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "174, 112, 36",
            pending={"kind": "awaiting_body_stats", "data": {}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"

    def test_natural_hebrew(self):
        """Body stats in natural Hebrew -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "גובה 174, משקל 112, גיל 36",
            pending={"kind": "awaiting_body_stats", "data": {}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"

    def test_multiline(self):
        """Body stats on multiple lines -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "174\n112 קג\n36 שנים",
            pending={"kind": "awaiting_body_stats", "data": {}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"


class TestNutritionWeightGoal:
    """Tests for weight goal step."""

    def test_lose_weight(self):
        """User says they want to lose weight -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "ירידה! רוצה להגיע ל 98 קג",
            pending={"kind": "awaiting_weight_goal", "data": {}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"

    def test_maintain_weight(self):
        """User wants to maintain -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לשמור על המשקל",
            pending={"kind": "awaiting_weight_goal", "data": {}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"

    def test_gain_weight(self):
        """User wants to gain -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "רוצה לעלות קצת, להגיע ל-80",
            pending={"kind": "awaiting_weight_goal", "data": {}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"


class TestNutritionConfirm:
    """Tests for confirming/correcting the GPT suggestion."""

    def test_accept_suggestion(self):
        """User accepts suggestion -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "נשמע מעולה",
            pending={"kind": "awaiting_nutrition_confirm", "data": {"calories": 1800, "protein": 160}},
            toggle_state=_build_toggle_state(nutrition="active"),
            history=_build_history(
                ("bot", "לפי הנתונים שלך, אני ממליץ על 1800 קלוריות ו-160 גרם חלבון ביום. נשמע טוב?"),
            ),
        )
        assert result.type == "conversation_reply"

    def test_correct_numbers(self):
        """User corrects with specific numbers -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "1800 קלוריות אבל 180 חלבון",
            pending={"kind": "awaiting_nutrition_confirm", "data": {"calories": 1800, "protein": 160}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"


# ============================================================================
# PHASE 2: SLEEP (day 1+)
# ============================================================================

class TestSleepOffer:
    """Tests for sleep tracking offer."""

    def test_accept_sleep(self):
        """User accepts sleep tracking -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "כן, בטח",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "sleep"}},
            toggle_state=_build_toggle_state(nutrition="active_with_goal", sleep="offered"),
        )
        assert result.type == "conversation_reply"

    def test_explicit_sleep_request(self):
        """User proactively asks to track sleep -> toggle_activate."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אני רוצה לעקוב אחרי השינה שלי",
            pending=None,
            toggle_state=_build_toggle_state(nutrition="active_with_goal", sleep="dormant"),
        )
        assert result.type == "toggle_activate"
        assert result.toggle_name == "sleep"


class TestSleepGoalValue:
    """Tests for sleep goal value extraction."""

    def test_sleep_time_natural(self):
        """User says sleep time naturally -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "23 בלילה",
            pending={"kind": "awaiting_goal_value", "data": {"toggle_name": "sleep"}},
            toggle_state=_build_toggle_state(sleep="active"),
        )
        assert result.type == "conversation_reply"

    def test_sleep_time_formal(self):
        """User says 23:00 -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "23:00",
            pending={"kind": "awaiting_goal_value", "data": {"toggle_name": "sleep"}},
            toggle_state=_build_toggle_state(sleep="active"),
        )
        assert result.type == "conversation_reply"


# ============================================================================
# PHASE 3: EATING WINDOW (day 4+)
# ============================================================================

class TestEatingWindowOffer:
    """Tests for eating window offer."""

    def test_accept_eating_window(self):
        """User accepts eating window -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "בוא ננסה",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "eating_window"}},
            toggle_state=_build_toggle_state(eating_window="offered"),
        )
        assert result.type == "conversation_reply"

    def test_window_times_natural(self):
        """User gives window in natural Hebrew -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "מ-8 בבוקר עד 8 בערב",
            pending={"kind": "awaiting_goal_value", "data": {"toggle_name": "eating_window"}},
            toggle_state=_build_toggle_state(eating_window="active"),
        )
        assert result.type == "conversation_reply"

    def test_update_window_request(self):
        """User asks to update eating window -> toggle_activate or conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שומע, אני רוצה לעדכן את חלון האכילה",
            pending=None,
            toggle_state=_build_toggle_state(eating_window="active_with_goal"),
        )
        # Could be toggle_activate (re-configure) or conversation_reply
        assert result.type in ("toggle_activate", "conversation_reply")


# ============================================================================
# PHASE 4: WORKOUTS (day 4+, Thursday)
# ============================================================================

class TestWorkoutsOffer:
    """Tests for workouts offer."""

    def test_accept_workouts(self):
        """User accepts workouts -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "קדימה",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "workouts"}},
            toggle_state=_build_toggle_state(workouts="offered"),
        )
        assert result.type == "conversation_reply"

    def test_workout_count_natural(self):
        """User says '3 פעמים בשבוע' -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "3 פעמים בשבוע",
            pending={"kind": "awaiting_goal_value", "data": {"toggle_name": "workouts"}},
            toggle_state=_build_toggle_state(workouts="active"),
        )
        assert result.type == "conversation_reply"


# ============================================================================
# PHASE 5: SELF-CARE (day 4+, Friday)
# ============================================================================

class TestSelfCareOffer:
    """Tests for self-care offer. No goal question - just tracking."""

    def test_accept_self_care(self):
        """User accepts self-care -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "למה לא",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "self_care"}},
            toggle_state=_build_toggle_state(self_care="offered"),
        )
        assert result.type == "conversation_reply"


# ============================================================================
# PHASE 6: CROSS-CUTTING CONCERNS
# ============================================================================

class TestGoalRemind:
    """Tests for the 'want me to remind you later?' step."""

    def test_accept_reminder(self):
        """User accepts reminder -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "כן, תזכיר לי",
            pending={"kind": "awaiting_goal_remind", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "conversation_reply"

    def test_decline_reminder_forever(self):
        """User declines reminder -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא, תעזוב",
            pending={"kind": "awaiting_goal_remind", "data": {"toggle_name": "nutrition"}},
            toggle_state=_build_toggle_state(nutrition="active"),
        )
        assert result.type == "toggle_cancel"


class TestToggleCancel:
    """Tests for cancelling tracking mid-flow or standalone."""

    def test_cancel_during_offer(self):
        """User refuses offer -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא רוצה",
            pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "sleep"}},
            toggle_state=_build_toggle_state(sleep="offered"),
        )
        assert result.type == "toggle_cancel"

    def test_cancel_standalone(self):
        """User asks to stop tracking sleep -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "תפסיק לשאול אותי על שינה",
            pending=None,
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
        )
        assert result.type == "toggle_cancel"
        assert result.toggle_name == "sleep"

    def test_cancel_natural_language(self):
        """User says 'I don't want nutrition tracking' -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אני לא רוצה מעקב תזונה",
            pending=None,
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
        )
        assert result.type == "toggle_cancel"
        assert result.toggle_name == "nutrition"


class TestNoneIsRare:
    """Tests that none classification is extremely rare."""

    def test_none_with_pending_should_not_happen(self):
        """Short informal messages with pending -> never none."""
        analyzer = _make_analyzer()
        short_messages = ["יאללה", "סבבה", "אוקיי", "בוא", "כן", "טוב"]
        for msg in short_messages:
            result = _classify(
                analyzer, msg,
                pending={"kind": "awaiting_toggle_consent", "data": {"toggle_name": "nutrition"}},
                toggle_state=_build_toggle_state(nutrition="offered"),
            )
            assert result.type != "none", f"'{msg}' classified as none with pending state"

    def test_genuine_chitchat_is_none(self):
        """Genuine chitchat with no pending, no context -> none (with freeform response)."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "מה שלומך?",
            pending=None,
            toggle_state=_build_toggle_state(),
        )
        assert result.type == "none"
        assert result.freeform_response  # should have a natural response
