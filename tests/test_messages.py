"""
test_messages - TDD tests for the messages module.

Verifies all expected message groups exist with correct structure and content.
"""

import pytest

import messages as M


class TestOnboardingMessages:
    def test_greeting_exists(self):
        assert isinstance(M.ONBOARDING_GREETING, str)
        assert len(M.ONBOARDING_GREETING) > 0
        assert "דוגרי" in M.ONBOARDING_GREETING

    def test_name_response_template(self):
        """Name response should be a format string with {name} placeholder."""
        text = M.ONBOARDING_NAME_RESPONSE.format(name="שי")
        assert "שי" in text

    def test_invite_first_meal(self):
        assert isinstance(M.ONBOARDING_INVITE_MEAL, str)
        assert len(M.ONBOARDING_INVITE_MEAL) > 0


class TestToggleRevealMessages:
    """One-time reveal messages - one per toggle."""

    def test_sleep_reveal(self):
        assert isinstance(M.REVEAL_SLEEP, str)
        assert "שינה" in M.REVEAL_SLEEP or "לישון" in M.REVEAL_SLEEP or "נרדמת" in M.REVEAL_SLEEP

    def test_eating_window_reveal(self):
        assert isinstance(M.REVEAL_EATING_WINDOW, str)
        assert "חלון" in M.REVEAL_EATING_WINDOW or "אכילה" in M.REVEAL_EATING_WINDOW

    def test_workouts_reveal(self):
        assert isinstance(M.REVEAL_WORKOUTS, str)
        assert "אימונ" in M.REVEAL_WORKOUTS

    def test_self_care_reveal(self):
        assert isinstance(M.REVEAL_SELF_CARE, str)
        assert "לעצמ" in M.REVEAL_SELF_CARE or "טוב" in M.REVEAL_SELF_CARE


class TestRotatingPrompts:
    """Rotating hook prompt pools must be non-empty lists of strings."""

    def test_all_prompts_are_nonempty_strings(self):
        for pool in [
            M.HOOK_SLEEP_PROMPTS,
            M.HOOK_WORKOUTS_PROMPTS,
            M.HOOK_SELF_CARE_PROMPTS,
        ]:
            assert len(pool) > 0
            for prompt in pool:
                assert isinstance(prompt, str)
                assert len(prompt) > 0


class TestTargetMessages:
    def test_target_offer_after_first_meal(self):
        assert isinstance(M.TARGET_OFFER_FIRST, str)
        assert "גובה" in M.TARGET_OFFER_FIRST or "משקל" in M.TARGET_OFFER_FIRST

    def test_target_retry_day9(self):
        assert isinstance(M.TARGET_RETRY, str)
        assert len(M.TARGET_RETRY) > 0

    def test_target_suggestion_template(self):
        text = M.TARGET_SUGGESTION.format(calories=1900, protein=140)
        assert "1,900" in text or "1900" in text

    def test_target_accepted(self):
        assert isinstance(M.TARGET_ACCEPTED, str)

    def test_target_declined(self):
        assert isinstance(M.TARGET_DECLINED, str)

    def test_ask_body_stats(self):
        assert isinstance(M.ASK_BODY_STATS, str)
        assert "גובה" in M.ASK_BODY_STATS


class TestExitDoorMessages:
    def test_exit_door_prompts_is_list_of_five(self):
        assert isinstance(M.EXIT_DOOR_PROMPTS, list)
        assert len(M.EXIT_DOOR_PROMPTS) == 5

    def test_all_exit_door_prompts_accept_habit_placeholder(self):
        for i, prompt in enumerate(M.EXIT_DOOR_PROMPTS):
            text = prompt.format(habit="שינה")
            assert "שינה" in text, f"EXIT_DOOR_PROMPTS[{i}] missing {{habit}}"

    def test_exit_door_cancelled(self):
        assert isinstance(M.EXIT_DOOR_CANCELLED, str)

    def test_exit_door_kept(self):
        assert isinstance(M.EXIT_DOOR_KEPT, str)


class TestToggleDeclinedMessages:
    def test_toggle_declined_message(self):
        assert isinstance(M.TOGGLE_DECLINED, str)
        assert "הדליק" in M.TOGGLE_DECLINED or "בהמשך" in M.TOGGLE_DECLINED or "תרצ" in M.TOGGLE_DECLINED


class TestDashboardIntroMessage:
    def test_dashboard_intro(self):
        assert isinstance(M.DASHBOARD_INTRO, str)
        assert "דשבורד" in M.DASHBOARD_INTRO or "אתר" in M.DASHBOARD_INTRO


class TestWeeklySummaryMessages:
    def test_weekly_offer(self):
        assert isinstance(M.WEEKLY_SUMMARY_OFFER, str)
        assert "סיכום" in M.WEEKLY_SUMMARY_OFFER or "שבוע" in M.WEEKLY_SUMMARY_OFFER

    def test_weekly_no_data(self):
        assert isinstance(M.WEEKLY_SUMMARY_NO_DATA, str)

    def test_weekly_sparse(self):
        assert isinstance(M.WEEKLY_SUMMARY_SPARSE, str)

    def test_weekly_no_pattern(self):
        assert isinstance(M.WEEKLY_SUMMARY_NO_PATTERN, str)

    def test_feedback_closing_full(self):
        assert isinstance(M.FEEDBACK_CLOSING_FULL, str)

    def test_feedback_closing_concise(self):
        assert isinstance(M.FEEDBACK_CLOSING_CONCISE, str)

    def test_feedback_reaction_ack(self):
        assert isinstance(M.FEEDBACK_REACTION_ACK, str)


class TestFoodDeletedMessages:
    def test_food_deleted_is_list(self):
        assert isinstance(M.FOOD_DELETED, list)

    def test_food_deleted_has_four_variants(self):
        assert len(M.FOOD_DELETED) == 4

    def test_food_deleted_contains_expected_phrases(self):
        expected = {"סוגר", "קיבלתי", "מחקתי", "טופל"}
        assert set(M.FOOD_DELETED) == expected


class TestRouterMessages:
    def test_sleep_logged_template(self):
        text = M.SLEEP_LOGGED.format(time="23:30")
        assert "23:30" in text

    def test_workout_logged(self):
        assert isinstance(M.WORKOUT_LOGGED, str)

    def test_self_care_logged(self):
        assert isinstance(M.SELF_CARE_LOGGED, str)

    def test_not_understood(self):
        assert isinstance(M.NOT_UNDERSTOOD, str)

    def test_no_data_for_feedback(self):
        assert isinstance(M.NO_DATA_FOR_FEEDBACK, str)
