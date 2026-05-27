"""
goal_service.py — per-habit goal lifecycle orchestration.

Handles the multi-step goal conversation for each habit:
  activate tracking -> offer goal -> collect value -> set/decline/remind

Each habit owns its goal independently. Nutrition has a special flow
(body stats -> GPT suggestion or manual entry).

Depends on: toggle_service, conversation_state_service, user_repository, analyzer.
Used by: handlers/base.py, scheduler.py.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from constants import HOOK_CONFIG, DEFAULT_GOAL_REMINDER_DAYS
from models.profile import User
from repositories.user_repository import UserRepository
from services.conversation_state_service import ConversationStateService
from services.toggle_service import ToggleService

logger = logging.getLogger(__name__)

# Pending state kinds owned by GoalService
GOAL_PENDING_KINDS = frozenset({
    "awaiting_goal_consent",
    "awaiting_goal_value",
    "awaiting_goal_remind",
    "awaiting_body_stats",
    "awaiting_weight_goal",
    "awaiting_nutrition_confirm",
})


class GoalService:
    def __init__(
        self,
        user_repo: UserRepository,
        state_service: ConversationStateService,
        toggle_service: ToggleService,
        analyzer=None,
    ):
        self._user_repo = user_repo
        self._state_service = state_service
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
        """Offer a goal for the given habit. Sets pending state."""
        import messages as M

        if toggle_name == "nutrition":
            return self.start_nutrition_onboarding(tid)

        pool = self._get_goal_offer_pool(toggle_name)
        text = random.choice(pool)

        self._state_service.set_pending(
            tid, "awaiting_goal_consent", data={"toggle_name": toggle_name},
        )
        self._toggle_service.set_goal_offered(tid, toggle_name)
        return text

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

        self._state_service.set_pending(
            tid, "awaiting_goal_value", data={"toggle_name": toggle_name},
        )
        return text

    def _ask_remind(self, tid: int, toggle_name: str) -> str:
        """Ask if user wants to be reminded later."""
        import messages as M

        text = random.choice(M.GOAL_DECLINED_REMIND_ASK)
        self._state_service.set_pending(
            tid, "awaiting_goal_remind", data={"toggle_name": toggle_name},
        )
        return text

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

        parsed = self._analyzer.extract_goal_value(raw_value, goal_type)
        if parsed is None:
            pool = self._get_goal_value_ask_pool(toggle_name)
            return random.choice(pool)

        self._toggle_service.set_goal_value(tid, toggle_name, parsed)
        self._state_service.clear_pending(tid)

        # For eating_window, also update the User.eating_window field
        if toggle_name == "eating_window" and "start" in parsed and "end" in parsed:
            self._user_repo.update_fields(tid, {
                "eating_window": {"start": parsed["start"], "end": parsed["end"]},
            })

        pool = self._get_goal_set_pool(toggle_name)
        return random.choice(pool)

    # ------------------------------------------------------------------
    # Goal remind (yes/no to "want me to remind you?")
    # ------------------------------------------------------------------

    def handle_remind_accept(self, tid: int, toggle_name: str) -> str:
        """User agreed to be reminded later. Set reminder."""
        import messages as M

        self._state_service.clear_pending(tid)
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
        """Re-offer a goal after a reminder period. Sets pending state."""
        import messages as M

        pool = self._get_goal_reminder_pool(toggle_name)
        text = random.choice(pool)

        self._state_service.set_pending(
            tid, "awaiting_goal_consent", data={"toggle_name": toggle_name},
        )
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
        self._state_service.set_pending(tid, "awaiting_body_stats")
        self._toggle_service.set_goal_offered(tid, "nutrition")
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

        self._state_service.set_pending(tid, "awaiting_weight_goal")
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
            # Keep pending at awaiting_weight_goal so next message retries
            # Store the weight goal text so we don't lose it
            self._state_service.set_pending(
                tid, "awaiting_weight_goal", data={"weight_goal_text": text},
            )
            return "לא הצלחתי לחשב עכשיו. ננסה שוב בהודעה הבאה."

        cal = suggestion.get("target_calories", 2000)
        prot = suggestion.get("target_protein", 150)

        # Store suggestion temporarily so confirm handler can access it
        self._user_repo.update_fields(tid, {
            "toggles.nutrition.goal_value": {"calories": cal, "protein": prot},
        })

        self._state_service.set_pending(tid, "awaiting_nutrition_confirm",
                                        data={"calories": cal, "protein": prot})
        return random.choice(M.NUTRITION_SUGGESTION).format(calories=cal, protein=prot)

    def handle_nutrition_confirm(self, tid: int, text: str) -> str:
        """User responded to nutrition suggestion. conversation_reply = cooperation.

        Try to extract corrected numbers via GPT. If none found, accept
        the original suggestion. Refusals are caught by toggle_cancel.
        """
        import messages as M

        # Try to extract corrected numbers from natural text
        if self._analyzer:
            parsed = self._analyzer.extract_goal_value(text, "nutrition_targets")
            if parsed and parsed.get("calories") and parsed.get("protein"):
                self._toggle_service.set_goal_value(tid, "nutrition",
                                                    {"calories": parsed["calories"], "protein": parsed["protein"]})
                self._state_service.clear_pending(tid)
                return random.choice(self._get_goal_set_pool("nutrition"))

        # No corrected numbers - accept the original suggestion
        self._toggle_service.set_goal_status(tid, "nutrition", "set")
        self._state_service.clear_pending(tid)
        return random.choice(self._get_goal_set_pool("nutrition"))

    # ------------------------------------------------------------------
    # Ghosting handler
    # ------------------------------------------------------------------

    def handle_expired_goal_pending(
        self, tid: int, kind: str, data: dict,
    ) -> None:
        """Called when a goal-related pending state expires (ghosting).
        Auto-sets a goal reminder so we ask again later.
        """
        if kind not in GOAL_PENDING_KINDS:
            return

        toggle_name = data.get("toggle_name")
        if not toggle_name:
            # For nutrition-specific kinds without toggle_name in data
            if kind in ("awaiting_body_stats", "awaiting_weight_goal", "awaiting_nutrition_confirm"):
                toggle_name = "nutrition"
            else:
                return

        days = HOOK_CONFIG.get(toggle_name, {}).get(
            "goal_reminder_days", DEFAULT_GOAL_REMINDER_DAYS,
        )
        remind_at = datetime.now(timezone.utc) + timedelta(days=days)
        self._toggle_service.set_goal_status(tid, toggle_name, "remind", remind_at)
        logger.info("Ghosting detected for %s/%d, reminder set for %s", toggle_name, tid, remind_at)

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
