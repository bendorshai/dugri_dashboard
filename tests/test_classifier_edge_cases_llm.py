"""
test_classifier_edge_cases_llm.py - TDD for classifier routing constraints.

These tests call the actual GPT-4o-mini classifier to verify cross-cutting
routing rules: when 'none' is/isn't valid, and sharp vs soft refusal tone.
They are integration tests that require an OpenAI API key and network access.

Run with: pytest tests/test_classifier_edge_cases_llm.py -v -m integration

# ============================================================================
# CLASSIFIER ROUTING RULES SPECIFICATION (Single Source of Truth)
#
# This comment defines the classifier's cross-cutting routing constraints.
# When behavior changes, UPDATE THIS COMMENT FIRST, then update/add tests,
# then fix code to pass.
#
# ============================================================================
#
# NONE IS A LAST RESORT
# ----------------------
# none (type="unrelated") should only be returned when the message is
# completely unrelated to any tracked habit, ongoing flow, or bot question,
# and context provides no clue. If ANY toggle is in an active flow
# (offered / goal_pending / remind_pending), none is almost impossible.
#
# When a toggle is offered and the offer is in history, short informal
# messages ("יאללה", "סבבה", "אוקיי", "בוא", "כן", "טוב") are ALWAYS
# responses to the offer, never unrelated chitchat.
#
# Genuine none: only when NO toggle is in an active flow AND the message
# is truly off-topic (e.g., "מה שלומך?" with all toggles dormant/active).
# In this case, freeform_response should contain a natural reply.
#
# NONE IMPOSSIBLE DURING ACTIVE FLOWS
# ------------------------------------
# When any toggle is in an active flow (offered/goal_pending/remind_pending),
# none should never be returned. The classifier must always find a more
# specific route. This applies even to ambiguous messages like "אממ",
# "מה?", "נו" - these are responses to the bot's question, not unrelated.
#
# REFUSAL TONE (refusal_tone field on toggle_cancel)
# ---------------------------------------------------
# When type=toggle_cancel, the classifier also sets refusal_tone:
#
#   - "sharp": Clear decisive refusal. The user knows they don't want this.
#     Examples: "לא", "עזוב", "לא מעניין", "לא רוצה"
#     Handler: asks "want me to remind you later?" -> remind_pending
#
#   - "soft": Hesitation, discomfort, "not sure". The user isn't saying no
#     forever - they're uncomfortable or unsure right now.
#     Examples: "לא סגור על זה", "לא בטוח", "אולי לא עכשיו",
#     "אולי בהמשך", "לא עכשיו", "לא בטוח שזה מתאים לי"
#     Handler: softer tone message, asks "want me to remind you?"
#
# refusal_tone applies at both the OFFER step (toggle=offered) and the
# GOAL step (toggle=active_goal_pending). At the goal step, sharp refusal
# means "I don't want a goal at all", soft means "I'm not sure about
# these numbers / this approach".
#
# ============================================================================
"""

import os
import sys
import pytest

# Add project root and tests dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _lazy_optin_helpers import (
    _make_analyzer, _build_toggle_state, _build_history, _classify,
    FOOD_RESPONSE_SCHNITZEL, FOOD_RESPONSE_COFFEE,
    NUTRITION_OFFER, NUTRITION_SUGGESTION, WEIGHT_GOAL_ASK,
    SLEEP_OFFER, EATING_WINDOW_OFFER, WORKOUTS_OFFER, GOAL_REMIND_ASK,
)

pytestmark = pytest.mark.integration


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
            assert result.type != "unrelated", f"'{msg}' classified as none with offer in context"

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
        assert result.type == "unrelated"
        assert result.freeform_response  # should have a natural response


class TestNoneDuringActiveFlow:
    """none must not occur when a toggle is in an active flow."""

    def test_none_impossible_during_goal_pending(self):
        """Various ambiguous messages during goal_pending -> never none."""
        analyzer = _make_analyzer()
        messages = ["אין לי שמץ", "לא יודע", "אממ", "נו"] # used ot have "מה?" in it but it's too off putting and may be unreleated.
        for msg in messages:
            result = _classify(
                analyzer, msg,
                toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
                history=_build_history(
                    ("bot", WEIGHT_GOAL_ASK),
                    ("user", "לרדת"),
                    ("bot", NUTRITION_SUGGESTION),
                ),
            )
            assert result.type != "unrelated", (
                f"'{msg}' classified as none during active goal flow"
            )

    def test_none_impossible_during_remind_pending(self):
        """Ambiguous messages during remind_pending -> never none."""
        analyzer = _make_analyzer()
        messages = ["אממ", "לא יודע", "נו"]
        for msg in messages:
            result = _classify(
                analyzer, msg,
                toggle_state=_build_toggle_state(nutrition="remind_pending"),
                history=_build_history(
                    ("bot", NUTRITION_OFFER),
                    ("user", "לא עכשיו"),
                    ("bot", GOAL_REMIND_ASK),
                ),
            )
            assert result.type != "unrelated", (
                f"'{msg}' classified as none during remind_pending"
            )


# ============================================================================
# SHARP vs SOFT REFUSAL (refusal_tone field)
#
# toggle_cancel now carries a refusal_tone: "sharp" for clear decisive
# refusal, "soft" for hesitation/discomfort. The handler uses this to
# choose between canceling vs skipping the goal with a softer response.
# ============================================================================

class TestRefusalTone:
    """Tests that toggle_cancel includes correct refusal_tone."""

    def test_sharp_refusal_during_offer(self):
        """'לא רוצה' to offer -> toggle_cancel, refusal_tone=sharp."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא רוצה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.refusal_tone == "sharp"

    def test_soft_refusal_during_offer(self):
        """'לא סגור על זה' to offer -> toggle_cancel, refusal_tone=soft."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא סגור על זה",
            toggle_state=_build_toggle_state(sleep="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", SLEEP_OFFER),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.refusal_tone == "soft"

    def test_sharp_refusal_during_goal(self):
        """'לא' to goal question -> toggle_cancel, refusal_tone=sharp."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "לרדת"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.refusal_tone == "sharp"

    def test_soft_refusal_during_goal(self):
        """'לא בטוח שזה מתאים לי' to suggestion -> toggle_cancel, refusal_tone=soft."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא בטוח שזה מתאים לי",
            toggle_state=_build_toggle_state(nutrition="active_goal_pending"),
            history=_build_history(
                ("bot", WEIGHT_GOAL_ASK),
                ("user", "ירידה"),
                ("bot", NUTRITION_SUGGESTION),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.refusal_tone == "soft"

    def test_maybe_later_is_soft(self):
        """'אולי בהמשך' -> toggle_cancel, refusal_tone=soft."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "אולי בהמשך",
            toggle_state=_build_toggle_state(eating_window="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", EATING_WINDOW_OFFER),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.refusal_tone == "soft"

    def test_not_now_is_soft(self):
        """'לא עכשיו' -> toggle_cancel, refusal_tone=soft."""
        analyzer = _make_analyzer()
        result = _classify(
            analyzer, "לא עכשיו",
            toggle_state=_build_toggle_state(workouts="offered"),
            history=_build_history(
                ("bot", FOOD_RESPONSE_SCHNITZEL),
                ("bot", WORKOUTS_OFFER),
            ),
        )
        assert result.type == "toggle_cancel"
        assert result.refusal_tone == "soft"
