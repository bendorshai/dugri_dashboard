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
# "inline conversation hooks" - messages sent after food entries. Each
# habit has:
#   - A gate (minimum days since trial start before revealing)
#   - An optional anchor day (weekday restriction)
#   - An optional goal (quantitative target the user can set)
#   - A reminder cycle for declined/ghosted goals
#
# All timing parameters are in constants.py HOOK_CONFIG. This spec references
# them by name, not by value, so changing a number in config doesn't
# invalidate the spec.
#
# ROUTING MODEL (no pending_state)
# ---------------------------------
# The classifier routes messages using ONLY:
#   1. Toggle state summary (all habits with their status)
#   2. Conversation history (last MAX_RECENT_MESSAGES messages)
#   3. Reply-to-message context (if Telegram swipe-reply)
#   4. Last food entry (for corrections)
#   5. Israeli Hebrew cultural context
#
#
# TOGGLE STATES (per habit)
# --------------------------
#   - dormant: not offered yet
#   - offered: bot proposed tracking, awaiting user response
#   - active_goal_pending: user accepted, bot is collecting goal info
#   - active: tracking without a goal
#   - active_with_goal: tracking with a goal set
#   - remind_pending: user declined/ghosted, asking about reminders
#   - cancelled: permanently declined
#
# The classifier sees the toggle state and the last bot message in history.
# Together these provide full context for routing - no state machine needed.
#
# HABIT SEQUENCE (order of introduction)
# ----------------------------------------
# 1. NUTRITION
#    - Gate: HOOK_CONFIG["nutrition"]["gate_days"] (0 = after first meal)
#    - Trigger: inline conversation hook after first food entry (5s delay)
#    - Goal: calorie + protein daily targets
#    - Flow: offer tracking -> collect body stats (height, weight, age in
#      one message, any format) -> ask weight goal (lose/keep/gain) ->
#      GPT calculates suggestion (Mifflin-St Jeor, 3 retries) -> present
#      suggestion -> user accepts or corrects numbers
#
# 2. SLEEP
#    - Gate: HOOK_CONFIG["sleep"]["gate_days"] (1 = after first night)
#    - Trigger: inline conversation hook after food entry, any day
#    - Goal: target sleep time (HH:MM)
#    - Flow: offer tracking -> accept -> ask "what time do you aim to sleep?"
#      -> user sends time in any format -> GPT extracts -> goal set
#    - IMPORTANT: while in goal flow for sleep (active_goal_pending),
#      the first time the user sends is treated as the GOAL, not as a
#      sleep log. The bot confirms "goal set to 23:00" (not "logged sleep
#      at 23:00"). The classifier knows this because toggle_state shows
#      sleep=active_goal_pending and history shows the bot asked for a time.
#    - Only if the user explicitly declines setting a goal does Dugri
#      switch to tracking sleep times WITHOUT a goal (just logging).
#    - User can update sleep goal later via natural language at any time
#      (see USER-INITIATED GOAL UPDATE section).
#
# 3. EATING WINDOW
#    - Gate: HOOK_CONFIG["eating_window"]["gate_days"] (4)
#    - Trigger: inline conversation hook after food entry
#    - Goal: the window itself (start-end times). Dugri measures daily
#      compliance (did user eat within the window?).
#      Weekly summary reports how many days window was kept.
#      (User can update goal later via natural language - see
#      USER-INITIATED GOAL UPDATE section below.)
#    - Flow: offer tracking -> accept -> ask "when do you start and stop
#      eating?" -> user sends times in any format -> GPT extracts -> set
#
# 4. WORKOUTS
#    - Gate: HOOK_CONFIG["workouts"]["gate_days"] (4) + anchor day (Thursday)
#    - Trigger: inline conversation hook after food entry, only on Thursday
#    - Goal: weekly workout count
#    - Flow: offer tracking -> accept -> ask "how many times per week?"
#      -> user sends number in any format -> GPT extracts -> goal set
#
# 5. SELF-CARE
#    - Gate: HOOK_CONFIG["self_care"]["gate_days"] (4) + anchor day (Friday)
#    - Trigger: inline conversation hook after food entry, only on Friday
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
# OFFER STEP (toggle_state = offered, bot's offer visible in history):
#   - ACCEPT: user cooperates ("יאללה", "אשמח", "בוא", "כן", or any
#     affirmative in natural Israeli Hebrew)
#     -> classifier: conversation_reply
#     -> handler: activate toggle, proceed to goal (or done for self-care)
#
#   - DECLINE: user refuses ("לא", "עזוב", "לא מעניין")
#     -> classifier: toggle_cancel
#     -> handler: Dugri asks "want me to remind you later?"
#     -> toggle moves to remind_pending
#
#   - GHOST: user doesn't reply, sends food or nothing
#     -> if food: classifier: meal, food logged normally
#     -> ghosting = bot's offer scrolls out of history window
#     -> poller detects: offered + no reply in history -> sets reminder
#     -> Dugri does NOT re-offer inline. Waits for scheduled reminder.
#
#   - LATE REPLY (in history): user replies later but the bot's offer is
#     still visible in the MAX_RECENT_MESSAGES (12) message history window.
#     -> classifier uses conversation history + toggle_state to identify
#        as conversation_reply
#     -> handler: activate toggle, proceed
#
#   - LATE LATE REPLY (out of history): user replies days later, the
#     bot's offer has scrolled out of the MAX_RECENT_MESSAGES (12) message
#     history. Only toggle_state shows "offered".
#     -> If only ONE habit is offered: classifier infers the reply
#        is about that habit and classifies as conversation_reply
#     -> If MULTIPLE habits are offered and the message is ambiguous:
#        classifier asks for clarification via freeform_response
#        (type=none with "did you mean X or Y?")
#     -> If MULTIPLE habits are offered but the intent is clear (e.g.,
#        "I work out 3 times a week" when workouts + sleep are offered):
#        classifier routes directly to the relevant habit without
#        clarification.
#
# GOAL STEP (toggle_state = active_goal_pending, bot's goal question in history):
#   - ACCEPT: user cooperates -> collect goal value
#   - DECLINE: user refuses -> toggle moves to remind_pending
#   - GHOST: offer scrolls out of history -> poller sets reminder
#
# GOAL VALUE STEP (toggle_state = active_goal_pending, bot asked for value):
#   - VALID: GPT extracts structured data from natural text (no format
#     requirements). Sleep: "23 בלילה" -> 23:00. Workouts: "3 פעמים" -> 3.
#   - INVALID: GPT can't extract -> Dugri asks again naturally (no format
#     instructions like "send HH:MM")
#
# REMIND STEP (toggle_state = remind_pending, "want me to remind you?" in history):
#   - ACCEPT REMINDER: conversation_reply -> set reminder, done
#   - DECLINE REMINDER: toggle_cancel -> cancelled, never ask again
#   - GHOST: offer scrolls out -> auto-reminder
#
# GHOSTING RULES (cross-cutting)
# --------------------------------
# Ghosting is defined as "out of history context" - the bot's question has
# scrolled out of the MAX_RECENT_MESSAGES window. No TTL-based expiry.
# - Ghost during ANY step -> poller detects and sets reminder
# - Dugri does NOT re-offer inline on next food entry. Not pushy.
# - Reminder fires via 28-min poller when goal_remind_at is reached
# - If ghosted again after reminder -> same cycle (remind, wait, remind)
# - User can always explicitly activate via natural language at any time
#   ("אני רוצה לעקוב אחרי שינה") -> toggle_activate
#
# FOOD DURING OFFER (cross-cutting)
# -----------------------------------
# - User sends food while Dugri is waiting for an opt-in answer
# - classifier: meal (food ALWAYS wins regardless of toggle state)
# - Food is logged normally
# - Toggle state stays unchanged; user can answer later
#
# TELEGRAM REPLY-TO-MESSAGE (cross-cutting)
# ------------------------------------------
# - User swipe-replies to a specific bot message
# - reply_to_message.text is injected into classifier context
# - Gives GPT exact context for what the user is responding to
# - Especially useful for late replies (replying to an old offer)
#
# USER-INITIATED GOAL UPDATE (cross-cutting)
# -------------------------------------------
# - Applies to ALL habits, not just eating window
# - User can say "I want to update my sleep goal" / "change my eating
#   window" / "update my calorie target" at any time in natural language
# - classifier: toggle_activate with the relevant toggle_name
# - If toggle is already active, Dugri re-enters the goal setting flow
#   (asks for the new value) instead of just re-activating
# - Dugri understands the intent from context, not from exact phrasing
#
# RECURRING HOOKS (scheduled prompts for active toggles)
# ------------------------------------------------------
# Once a toggle is ACTIVE, Dugri proactively sends prompts to collect
# data. Timing is randomized to feel human, not robotic:
#
# RANDOMIZED HOOK TIMING
# A random send time is picked within each hook's time window (once per
# day for daily hooks like sleep, once per week for weekly hooks like
# workouts/self_care). These random times are stored in a shared MongoDB
# document (hook_schedule collection, one doc for all users).
# The 28-min poller generates new random times when they're missing or
# expired. The hook fires on the first poller tick AFTER the chosen
# random time - even if that tick lands outside the window (e.g., random
# time 9:59 for sleep, poller picks it up at 10:20 - still fires). The
# window only constrains where the random time is drawn, not when the
# message can actually send. Tests for the randomization mechanism live
# in test_hook_schedule.py.
#
# - SLEEP: daily, within HOOK_CONFIG["sleep"]["window"] (08:00-10:00).
#   Dugri asks what time the user went to sleep yesterday.
#   5 rotating phrasings. Once per day (deduped by last_asked_at).
#
# - WORKOUTS: weekly on HOOK_CONFIG["workouts"]["anchor_day"] (Thursday),
#   within HOOK_CONFIG["workouts"]["window"] (16:00-20:00).
#   Dugri asks if the user worked out this week.
#   5 rotating phrasings. Once per week.
#
# - SELF-CARE: weekly on HOOK_CONFIG["self_care"]["anchor_day"] (Friday),
#   within HOOK_CONFIG["self_care"]["window"] (10:00-14:00).
#   Dugri asks what good thing the user did for themselves.
#   5 rotating phrasings. Once per week.
#
# - WEEKLY SUMMARY: weekly on HOOK_CONFIG["weekly_summary"]["anchor_day"]
#   (Sunday), within window (09:00-11:00).
#   Dugri offers to show the weekly summary.
#
# - EATING WINDOW: daily check. If window closes within
#   EATING_WINDOW_WARN_MINUTES (60 min), send "closing soon" with stats.
#   After window closes, send daily compliance summary.
#   Both fire once per day (deduped by last_asked_at).
#
# These hooks also fire as inline conversation hooks after food entries
# if the user happens to log food during the window and the hook hasn't
# fired yet today. Inline conversation hooks are preferred (natural
# moment), poller is the fallback.
#
# EXIT DOOR: after EXIT_DOOR_UNANSWERED_THRESHOLD (2) consecutive
# unanswered hooks, Dugri adds a soft opt-out message from 5 rotating
# phrasings (EXIT_DOOR_PROMPTS). Each phrasing includes the {habit}
# name so the user knows which tracking is being offered for removal.
#
# PROACTIVE REVEALS
# -----------------
# The 28-min poller checks for reveals within time windows, serving as
# a fallback for users who haven't logged food. Inline conversation
# hooks (after food) remain the preferred trigger for reveals.
#
# CLASSIFIER CONTEXT (always present on every call)
# --------------------------------------------------
# 1. Toggle state summary (all habits with status - see TOGGLE STATES)
# 2. Conversation history (last MAX_RECENT_MESSAGES messages)
# 3. Reply-to-message context (if Telegram reply)
# 4. Last food entry (for corrections)
# 5. Israeli Hebrew cultural context (informal slang = cooperation)
#
# The LLM infers the conversation step from toggle_state + history.
# No explicit pending_state is injected. Examples:
#   - toggle=offered + history shows offer message -> awaiting consent
#   - toggle=active_goal_pending + history shows "what time?" -> awaiting value
#   - toggle=active_goal_pending + history shows suggestion -> awaiting confirm
#   - toggle=remind_pending + history shows "remind later?" -> awaiting remind answer
#
# CLASSIFIER ROUTING RULES
# --------------------------
# - Calorie/protein numbers during goal flow are goal values, not food.
#   "1800 קלוריות ו-180 חלבון" when toggle is active_goal_pending = goal.
# - Toggle state is the primary routing signal: when toggle shows
#   active_goal_pending and the user sends a value, it's a goal - not a
#   food entry, correction, or sleep log.
#
# TEST INFRASTRUCTURE
# --------------------
# History stubs: offer stubs (NUTRITION_OFFER, SLEEP_OFFER, etc.) use
# exact production messages from messages.py. Food response stubs are
# realistic approximations of GPT output (varies by nature).
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
import messages as M

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


# ============================================================================
# TEST INFRASTRUCTURE
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
        "dormant": "לא הוצע עדיין",
        "offered": "הוצע, ממתין לתשובה",
        "active_goal_pending": "פעיל, בתהליך הגדרת יעד",
        "active": "פעיל, בלי יעד",
        "active_with_goal": "פעיל, עם יעד",
        "remind_pending": "סירב, שאלנו אם להזכיר",
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
    base_time = datetime.now(timezone.utc) - timedelta(minutes=len(messages) * 5)
    for i, (role, text) in enumerate(messages):
        msg = {
            "role": role,
            "text": text[:500],
            "timestamp": (base_time + timedelta(minutes=i * 5)).isoformat(),
        }
        result.append(msg)
    return result


def _classify(analyzer, text, toggle_state=None,
              history=None, reply_context=None):
    """Convenience wrapper for classify_message with all context.

    No pending_state is passed. The classifier infers the conversation step
    from toggle_state + history alone.
    """
    return analyzer.classify_message(
        text=text,
        today_str=datetime.now().strftime("%d/%m/%Y"),
        last_entry=None,
        recent_messages=history or [],
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
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "conversation_reply"

    def test_ashma_accepted(self):
        """User says 'אשמח' to nutrition offer -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "conversation_reply"

    def test_okay_accepted(self):
        """User says 'אוקיי' -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אוקיי",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "conversation_reply"

    def test_declined(self):
        """User says 'לא מעניין אותי' -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא מעניין אותי",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "toggle_cancel"

    def test_food_during_offer(self):
        """User sends food while nutrition is in offered state -> meal."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שניצל עם אורז וסלט",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "קפה עם חלב"),
                ("bot", FOOD_RESPONSE_COFFEE),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "meal"

    def test_late_reply_in_history(self):
        """User says 'אשמח' after TTL expired, offer still in history window."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
                ("user", "חביתה עם גבינה"),
                ("bot", FOOD_RESPONSE_EGGS),
            ),
        )
        assert result.type in ("conversation_reply", "toggle_activate")

    def test_late_late_reply_out_of_history(self):
        """User says 'אשמח' days later, offer scrolled out of history.
        History is full of recent food entries. Only toggle_state shows 'offered'."""
        analyzer = _make_analyzer()
        # Simulate a full history of food entries that pushed the offer out
        result = _classify(
            analyzer, "אשמח",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
                ("user", "2 ביצים וסלט"),
                ("bot", FOOD_RESPONSE_EGGS),
                ("user", "סלט טונה"),
                ("bot", FOOD_RESPONSE_SALAD),
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("user", "קפה אחרי הצהריים"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type in ("conversation_reply", "toggle_activate")

    def test_late_late_reply_multiple_offered_clear_intent(self):
        """Two habits offered, user's message clearly refers to one.
        Should route to the correct habit without asking for clarification."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אני מתאמן 3 פעמים בשבוע",
            toggle_state=_build_toggle_state(
                sleep="offered", workouts="offered",
            ),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type in ("conversation_reply", "toggle_activate")
        if result.type == "toggle_activate":
            assert result.toggle_name == "workouts"

    def test_late_reply_swipe_reply(self):
        """User swipe-replies 'אשמח' to the original offer -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח",
            toggle_state=_build_toggle_state(nutrition="offered"),
            reply_context=NUTRITION_OFFER,
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
                ("user", "סלט טונה"),
                ("bot", FOOD_RESPONSE_SALAD),
            ),
        )
        assert result.type in ("conversation_reply", "toggle_activate")

    def test_explicit_request_no_prior_offer(self):
        """User proactively asks to track nutrition -> toggle_activate."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אשמח לעקוב אחרי הרגלי תזונה",
            toggle_state=_build_toggle_state(nutrition="dormant"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "toggle_activate"
        assert result.toggle_name == "nutrition"

    def test_user_asks_why_protein(self):
        """User asks 'why protein?' during offer -> help (not meal, not none)."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "למה חלבון? מה זה נותן?",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "help"


class TestNutritionBodyStats:
    """Tests for body stats collection step.

    toggle_state = active_goal_pending (user accepted, in goal flow).
    The classifier knows we're in body stats step because history shows
    the bot asked for height/weight/age.
    """

    def test_comma_separated(self):
        """Body stats in comma format -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "174, 112, 36",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "יאללה"),
                ("bot", BODY_STATS_ASK),
            ),
        )
        assert result.type == "conversation_reply"

    def test_natural_hebrew(self):
        """Body stats in natural Hebrew -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "��ובה 174, משקל 112, ��יל 36",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "אשמח"),
                ("bot", BODY_STATS_ASK),
            ),
        )
        assert result.type == "conversation_reply"

    def test_multiline(self):
        """Body stats on multiple lines -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "174\n112 קג\n36 שנים",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "בוא"),
                ("bot", BODY_STATS_ASK),
            ),
        )
        assert result.type == "conversation_reply"


class TestNutritionWeightGoal:
    """Tests for weight goal step."""

    def test_lose_weight(self):
        """User says they want to lose weight -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "ירידה! רוצה להגיע ל 98 קג",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "174, 112, 36"),
                ("bot", WEIGHT_GOAL_ASK),
            ),
        )
        assert result.type == "conversation_reply"

    def test_maintain_weight(self):
        """User wants to maintain -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לשמור על המשקל",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "גובה 174, משקל 80, גיל 30"),
                ("bot", WEIGHT_GOAL_ASK),
            ),
        )
        assert result.type == "conversation_reply"

    def test_gain_weight(self):
        """User wants to gain -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "רוצה לעלות קצת, להגיע ל-80",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "175, 65, 25"),
                ("bot", WEIGHT_GOAL_ASK),
            ),
        )
        assert result.type == "conversation_reply"

    def test_weight_goal_all_ask_variants(self):
        """User answers weight goal with ALL NUTRITION_WEIGHT_GOAL_ASK variants.

        Regression: keyword matching failed on 3/5 variants because they use
        verb forms ('לרדת') instead of noun forms ('ירידה').
        """
        analyzer = _make_analyzer()
        for i, ask_variant in enumerate(M.NUTRITION_WEIGHT_GOAL_ASK):
            result = _classify(
                analyzer, "לרדת במשקל",
                toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
                history=_build_history(
                    ("bot", BODY_STATS_ASK),
                    ("user", "174, 112, 36"),
                    ("bot", ask_variant),
                ),
            )
            assert result.type == "conversation_reply", (
                f"NUTRITION_WEIGHT_GOAL_ASK variant {i+1}/{len(M.NUTRITION_WEIGHT_GOAL_ASK)} "
                f"misclassified as {result.type}: {ask_variant!r}"
            )


class TestNutritionConfirm:
    """Tests for confirming/correcting the GPT suggestion."""

    def test_accept_suggestion(self):
        """User accepts suggestion -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "נשמע מעולה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "לרדת"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "conversation_reply"

    def test_correct_numbers(self):
        """User corrects with specific numbers -> conversation_reply or correction.

        The handler treats both the same in active_goal_pending context:
        extract the numbers as the user's desired targets.
        """
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "1800 קלוריות אבל 180 חלבון",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "ירידה"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type in ("conversation_reply", "correction")

    def test_accept_suggestion_all_variants(self):
        """User accepts suggestion with ALL NUTRITION_SUGGESTION variants.

        Regression: keyword matching required 'ממליץ' in bot message, but only
        1/5 variants contains that word. 80% failure rate.
        """
        analyzer = _make_analyzer()
        for i, suggestion_template in enumerate(M.NUTRITION_SUGGESTION):
            suggestion = suggestion_template.format(calories=1800, protein=160)
            result = _classify(
                analyzer, "אוקיי",
                toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
                history=_build_history(
                    ("bot", WEIGHT_GOAL_ASK),
                    ("user", "לרדת"),
                    ("bot", suggestion),
                ),
            )
            assert result.type == "conversation_reply", (
                f"NUTRITION_SUGGESTION variant {i+1}/{len(M.NUTRITION_SUGGESTION)} "
                f"misclassified as {result.type}: {suggestion!r}"
            )


# ============================================================================
# FEEDBACK REQUEST (cross-cutting)
# ============================================================================

class TestFeedbackRequest:
    """Regression tests for feedback_request classification."""

    def test_weekly_summary_request(self):
        """'שלח סיכום שבועי' -> feedback_request, not toggle_activate.

        Regression: bug from 2026-05-25 where this was misclassified as
        toggle_activate with no toggle_name, causing 'לא הבנתי איזה מעקב להדליק'.
        Fixed in v2.2.2 (60f3bfe).
        """
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שלח סיכום שבועי",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "feedback_request", (
            f"'שלח סיכום שבועי' misclassified as {result.type} "
            f"(toggle_name={result.toggle_name})"
        )

    def test_weekly_summary_request_short(self):
        """'שלח סיכום' -> feedback_request."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שלח סיכום",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "feedback_request"


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
            toggle_state=_build_toggle_state(nutrition="active_with_goal", sleep="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "conversation_reply"

    def test_explicit_sleep_request(self):
        """User proactively asks to track sleep -> toggle_activate."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אני רוצה לעקוב אחרי השינה שלי",
            toggle_state=_build_toggle_state(nutrition="active_with_goal", sleep="dormant"),
            history=_build_history(
                ("user", "קפה עם חלב"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "toggle_activate"
        assert result.toggle_name == "sleep"


class TestSleepGoalValue:
    """Tests for sleep goal value extraction.

    IMPORTANT: when toggle_state shows sleep=active_goal_pending and history
    shows the bot asked "what time do you aim to sleep?", a time is the GOAL,
    not a sleep log. The classifier should return conversation_reply, not sleep.
    """

    def test_sleep_time_natural(self):
        """User says sleep time naturally during goal setting -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "23 בלילה",
            toggle_state=_build_toggle_state(sleep="active_goal_pending"),
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "כן"),
                ("bot", SLEEP_GOAL_ASK),
            ),
        )
        assert result.type == "conversation_reply"

    def test_sleep_time_formal(self):
        """User says 23:00 during goal setting -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "23:00",
            toggle_state=_build_toggle_state(sleep="active_goal_pending"),
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "בטח"),
                ("bot", SLEEP_GOAL_ASK),
            ),
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
            toggle_state=_build_toggle_state(eating_window="offered"),
            history=_build_history(
                ("user", "2 ביצים וסלט"),
                ("bot", FOOD_RESPONSE_EGGS),
                ("bot", EATING_WINDOW_OFFER),
            ),
        )
        assert result.type == "conversation_reply"

    def test_window_times_natural(self):
        """User gives window in natural Hebrew -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "מ-8 בבוקר עד 8 בערב",
            toggle_state=_build_toggle_state(eating_window="active_goal_pending"),
            history=_build_history(
                ("bot", EATING_WINDOW_OFFER),
                ("user", "כן"),
                ("bot", "מתי אתה מתחיל ומסיים לאכול?"),
            ),
        )
        assert result.type == "conversation_reply"

    def test_update_window_request(self):
        """User asks to update eating window -> toggle_activate or conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "שומע, אני רוצה לעדכן את חלון האכילה",
            toggle_state=_build_toggle_state(eating_window="active_with_goal"),
            history=_build_history(
                ("user", "סלט טונה"),
                ("bot", FOOD_RESPONSE_SALAD),
            ),
        )
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
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", WORKOUTS_OFFER),
            ),
        )
        assert result.type == "conversation_reply"

    def test_workout_count_natural(self):
        """User says '3 פעמים בשבוע' -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "3 פעמים בשבוע",
            toggle_state=_build_toggle_state(workouts="active_goal_pending"),
            history=_build_history(
                ("bot", WORKOUTS_OFFER),
                ("user", "יאללה"),
                ("bot", "כמה אימונים בשבוע אתה מכוון?"),
            ),
        )
        assert result.type == "conversation_reply"


# ============================================================================
# PHASE 5: SELF-CARE (day 4+, Friday)
# ============================================================================

class TestSelfCareOffer:
    """Tests for self-care offer. No goal question - just tracking."""

    def test_accept_self_care(self):
        """User accepts self-care (naive user says simply yes) -> conversation_reply."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "כן",
            toggle_state=_build_toggle_state(self_care="offered"),
            history=_build_history(
                ("user", "סלט טונה"),
                ("bot", FOOD_RESPONSE_SALAD),
                ("bot", SELF_CARE_OFFER),
            ),
        )
        assert result.type == "conversation_reply"


# ============================================================================
# PHASE 6: CROSS-CUTTING CONCERNS
# ============================================================================

class TestGoalRemind:
    """Tests for the 'want me to remind you later?' step.

    toggle_state = remind_pending. The classifier knows we're in remind step
    because history shows the bot asked "want me to remind you later?".
    """

    def test_accept_reminder(self):
        """User accepts reminder -> conversation_reply or toggle_activate.

        Both are valid: the handler sees remind_pending + affirmative
        and sets the reminder either way.
        """
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "כן, תזכיר לי",
            toggle_state=_build_toggle_state(nutrition="remind_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "לא עכשיו"),
                ("bot", GOAL_REMIND_ASK),
            ),
        )
        assert result.type in ("conversation_reply", "toggle_activate")

    def test_decline_reminder_forever(self):
        """User declines reminder -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא, תעזוב",
            toggle_state=_build_toggle_state(nutrition="remind_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "לא מעניין"),
                ("bot", GOAL_REMIND_ASK),
            ),
        )
        assert result.type == "toggle_cancel"


class TestToggleCancel:
    """Tests for cancelling tracking mid-flow or standalone."""

    def test_cancel_during_offer(self):
        """User refuses offer -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא רוצה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(
                ("user", "קפה עם חלב"),
                ("bot", FOOD_RESPONSE_COFFEE),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "toggle_cancel"

    def test_cancel_standalone(self):
        """User asks to stop tracking sleep -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "תפסיק לשאול אותי על שינה",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.toggle_name == "sleep"

    def test_cancel_natural_language(self):
        """User says 'I don't want nutrition tracking' -> toggle_cancel."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אני לא רוצה מעקב תזונה",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.toggle_name == "nutrition"


class TestNoneIsRare:
    """Tests that none classification is extremely rare."""

    def test_none_with_offer_should_not_happen(self):
        """Short informal messages with offered toggle + offer in history -> never none."""
        analyzer = _make_analyzer()
        short_messages = ["יאללה", "סבבה", "אוקיי", "בוא", "כן", "טוב"]
        for msg in short_messages:
            result = _classify(
                analyzer, msg,
                toggle_state=_build_toggle_state(nutrition="offered"),
                history=_build_history(
                    ("user", "שניצל עם אורז"),
                    ("bot", FOOD_RESPONSE_SCHNITZEL),
                    ("bot", NUTRITION_OFFER),
                ),
            )
            assert result.type != "none", f"'{msg}' classified as none with offer in context"

    def test_genuine_chitchat_is_none(self):
        """Genuine chitchat with no active flow -> none (with freeform response)."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "מה שלומך?",
            toggle_state=_build_toggle_state(),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "none"
        assert result.freeform_response  # should have a natural response
