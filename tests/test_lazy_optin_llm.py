"""
test_lazy_optin_llm.py - TDD for the core lazy opt-in lifecycle.

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
# Related test files:
#   - test_router_llm.py: Router classification tests (primary)
#   - test_router_integration_llm.py: multi-turn integration tests
#   - test_multi_intent_router_llm.py: multi-intent detection
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
# IMPORTANT: Toggle state gates proactive hooks and goal flows, NOT the
# ability to log. A user can report sleep/workout/self_care at any time
# regardless of toggle state. Dormant/cancelled toggles mean Dugri won't
# proactively ask - but if the user volunteers a report, it gets logged.
#
# LOG CONFIRMATION vs TOGGLE OPT-IN (critical distinction)
# ---------------------------------------------------------
# When the conversational handler asks "want to log this as a workout?"
# (or sleep/self_care), user confirmation ("כן", "יאללה") = the habit
# type (workout/sleep/self_care), NOT opt_in. The user is confirming a
# LOG action for a specific instance, not opting into a tracking toggle.
# opt_in is ONLY for:
#   - Formal toggle offers (WORKOUTS_OFFER, SLEEP_OFFER, etc.)
#   - Goal value setting (active_goal_pending)
#   - User-initiated tracking requests ("I want to track workouts")
# The router distinguishes these by checking whether the bot's last
# message asks about logging a specific activity vs offering ongoing
# tracking.
#
# HABIT SEQUENCE (order of introduction)
# ----------------------------------------
# 1. NUTRITION
#    - Gate: HOOK_CONFIG["nutrition"]["gate_days"] (0 = after first meal)
#    - Trigger: inline conversation hook after first food entry (5s delay).
#      STRICTLY INLINE - the 28-min poller must never reveal nutrition.
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
#    - Trigger: inline conversation hook after food entry.
#      Poller reveal requires at least 1 food entry in history.
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
#   - ACCEPT: user cooperates ("יאללה", "אשמח", "בוא", "כן", "זורם",
#     "נו בסדר", "למה לא", "אחלה", "עושים", "טוב", or any affirmative
#     in natural Israeli Hebrew)
#     -> classifier: conversation_reply
#     -> handler: activate toggle, proceed to goal (or done for self-care)
#
#   - SHARP DECLINE: clear decisive refusal ("לא", "עזוב", "לא מעניין",
#     "לא רוצה")
#     -> classifier: toggle_cancel with refusal_tone="sharp"
#     -> handler: Dugri asks "want me to remind you later?"
#     -> toggle moves to remind_pending
#
#   - SOFT DECLINE: hesitation/discomfort ("לא סגור על זה", "לא בטוח",
#     "אולי לא עכשיו", "אולי בהמשך")
#     -> classifier: toggle_cancel with refusal_tone="soft"
#     -> handler: softer tone message, asks "want me to remind you?"
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
#   - UNCERTAINTY/DEFERENCE: user doesn't know, defers to the bot
#     ("אין לי שמץ", "מה שאתה אומר", "אני לא יודע", "תחליט אתה")
#     -> classifier: conversation_reply (not none!)
#     -> handler: accept the bot's suggestion (same as ACCEPT)
#   - SHARP DECLINE: clear refusal ("לא", "עזוב", "לא רוצה")
#     -> classifier: toggle_cancel with refusal_tone="sharp"
#     -> handler: keep habit active, skip goal, ask "want a reminder?"
#     -> goal_status moves to remind_pending
#   - SOFT DECLINE: hesitation/discomfort ("לא סגור על זה", "לא בטוח",
#     "אולי לא עכשיו")
#     -> classifier: toggle_cancel with refusal_tone="soft"
#     -> handler: keep habit active, skip goal, per-habit soft message
#       ("סבבה, בלי יעד בינתיים..."), ask "want a reminder?"
#     -> goal_status moves to remind_pending
#   - GHOST: offer scrolls out of history -> poller sets reminder
#   - PARTIAL ADJUSTMENT: user adjusts only ONE value from the
#     suggestion ("אני מעדיף 170 גרם חלבון" when bot suggested 2200 cal +
#     179g protein). This is cooperation, not refusal.
#     -> classifier: conversation_reply (NOT toggle_cancel)
#     -> handler: merge the user's adjusted value with the original
#        suggestion. E.g., keep calories=2200, update protein=170.
#
# GOAL VALUE STEP (toggle_state = active_goal_pending, bot asked for value):
#   - VALID: GPT extracts structured data from natural text (no format
#     requirements). Sleep: "23 בלילה" -> 23:00. Workouts: "3 פעמים" -> 3.
#   - INVALID: GPT can't extract -> Dugri asks again naturally (no format
#     instructions like "send HH:MM")
#
# REMIND STEP (toggle_state = remind_pending, "want me to remind you?" in history):
#   - ACCEPT REMINDER: conversation_reply -> set reminder, done
#   - DECLINE REMINDER: toggle_cancel -> permanently declined
#     -> handler: sends GOAL_DECLINED_FOREVER message, never asks again
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
# - If toggle is already active with a goal set:
#   - If the user's message contains the new value (e.g., "change
#     calories to 2000"), extract and update directly - no re-flow.
#   - If no value in the message (e.g., "change my targets"), ask for
#     the specific number. For nutrition, skip body stats (already stored).
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
# - none is a LAST RESORT: only when the message is completely unrelated
#   to any tracked habit, ongoing flow, or bot question, and context
#   provides no clue. If ANY toggle is in an active flow (offered /
#   goal_pending / remind_pending), none is almost impossible.
# - refusal_tone: when type=toggle_cancel, the classifier also sets
#   refusal_tone to "sharp" (clear decisive "no") or "soft" (hesitation,
#   discomfort, "not sure"). The handler uses this to choose between
#   canceling vs skipping the goal with a softer message.
#
# COOPERATIVE USER SHORTCUT (offer acceptance with embedded value)
# ----------------------------------------------------------------
# When a user's acceptance message already contains the answer to the
# NEXT question in the flow, Dugri detects this and skips the redundant
# question. The extraction layer runs on the acceptance text before the
# goal offer question is sent.
#
# Examples:
#   - "יאללה, 3 פעמים בשבוע" to workouts offer -> goal set to 3,
#     skip "כמה אימונים בשבוע?" entirely.
#   - "כן, אני מנסה להירדם עד 23:00" to sleep offer -> goal set to
#     23:00, skip "באיזו שעה אתה רוצה ללכת לישון?".
#   - "בטח, 8 בבוקר עד 8 בערב" to eating window offer -> window set,
#     skip "מתי אתה מתחיל ומסיים לאכול?".
#   - "יאללה" alone -> no value found, normal flow continues.
#
# This applies to the offer acceptance path and the toggle_activate path.
# Nutrition is excluded (multi-step flow: body stats -> weight goal ->
# suggestion -> confirm).
#
# Extraction prompts accept bare numbers: "5" -> weekly_target=5,
# "23" -> sleep_time=23:00.
#
# LOOP-CLOSING MESSAGES (what happens next)
# ------------------------------------------
# After a goal is set (or a habit is activated without a goal), Dugri
# appends a habit-specific suffix explaining what the user should expect:
#   - sleep: "מחר בבוקר אשאל אותך מתי הלכת לישון."
#   - workouts: "בימי חמישי אבדוק איתך... תמיד אפשר לדווח מתי שבא לך."
#   - eating_window: "אני עוקב אוטומטית מהארוחות."
#   - nutrition: "כל ארוחה שתדווח - אראה לך איפה אתה עומד ביחס ליעד."
#   - self_care: "בימי שישי אשאל אותך מה עשית לעצמך השבוע."
#
# This fires on goal set, nutrition confirm, and the shortcut path.
#
# ============================================================================

"""

import os
import sys
import pytest

# Add project root and tests dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import messages as M

from _lazy_optin_helpers import (
    _make_analyzer, _build_toggle_state, _build_history, _route,
    FOOD_RESPONSE_SCHNITZEL, FOOD_RESPONSE_COFFEE,
    FOOD_RESPONSE_EGGS, FOOD_RESPONSE_SALAD,
    NUTRITION_OFFER, BODY_STATS_ASK, WEIGHT_GOAL_ASK, NUTRITION_SUGGESTION,
    SLEEP_OFFER, SLEEP_GOAL_ASK,
    EATING_WINDOW_OFFER, WORKOUTS_OFFER, SELF_CARE_OFFER, GOAL_REMIND_ASK,
)

pytestmark = pytest.mark.integration


# ============================================================================
# PHASE 1: NUTRITION (day 0, after first meal)
# ============================================================================

class TestNutritionOffer:
    """Tests for the initial nutrition tracking offer after first food entry."""

    def test_yalla_accepted(self):
        """User says 'יאללה' to nutrition offer -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "יאללה",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_ashma_accepted(self):
        """User says 'אשמח' to nutrition offer -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אשמח",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_okay_accepted(self):
        """User says 'אוקיי' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אוקיי",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_declined(self):
        """User says 'לא מעניין אותי' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא מעניין אותי",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_food_during_offer(self):
        """User sends food while nutrition is in offered state -> meal."""
        analyzer = _make_analyzer()
        result = _route(
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
        result = _route(
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
        assert result.type == "opt_in"

    def test_late_late_reply_out_of_history(self):
        """User says 'אשמח' days later, offer scrolled out of history.
        History is full of recent food entries. Only toggle_state shows 'offered'."""
        analyzer = _make_analyzer()
        # Simulate a full history of food entries that pushed the offer out
        result = _route(
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
        assert result.type == "opt_in"

    def test_late_late_reply_multiple_offered_clear_intent(self):
        """Two habits offered, user's message clearly refers to one.
        Should route to the correct habit without asking for clarification."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני מתאמן 3 פעמים בשבוע",
            toggle_state=_build_toggle_state(
                sleep="offered", workouts="offered",
            ),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "opt_in"
        assert result.toggle_name == "workouts"

    def test_late_reply_swipe_reply(self):
        """User swipe-replies 'אשמח' to the original offer -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
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
        assert result.type == "opt_in"

    def test_explicit_request_no_prior_offer(self):
        """User proactively asks to track nutrition -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אשמח לעקוב אחרי הרגלי תזונה",
            toggle_state=_build_toggle_state(nutrition="dormant"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "opt_in"
        assert result.toggle_name == "nutrition"

    def test_user_asks_why_protein(self):
        """User asks 'why protein?' during offer -> conversational (not meal, not conversational)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "למה חלבון? מה זה נותן?",
            toggle_state=_build_toggle_state(nutrition="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", NUTRITION_OFFER),
            ),
        )
        assert result.type == "conversational"


class TestNutritionBodyStats:
    """Tests for body stats collection step.

    toggle_state = active_goal_pending (user accepted, in goal flow).
    The classifier knows we're in body stats step because history shows
    the bot asked for height/weight/age.
    """

    def test_comma_separated(self):
        """Body stats in comma format -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "174, 112, 36",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "יאללה"),
                ("bot", BODY_STATS_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_natural_hebrew(self):
        """Body stats in natural Hebrew -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "גובה 174, משקל 112, גיל 36",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "אשמח"),
                ("bot", BODY_STATS_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_multiline(self):
        """Body stats on multiple lines -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "174\n112 קג\n36 שנים",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "בוא"),
                ("bot", BODY_STATS_ASK),
            ),
        )
        assert result.type == "opt_in"


class TestNutritionWeightGoal:
    """Tests for weight goal step."""

    def test_lose_weight(self):
        """User says they want to lose weight -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "ירידה! רוצה להגיע ל 98 קג",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "174, 112, 36"),
                ("bot", WEIGHT_GOAL_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_maintain_weight(self):
        """User wants to maintain -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לשמור על המשקל",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "גובה 174, משקל 80, גיל 30"),
                ("bot", WEIGHT_GOAL_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_gain_weight(self):
        """User wants to gain -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "רוצה לעלות קצת, להגיע ל-80",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "175, 65, 25"),
                ("bot", WEIGHT_GOAL_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_bare_laredet(self):
        """User says just 'לרדת' (to lose) - the exact word from the bot's
        options. Regression: gpt-4o-mini misclassified this as toggle_cancel."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לרדת",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", BODY_STATS_ASK),
                ("user", "גובה 174 משקל 113 גיל 36"),
                ("bot", "לפני שאחשב - אתה רוצה לרדת, לשמור על המשקל, או לעלות?"),
            ),
        )
        assert result.type == "opt_in"

    def test_weight_goal_all_ask_variants(self):
        """User answers weight goal with ALL NUTRITION_WEIGHT_GOAL_ASK variants.

        Regression: keyword matching failed on 3/5 variants because they use
        verb forms ('לרדת') instead of noun forms ('ירידה').
        """
        analyzer = _make_analyzer()
        for i, ask_variant in enumerate(M.NUTRITION_WEIGHT_GOAL_ASK):
            result = _route(
                analyzer, "לרדת במשקל",
                toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
                history=_build_history(
                    ("bot", BODY_STATS_ASK),
                    ("user", "174, 112, 36"),
                    ("bot", ask_variant),
                ),
            )
            assert result.type == "opt_in", (
                f"NUTRITION_WEIGHT_GOAL_ASK variant {i+1}/{len(M.NUTRITION_WEIGHT_GOAL_ASK)} "
                f"misclassified as {result.type}: {ask_variant!r}"
            )


class TestNutritionConfirm:
    """Tests for confirming/correcting the GPT suggestion."""

    def test_accept_suggestion(self):
        """User accepts suggestion -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "נשמע מעולה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "לרדת"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "opt_in"

    def test_correct_numbers(self):
        """User corrects with specific numbers -> opt_in or correction.

        The handler treats both the same in active_goal_pending context:
        extract the numbers as the user's desired targets.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "1800 קלוריות אבל 180 חלבון",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "ירידה"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type in ("opt_in", "correction")

    def test_accept_suggestion_all_variants(self):
        """User accepts suggestion with ALL NUTRITION_SUGGESTION variants.

        Regression: keyword matching required 'ממליץ' in bot message, but only
        1/5 variants contains that word. 80% failure rate.
        """
        analyzer = _make_analyzer()
        for i, suggestion_template in enumerate(M.NUTRITION_SUGGESTION):
            suggestion = suggestion_template.format(calories=1800, protein=160)
            result = _route(
                analyzer, "אוקיי",
                toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
                history=_build_history(
                    ("bot", WEIGHT_GOAL_ASK),
                    ("user", "לרדת"),
                    ("bot", suggestion),
                ),
            )
            assert result.type == "opt_in", (
                f"NUTRITION_SUGGESTION variant {i+1}/{len(M.NUTRITION_SUGGESTION)} "
                f"misclassified as {result.type}: {suggestion!r}"
            )


# ============================================================================
# GAP 4: PARTIAL NUTRITION GOAL ADJUSTMENT
#
# When Dugri suggests nutrition targets and the user wants to adjust only
# one value (e.g., protein but not calories), the classifier must route it
# as opt_in (not toggle_cancel) and the handler must merge the
# user's adjustment with the original suggestion.
#
# Real failure (2026-06-07): bot suggested 2200 cal + 179g protein, user
# said "אני מעדיף 170 גרם חלבון", classifier returned toggle_cancel,
# bot responded "ממשיכים בלי יעד" - lost the entire goal.
# ============================================================================

class TestNutritionPartialAdjustment:
    """Tests for adjusting one value from the nutrition suggestion.

    The user accepts the suggestion but wants to change only calories or
    only protein. This is cooperation (opt_in), not refusal.
    """

    SUGGESTION_2200 = (
        "לפי הנתונים שלך, אני ממליץ על 2200 קלוריות ו-179.2 גרם חלבון ביום. נשמע טוב?"
    )

    def test_adjust_protein_only(self):
        """'אני מעדיף 170 גרם חלבון' -> opt_in, not toggle_cancel.

        Real case from 2026-06-07. User accepted calories but wanted
        different protein. Classifier misrouted as toggle_cancel.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני מעדיף 170 גרם חלבון",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", "כדי לחשב - מה הגובה, המשקל והגיל שלך?"),
                ("user", "גובה 174. משקל 112. גיל 36"),
                ("bot", "מה היעד? ירידה, שמירה, או עלייה?"),
                ("user", "ירידה"),
                ("bot", self.SUGGESTION_2200),
            ),
        )
        assert result.type == "opt_in", (
            f"partial adjustment classified as {result.type} - "
            f"adjusting one number is cooperation, not refusal"
        )

    def test_adjust_calories_only(self):
        """'בוא נעשה 2000 קלוריות' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "בוא נעשה 2000 קלוריות",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "ירידה"),
                ("bot", self.SUGGESTION_2200),
            ),
        )
        assert result.type == "opt_in", (
            f"partial adjustment classified as {result.type} - "
            f"adjusting one number is cooperation, not refusal"
        )

    def test_adjust_both_values(self):
        """'אני מעדיף 2000 ו-160' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני מעדיף 2000 ו-160",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "ירידה"),
                ("bot", self.SUGGESTION_2200),
            ),
        )
        assert result.type == "opt_in", (
            f"full adjustment classified as {result.type} - "
            f"changing numbers is cooperation, not refusal"
        )

    def test_prefer_phrasing(self):
        """'אני מעדיף X' is negotiation, not refusal."""
        analyzer = _make_analyzer()
        phrases = [
            "אני מעדיף 150 גרם חלבון",
            "אפשר 1900 קלוריות?",
            "בוא נוריד את החלבון ל-150",
            "אני חושב ש-2000 קלוריות יותר מתאים לי",
        ]
        for phrase in phrases:
            result = _route(
                analyzer, phrase,
                toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
                history=_build_history(
                    ("bot", WEIGHT_GOAL_ASK),
                    ("user", "ירידה"),
                    ("bot", self.SUGGESTION_2200),
                ),
            )
            assert result.type == "opt_in", (
                f"'{phrase}' classified as {result.type} - "
                f"negotiating numbers is cooperation, not refusal"
            )


# ============================================================================
# PHASE 2: SLEEP (day 1+)
# ============================================================================

class TestSleepOffer:
    """Tests for sleep tracking offer."""

    def test_accept_sleep(self):
        """User accepts sleep tracking -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן, בטח",
            toggle_state=_build_toggle_state(nutrition="active_with_goal", sleep="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_explicit_sleep_request(self):
        """User proactively asks to track sleep -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני רוצה לעקוב אחרי השינה שלי",
            toggle_state=_build_toggle_state(nutrition="active_with_goal", sleep="dormant"),
            history=_build_history(
                ("user", "קפה עם חלב"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "opt_in"
        assert result.toggle_name == "sleep"


class TestSleepGoalValue:
    """Tests for sleep goal value extraction.

    IMPORTANT: when toggle_state shows sleep=active_goal_pending and history
    shows the bot asked "what time do you aim to sleep?", a time is the GOAL,
    not a sleep log. The classifier should return opt_in, not sleep.
    """

    def test_sleep_time_natural(self):
        """User says sleep time naturally during goal setting -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "23 בלילה",
            toggle_state=_build_toggle_state(sleep="active_goal_pending"),
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "כן"),
                ("bot", SLEEP_GOAL_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_sleep_time_formal(self):
        """User says 23:00 during goal setting -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "23:00",
            toggle_state=_build_toggle_state(sleep="active_goal_pending"),
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "בטח"),
                ("bot", SLEEP_GOAL_ASK),
            ),
        )
        assert result.type == "opt_in"


# ============================================================================
# PHASE 3: EATING WINDOW (day 4+)
# ============================================================================

class TestEatingWindowOffer:
    """Tests for eating window offer."""

    def test_accept_eating_window(self):
        """User accepts eating window -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "בוא ננסה",
            toggle_state=_build_toggle_state(eating_window="offered"),
            history=_build_history(
                ("user", "2 ביצים וסלט"),
                ("bot", FOOD_RESPONSE_EGGS),
                ("bot", EATING_WINDOW_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_window_times_natural(self):
        """User gives window in natural Hebrew -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "מ-8 בבוקר עד 8 בערב",
            toggle_state=_build_toggle_state(eating_window="active_goal_pending"),
            history=_build_history(
                ("bot", EATING_WINDOW_OFFER),
                ("user", "כן"),
                ("bot", "מתי אתה מתחיל ומסיים לאכול?"),
            ),
        )
        assert result.type == "opt_in"

    def test_update_window_request(self):
        """User asks to update eating window -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "שומע, אני רוצה לעדכן את חלון האכילה",
            toggle_state=_build_toggle_state(eating_window="active_with_goal"),
            history=_build_history(
                ("user", "סלט טונה"),
                ("bot", FOOD_RESPONSE_SALAD),
            ),
        )
        assert result.type == "opt_in"


# ============================================================================
# PHASE 4: WORKOUTS (day 4+, Thursday)
# ============================================================================

class TestWorkoutsOffer:
    """Tests for workouts offer."""

    def test_accept_workouts(self):
        """User accepts workouts -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "קדימה",
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", WORKOUTS_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_workout_count_natural(self):
        """User says '3 פעמים בשבוע' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "3 פעמים בשבוע",
            toggle_state=_build_toggle_state(workouts="active_goal_pending"),
            history=_build_history(
                ("bot", WORKOUTS_OFFER),
                ("user", "יאללה"),
                ("bot", "כמה אימונים בשבוע אתה מכוון?"),
            ),
        )
        assert result.type == "opt_in"


# ============================================================================
# PHASE 5: SELF-CARE (day 4+, Friday)
# ============================================================================

class TestSelfCareOffer:
    """Tests for self-care offer. No goal question - just tracking."""

    def test_accept_self_care(self):
        """User accepts self-care (naive user says simply yes) -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן",
            toggle_state=_build_toggle_state(self_care="offered"),
            history=_build_history(
                ("user", "סלט טונה"),
                ("bot", FOOD_RESPONSE_SALAD),
                ("bot", SELF_CARE_OFFER),
            ),
        )
        assert result.type == "opt_in"


# ============================================================================
# PHASE 6: CROSS-CUTTING CONCERNS
# ============================================================================

class TestGoalRemind:
    """Tests for the 'want me to remind you later?' step.

    toggle_state = remind_pending. The classifier knows we're in remind step
    because history shows the bot asked "want me to remind you later?".
    """

    def test_accept_reminder(self):
        """User accepts reminder -> opt_in.

        The handler sees remind_pending + affirmative and sets the reminder.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן, תזכיר לי",
            toggle_state=_build_toggle_state(nutrition="remind_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "לא עכשיו"),
                ("bot", GOAL_REMIND_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_decline_reminder_forever(self):
        """User declines reminder -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא, תעזוב",
            toggle_state=_build_toggle_state(nutrition="remind_pending"),
            history=_build_history(
                ("bot", NUTRITION_OFFER),
                ("user", "לא מעניין"),
                ("bot", GOAL_REMIND_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_accept_reminder_casual(self):
        """Casual 'כן' to reminder question -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן",
            toggle_state=_build_toggle_state(sleep="remind_pending"),
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "עזוב"),
                ("bot", GOAL_REMIND_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_accept_reminder_sure(self):
        """'סבבה' to reminder question -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "סבבה",
            toggle_state=_build_toggle_state(eating_window="remind_pending"),
            history=_build_history(
                ("bot", EATING_WINDOW_OFFER),
                ("user", "לא עכשיו"),
                ("bot", GOAL_REMIND_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_decline_reminder_not_interested(self):
        """'לא מעניין' to reminder question -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא מעניין",
            toggle_state=_build_toggle_state(workouts="remind_pending"),
            history=_build_history(
                ("bot", WORKOUTS_OFFER),
                ("user", "לא"),
                ("bot", GOAL_REMIND_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_reminder_not_none(self):
        """Any response during remind_pending -> never conversational."""
        analyzer = _make_analyzer()
        messages = ["כן", "לא", "אולי", "נו", "סבבה"]
        for msg in messages:
            result = _route(
                analyzer, msg,
                toggle_state=_build_toggle_state(nutrition="remind_pending"),
                history=_build_history(
                    ("bot", NUTRITION_OFFER),
                    ("user", "לא עכשיו"),
                    ("bot", GOAL_REMIND_ASK),
                ),
            )
            assert result.type != "conversational", (
                f"'{msg}' classified as conversational during remind_pending"
            )


class TestToggleCancel:
    """Tests for cancelling tracking mid-flow or standalone."""

    def test_cancel_during_offer(self):
        """User refuses offer -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא רוצה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(
                ("user", "קפה עם חלב"),
                ("bot", FOOD_RESPONSE_COFFEE),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "opt_in"

    def test_cancel_standalone(self):
        """User asks to stop tracking sleep -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "תפסיק לשאול אותי על שינה",
            toggle_state=_build_toggle_state(sleep="active_with_goal"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
            ),
        )
        assert result.type == "opt_in"
        assert result.toggle_name == "sleep"

    def test_cancel_natural_language(self):
        """User says 'I don't want nutrition tracking' -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני לא רוצה מעקב תזונה",
            toggle_state=_build_toggle_state(nutrition="active_with_goal"),
            history=_build_history(
                ("user", "קפה בבוקר"),
                ("bot", FOOD_RESPONSE_COFFEE),
            ),
        )
        assert result.type == "opt_in"
        assert result.toggle_name == "nutrition"


# ============================================================================
# GAP 3: COOPERATIVE USER SHORTCUT (skip redundant questions)
#
# When a user's response already contains the answer to the NEXT question,
# Dugri should skip that question. E.g., "יאללה, 3 פעמים בשבוע" to a
# workouts offer contains both consent AND the goal value.
# ============================================================================

class TestGoalShortcut:
    """Tests for extracting goal values from acceptance messages.

    These test the extraction layer directly: can GPT extract a goal value
    from a message that also contains acceptance language?
    """

    def test_workouts_accept_with_count(self):
        """'יאללה, 3 פעמים בשבוע' contains a workout count -> extraction succeeds."""
        analyzer = _make_analyzer()
        parsed = analyzer.extract_goal_value("יאללה, 3 פעמים בשבוע", "workout_count")
        assert parsed is not None
        assert parsed.get("weekly_target") == 3

    def test_sleep_accept_with_time(self):
        """'כן, אני מנסה להירדם עד 23:00' contains a sleep time -> extraction succeeds."""
        analyzer = _make_analyzer()
        parsed = analyzer.extract_goal_value("כן, אני מנסה להירדם עד 23:00", "sleep_time")
        assert parsed is not None
        assert parsed.get("sleep_time") == "23:00"

    def test_eating_window_accept_with_times(self):
        """'בטח, 8 בבוקר עד 8 בערב' contains eating window times -> extraction succeeds."""
        analyzer = _make_analyzer()
        parsed = analyzer.extract_goal_value("בטח, 8 בבוקר עד 8 בערב", "eating_window")
        assert parsed is not None
        assert parsed.get("start") == "08:00"
        assert parsed.get("end") == "20:00"

    def test_plain_acceptance_no_shortcut(self):
        """'יאללה' alone has no goal value -> extraction returns None."""
        analyzer = _make_analyzer()
        parsed = analyzer.extract_goal_value("יאללה", "workout_count")
        assert parsed is None

    def test_bare_number_workout(self):
        """Bare '5' should extract as workout count."""
        analyzer = _make_analyzer()
        parsed = analyzer.extract_goal_value("5", "workout_count")
        assert parsed is not None
        assert parsed.get("weekly_target") == 5

    def test_bare_number_sleep(self):
        """Bare '23' should extract as sleep time 23:00."""
        analyzer = _make_analyzer()
        parsed = analyzer.extract_goal_value("23", "sleep_time")
        assert parsed is not None
        assert parsed.get("sleep_time") == "23:00"


# ============================================================================
# UNCERTAINTY / DEFERENCE DURING GOAL FLOW
#
# When the user expresses uncertainty ("I have no clue", "whatever you say")
# during goal-setting, it's NOT a refusal - it's deference. The classifier
# must route to opt_in so the handler accepts the suggestion.
# ============================================================================

class TestUncertaintyDuringGoal:
    """Uncertain/deferring responses during goal-setting -> opt_in."""

    def test_no_clue_during_nutrition_confirm(self):
        """'אין לי שמץ' after nutrition suggestion -> opt_in.

        Regression: was misclassified as none, breaking the goal flow.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אין לי שמץ",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "לרדת"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "opt_in", (
            f"'אין לי שמץ' during goal confirm misclassified as {result.type}"
        )

    def test_deference_during_nutrition_confirm(self):
        """'מה שאתה אומר' after nutrition suggestion -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "מה שאתה אומר",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "ירידה"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "opt_in"

    def test_dont_know_during_sleep_goal(self):
        """'אני לא יודע' when asked for sleep goal -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "אני לא יודע",
            toggle_state=_build_toggle_state(sleep="active_goal_pending"),
            history=_build_history(
                ("bot", SLEEP_OFFER),
                ("user", "יאללה"),
                ("bot", SLEEP_GOAL_ASK),
            ),
        )
        assert result.type == "opt_in"

    def test_you_decide_during_goal(self):
        """'תחליט אתה' after suggestion -> opt_in."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "תחליט אתה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "שמירה"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "opt_in"

    def test_doesnt_matter_during_goal(self):
        """'לא משנה' during goal -> opt_in (deference, not refusal)."""
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "לא משנה",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "לרדת"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "opt_in"


# ============================================================================
# LOG CONFIRMATION vs OPT-IN
#
# When the conversational handler suggests logging a specific activity
# ("want to log this as a workout?"), user confirmation is a LOG action
# (type=workout), NOT an opt_in. opt_in is only for formal toggle offers,
# goal flows, and user-initiated tracking requests.
#
# Regression: user said "I walked 1.5hrs on Saturday", bot (conversational)
# responded "great! want to log as workout?", user said "כן!" -
# router misclassified as opt_in, activated toggle without logging.
# ============================================================================

class TestLogConfirmationVsOptIn:
    """Confirmation of bot's logging suggestion = habit type, not opt_in.

    The router uses last_bot_intent (enum field before type) to distinguish:
    - log_suggestion: bot asked to log a specific activity -> workout/sleep/self_care
    - toggle_offer: bot offered ongoing tracking -> opt_in
    - goal_question: bot asked for goal values -> opt_in
    """

    def test_yes_to_log_workout_suggestion(self):
        """User says 'כן!' after bot asks 'want to log as workout?' -> workout.

        Exact production scenario: user mentioned walking, conversational
        handler asked about logging, user confirmed. Toggle is dormant.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן!",
            toggle_state=_build_toggle_state(workouts="dormant"),
            history=_build_history(
                ("user", "אתה יודע שביום שבת הלכתי שעה וחצי ברגל?"),
                ("bot", "מעולה, הליכה זה תמיד טוב! רוצה לדווח על זה כהתאמן השבוע?"),
            ),
        )
        assert result.type == "workout", (
            f"'כן!' after bot suggested logging workout misclassified as {result.type} "
            f"(expected workout - log confirmation, not opt_in)"
        )

    def test_formal_workout_offer_still_optin(self):
        """'כן' after formal WORKOUTS_OFFER (toggle offered) -> opt_in.

        Distinguishes from log confirmation: this is a formal tracking
        offer, not a suggestion to log a specific workout instance.
        """
        analyzer = _make_analyzer()
        result = _route(
            analyzer, "כן",
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(
                ("user", "שניצל עם אורז"),
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", WORKOUTS_OFFER),
            ),
        )
        assert result.type == "opt_in", (
            f"'כן' after formal WORKOUTS_OFFER misclassified as {result.type} "
            f"(expected opt_in)"
        )
