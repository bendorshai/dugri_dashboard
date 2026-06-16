"""
goal_service.py - per-habit goal lifecycle orchestration.

Handles the multi-step goal conversation for each habit:
  activate tracking -> offer goal -> collect value -> set/decline/remind

Each habit owns its goal independently. Nutrition has a special flow
(body stats -> GPT suggestion or manual entry).

Routing is done by toggle_state + conversation history in the handler.
This service only handles the business logic for each step.

Depends on: toggle_service, user_repository, analyzer.
Used by: handlers/base.py, scheduler.py.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from constants import HOOK_CONFIG, DEFAULT_GOAL_REMINDER_DAYS
from models.profile import User
from repositories.user_repository import UserRepository
from services.toggle_service import ToggleService

logger = logging.getLogger(__name__)


class GoalService:
    def __init__(
        self,
        user_repo: UserRepository,
        toggle_service: ToggleService,
        analyzer=None,
    ):
        self._user_repo = user_repo
        self._toggle_service = toggle_service
        self._analyzer = analyzer

    # ------------------------------------------------------------------
    # Should we offer a goal?
    # ------------------------------------------------------------------

    def should_offer_goal(self, profile: User, toggle_name: str) -> bool:
        """Check if we should offer a goal for this habit."""
        config = HOOK_CONFIG.get(toggle_name, {})
        if not config.get("has_goal", False):
            return False

        toggle = getattr(profile.toggles, toggle_name, None)
        if toggle is None:
            return False

        # Already set, declined, or has a value (e.g. from dashboard)
        if toggle.goal_status in ("set", "declined"):
            return False
        if toggle.goal_value:
            return False

        # For nutrition, check if dashboard already set targets
        if toggle_name == "nutrition":
            if profile.targets.calories or profile.targets.protein:
                return False

        return True

    # ------------------------------------------------------------------
    # Offer goal
    # ------------------------------------------------------------------

    def offer_goal(self, tid: int, toggle_name: str) -> str:
        """Offer a goal for the given habit."""
        import messages as M

        if toggle_name == "nutrition":
            return self.start_nutrition_onboarding(tid)

        pool = self._get_goal_offer_pool(toggle_name)
        text = random.choice(pool)

        self._toggle_service.set_goal_offered(tid, toggle_name)
        return text

    def offer_goal_with_shortcut(
        self, tid: int, toggle_name: str, user_text: str,
    ) -> str:
        """Offer a goal, but first try to extract a value from the user's text.

        If the user's acceptance message already contains the goal value
        (e.g., "יאללה, 3 פעמים בשבוע"), skip the goal question and jump
        straight to confirmation. Falls back to normal offer_goal() if
        no value is found.
        """
        import messages as M

        if toggle_name == "nutrition":
            return self.start_nutrition_onboarding(tid)

        extraction_types = {
            "sleep": "sleep_time",
            "workouts": "workout_count",
            "eating_window": "eating_window",
        }
        goal_type = extraction_types.get(toggle_name)
        if goal_type and self._analyzer:
            parsed = self._analyzer.extract_goal_value(user_text, goal_type)
            if parsed is not None:
                self._toggle_service.set_goal_value(tid, toggle_name, parsed)
                if toggle_name == "eating_window" and "start" in parsed and "end" in parsed:
                    self._user_repo.update_fields(tid, {
                        "eating_window": {"start": parsed["start"], "end": parsed["end"]},
                    })
                pool = self._get_goal_set_pool(toggle_name)
                text = random.choice(pool)
                loop_close = M.LOOP_CLOSE_GOAL_SET.get(toggle_name, "")
                return text + loop_close

        return self.offer_goal(tid, toggle_name)

    # ------------------------------------------------------------------
    # Goal consent (yes/no to "want to set a goal?")
    # ------------------------------------------------------------------

    def handle_goal_consent(self, tid: int, toggle_name: str) -> str:
        """User cooperated with goal offer - proceed to value collection."""
        return self._ask_for_goal_value(tid, toggle_name)

    def _ask_for_goal_value(self, tid: int, toggle_name: str) -> str:
        """Transition to collecting the goal value."""
        import messages as M

        pool = self._get_goal_value_ask_pool(toggle_name)
        text = random.choice(pool)
        return text

    def ask_remind(self, tid: int, toggle_name: str) -> str:
        """Ask if user wants to be reminded later.

        Sets goal_status to remind_pending so the handler knows the user
        is answering a reminder question on their next message.
        """
        import messages as M

        text = random.choice(M.GOAL_DECLINED_REMIND_ASK)
        self._toggle_service.set_goal_status(tid, toggle_name, "remind_pending")
        return text

    def skip_goal(self, tid: int, toggle_name: str) -> None:
        """Skip goal without canceling the habit.

        The habit stays active but without a quantitative target.
        Clears goal_offered_at so the flow doesn't re-trigger.
        """
        self._toggle_service.set_goal_status(tid, toggle_name, "declined")
        self._user_repo.update_fields(tid, {
            f"toggles.{toggle_name}.goal_offered_at": None,
            f"toggles.{toggle_name}.goal_value": None,
        })

    # ------------------------------------------------------------------
    # Goal value collection
    # ------------------------------------------------------------------

    def handle_goal_value(self, tid: int, toggle_name: str, raw_value: str) -> str:
        """Extract and store the goal value using GPT - no format requirements."""
        import messages as M

        extraction_types = {
            "sleep": "sleep_time",
            "workouts": "workout_count",
            "eating_window": "eating_window",
        }
        goal_type = extraction_types.get(toggle_name)
        if not goal_type or not self._analyzer:
            pool = self._get_goal_value_ask_pool(toggle_name)
            return random.choice(pool)

        recent = self._user_repo.get_recent_messages(tid, 5)
        parsed = self._analyzer.extract_goal_value(
            raw_value, goal_type, recent_messages=recent,
        )
        if parsed is None:
            pool = self._get_goal_value_ask_pool(toggle_name)
            return random.choice(pool)

        self._toggle_service.set_goal_value(tid, toggle_name, parsed)

        # For eating_window, also update the User.eating_window field
        if toggle_name == "eating_window" and "start" in parsed and "end" in parsed:
            self._user_repo.update_fields(tid, {
                "eating_window": {"start": parsed["start"], "end": parsed["end"]},
            })

        pool = self._get_goal_set_pool(toggle_name)
        text = random.choice(pool)
        loop_close = M.LOOP_CLOSE_GOAL_SET.get(toggle_name, "")
        return text + loop_close

    # ------------------------------------------------------------------
    # Goal remind (yes/no to "want me to remind you?")
    # ------------------------------------------------------------------

    def handle_remind_accept(self, tid: int, toggle_name: str) -> str:
        """User agreed to be reminded later. Set reminder."""
        import messages as M

        days = HOOK_CONFIG.get(toggle_name, {}).get(
            "goal_reminder_days", DEFAULT_GOAL_REMINDER_DAYS,
        )
        remind_at = datetime.now(timezone.utc) + timedelta(days=days)
        self._toggle_service.set_goal_status(tid, toggle_name, "remind", remind_at)
        return random.choice(M.GOAL_REMIND_SCHEDULED)

    # ------------------------------------------------------------------
    # Goal reminders (check + fire)
    # ------------------------------------------------------------------

    def check_goal_reminders(self, profile: User) -> list[str]:
        """Return toggle names with due goal reminders."""
        now = datetime.now(timezone.utc)
        due = []
        for name in ("sleep", "eating_window", "workouts", "nutrition"):
            toggle = getattr(profile.toggles, name, None)
            if toggle is None:
                continue
            if toggle.goal_status != "remind":
                continue
            if toggle.goal_remind_at and toggle.goal_remind_at <= now:
                due.append(name)
        return due

    def fire_goal_reminder(self, tid: int, toggle_name: str) -> str:
        """Re-offer a goal after a reminder period."""
        import messages as M

        pool = self._get_goal_reminder_pool(toggle_name)
        text = random.choice(pool)

        self._toggle_service.set_goal_offered(tid, toggle_name)
        return text

    # ------------------------------------------------------------------
    # Nutrition special flow
    #
    # body stats → weight goal (lose/keep/gain) → GPT suggests → user confirms/corrects
    # ------------------------------------------------------------------

    def start_nutrition_onboarding(self, tid: int) -> str:
        """Start the nutrition goal flow: collect body stats first."""
        import messages as M

        text = random.choice(M.NUTRITION_BODY_STATS_ASK)
        self._toggle_service.set_goal_offered(tid, "nutrition")
        # Clear goal_value for clean slate (used as step 3 signal by handler)
        self._user_repo.update_fields(tid, {"toggles.nutrition.goal_value": None})
        return text

    def handle_body_stats(self, tid: int, text: str) -> str:
        """Extract height, weight, age from natural text using GPT."""
        import messages as M

        if not self._analyzer:
            return random.choice(M.NUTRITION_BODY_STATS_ASK)

        parsed = self._analyzer.extract_goal_value(text, "body_stats")
        if not parsed or not parsed.get("height_cm") or not parsed.get("weight_kg") or not parsed.get("age"):
            return random.choice(M.NUTRITION_BODY_STATS_ASK)

        height = parsed["height_cm"]
        weight = parsed["weight_kg"]
        age = int(parsed["age"])
        birth_year = datetime.now().year - age

        self._user_repo.update_fields(tid, {
            "height_cm": height,
            "weight_kg": weight,
            "birth_year": birth_year,
        })

        return random.choice(M.NUTRITION_WEIGHT_GOAL_ASK)

    def handle_weight_goal(self, tid: int, text: str, profile: User | None = None) -> str:
        """User told us their weight goal. Calculate targets and present suggestion."""
        import messages as M

        if not self._analyzer or not profile:
            logger.error("FATAL ERROR CONVERSATION BREAKER: no analyzer or profile for nutrition calc, tid=%d", tid)
            return "משהו השתבש אצלי. ננסה שוב בהודעה הבאה."

        height = profile.height_cm or 170
        weight = profile.weight_kg or 70
        age = datetime.now().year - profile.birth_year if profile.birth_year else 30

        suggestion = self._analyzer.suggest_targets(height, weight, age, text)

        if not suggestion:
            return "לא הצלחתי לחשב עכשיו. ננסה שוב בהודעה הבאה."

        cal = suggestion.get("target_calories", 2000)
        prot = suggestion.get("target_protein", 150)

        # Store suggestion temporarily so confirm handler can access it
        weight_goal = suggestion.get("weight_goal", "maintain")
        update_fields = {
            "toggles.nutrition.goal_value": {"calories": cal, "protein": prot},
            "targets.weight_goal": weight_goal,
        }
        self._user_repo.update_fields(tid, update_fields)

        return random.choice(M.NUTRITION_SUGGESTION).format(calories=cal, protein=prot)

    def handle_nutrition_confirm(self, tid: int, text: str) -> str:
        """User responded to nutrition suggestion. conversation_reply = cooperation.

        Handles three cases:
        1. User provides both calories AND protein -> use both
        2. User adjusts only ONE value -> merge with original suggestion
        3. User accepts without numbers -> keep original suggestion
        All paths sync targets.calories/protein for weekly feedback.
        """
        import messages as M

        loop_close = M.LOOP_CLOSE_GOAL_SET.get("nutrition", "")

        # Load original suggestion from profile
        profile = self._user_repo.get(tid)
        original = (profile.toggles.nutrition.goal_value or {}) if profile else {}

        # Try to extract corrected numbers from natural text
        if self._analyzer:
            parsed = self._analyzer.extract_goal_value(text, "nutrition_targets")
            if parsed and (parsed.get("calories") or parsed.get("protein")):
                # Merge: user's value wins, fall back to original suggestion
                cal = parsed.get("calories") or original.get("calories", 2000)
                prot = parsed.get("protein") or original.get("protein", 150)
                merged = {"calories": cal, "protein": prot}
                self._toggle_service.set_goal_value(tid, "nutrition", merged)
                self._user_repo.update_fields(tid, {
                    "targets.calories": cal, "targets.protein": prot,
                })
                return random.choice(self._get_goal_set_pool("nutrition")) + loop_close

        # No corrected numbers - accept original suggestion, sync targets
        cal = original.get("calories", 2000)
        prot = original.get("protein", 150)
        self._toggle_service.set_goal_status(tid, "nutrition", "set")
        self._user_repo.update_fields(tid, {
            "targets.calories": cal, "targets.protein": prot,
        })
        return random.choice(self._get_goal_set_pool("nutrition")) + loop_close

    # ------------------------------------------------------------------
    # User-initiated goal update (toggle already active with goal set)
    # ------------------------------------------------------------------

    def handle_goal_update(
        self, tid: int, toggle_name: str, text: str, profile: User,
    ) -> str | None:
        """User wants to update an existing goal.

        If the user's message contains the new value, extract and update
        directly. Otherwise, re-enter the goal flow (ask for value).
        Returns None if the habit has no goal (e.g. self_care).
        """
        import messages as M

        config = HOOK_CONFIG.get(toggle_name, {})
        if not config.get("has_goal", False):
            return None

        extraction_types = {
            "sleep": "sleep_time",
            "workouts": "workout_count",
            "eating_window": "eating_window",
            "nutrition": "nutrition_targets",
        }
        goal_type = extraction_types.get(toggle_name)

        # Try to extract value from user's text (shortcut)
        if goal_type and self._analyzer:
            parsed = self._analyzer.extract_goal_value(text, goal_type)
            if parsed is not None:
                # Nutrition: merge partial values with existing goal
                if toggle_name == "nutrition":
                    original = (profile.toggles.nutrition.goal_value or {})
                    cal = parsed.get("calories") or original.get("calories", 2000)
                    prot = parsed.get("protein") or original.get("protein", 150)
                    parsed = {"calories": cal, "protein": prot}
                    self._user_repo.update_fields(tid, {
                        "targets.calories": cal, "targets.protein": prot,
                    })

                self._toggle_service.set_goal_value(tid, toggle_name, parsed)

                # Sync eating_window field
                if toggle_name == "eating_window" and "start" in parsed and "end" in parsed:
                    self._user_repo.update_fields(tid, {
                        "eating_window": {"start": parsed["start"], "end": parsed["end"]},
                    })

                pool = self._get_goal_set_pool(toggle_name)
                loop_close = M.LOOP_CLOSE_GOAL_SET.get(toggle_name, "")
                return random.choice(pool) + loop_close

        # No value found - re-enter goal flow
        if toggle_name == "nutrition":
            # Skip body stats (already stored), ask for specific numbers
            self._toggle_service.set_goal_offered(tid, "nutrition")
            return random.choice(M.GOAL_VALUE_ASK_NUTRITION)
        else:
            # Re-offer goal question for other habits
            self._toggle_service.set_goal_offered(tid, toggle_name)
            pool = self._get_goal_value_ask_pool(toggle_name)
            return random.choice(pool)

    # ------------------------------------------------------------------
    # Ghosting detection (called by poller)
    # ------------------------------------------------------------------

    def check_ghosting(self, profile: User) -> None:
        """Check if any goal flow has been ghosted (offer scrolled out of history).

        Called by the poller. If a toggle has goal_offered_at set but
        goal_status is still 'pending' and enough time has passed,
        auto-set a reminder.
        """
        tid = profile.telegram_user_id
        now = datetime.now(timezone.utc)

        for name in ("nutrition", "sleep", "eating_window", "workouts"):
            toggle = getattr(profile.toggles, name, None)
            if not toggle or not toggle.goal_offered_at:
                continue
            if toggle.goal_status not in ("pending",):
                continue
            # Check if enough time has passed (use goal_reminder_days as threshold)
            days = HOOK_CONFIG.get(name, {}).get(
                "goal_reminder_days", DEFAULT_GOAL_REMINDER_DAYS,
            )
            elapsed = (now - toggle.goal_offered_at).total_seconds() / 86400
            if elapsed >= days:
                remind_at = now + timedelta(days=days)
                self._toggle_service.set_goal_status(tid, name, "remind", remind_at)
                logger.info("Ghosting detected for %s/%d, reminder set for %s", name, tid, remind_at)

    # ------------------------------------------------------------------
    # Message pool helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_goal_offer_pool(toggle_name: str) -> list[str]:
        import messages as M
        pools = {
            "sleep": M.GOAL_OFFER_SLEEP,
            "workouts": M.GOAL_OFFER_WORKOUTS,
            "eating_window": M.GOAL_OFFER_EATING_WINDOW,
            "nutrition": M.GOAL_OFFER_NUTRITION,
        }
        return pools.get(toggle_name, M.GOAL_OFFER_SLEEP)

    @staticmethod
    def _get_goal_value_ask_pool(toggle_name: str) -> list[str]:
        import messages as M
        pools = {
            "sleep": M.GOAL_VALUE_ASK_SLEEP,
            "workouts": M.GOAL_VALUE_ASK_WORKOUTS,
            "eating_window": M.GOAL_VALUE_ASK_EATING_WINDOW,
        }
        return pools.get(toggle_name, [M.GOAL_VALUE_ASK_SLEEP[0]])

    @staticmethod
    def _get_goal_set_pool(toggle_name: str) -> list[str]:
        import messages as M
        pools = {
            "sleep": M.GOAL_SET_SLEEP,
            "workouts": M.GOAL_SET_WORKOUTS,
            "eating_window": M.GOAL_SET_EATING_WINDOW,
            "nutrition": M.GOAL_SET_NUTRITION,
        }
        return pools.get(toggle_name, M.GOAL_SET_SLEEP)

    @staticmethod
    def _get_goal_reminder_pool(toggle_name: str) -> list[str]:
        import messages as M
        pools = {
            "sleep": M.GOAL_REMINDER_SLEEP,
            "workouts": M.GOAL_REMINDER_WORKOUTS,
            "eating_window": M.GOAL_REMINDER_EATING_WINDOW,
            "nutrition": M.GOAL_REMINDER_NUTRITION,
        }
        return pools.get(toggle_name, M.GOAL_REMINDER_SLEEP)
