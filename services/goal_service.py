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
    "awaiting_nutrition_method",
    "awaiting_manual_targets",
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

    def handle_goal_consent(self, tid: int, toggle_name: str, accepted: bool) -> str:
        """Handle user's response to goal offer."""
        import messages as M

        if accepted:
            return self._ask_for_goal_value(tid, toggle_name)
        else:
            return self._ask_remind(tid, toggle_name)

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
        """Parse and store the goal value."""
        import messages as M

        parsed = self._parse_goal_value(toggle_name, raw_value)
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

    def _parse_goal_value(self, toggle_name: str, raw: str) -> dict | None:
        """Parse raw text into a goal value dict. Returns None if invalid."""
        raw = raw.strip()

        if toggle_name == "sleep":
            import re
            m = re.match(r"^(\d{1,2}):(\d{2})$", raw)
            if m:
                h, mn = int(m.group(1)), m.group(2)
                return {"sleep_time": f"{h:02d}:{mn}"}
            return None

        if toggle_name == "workouts":
            try:
                n = int(raw)
                if 1 <= n <= 14:
                    return {"weekly_target": n}
            except ValueError:
                pass
            return None

        if toggle_name == "eating_window":
            import re
            m = re.match(r"^(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})$", raw)
            if m:
                return {"start": m.group(1), "end": m.group(2)}
            return None

        return None

    # ------------------------------------------------------------------
    # Goal remind (yes/no to "want me to remind you?")
    # ------------------------------------------------------------------

    def handle_goal_remind(self, tid: int, toggle_name: str, accepted: bool) -> str:
        """Handle user's response to reminder question."""
        import messages as M

        self._state_service.clear_pending(tid)

        if accepted:
            days = HOOK_CONFIG.get(toggle_name, {}).get(
                "goal_reminder_days", DEFAULT_GOAL_REMINDER_DAYS,
            )
            remind_at = datetime.now(timezone.utc) + timedelta(days=days)
            self._toggle_service.set_goal_status(tid, toggle_name, "remind", remind_at)
            return random.choice(M.GOAL_REMIND_SCHEDULED)
        else:
            self._toggle_service.set_goal_status(tid, toggle_name, "declined")
            return random.choice(M.GOAL_DECLINED_FOREVER)

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
    # ------------------------------------------------------------------

    def start_nutrition_onboarding(self, tid: int) -> str:
        """Start the nutrition goal flow: collect body stats first."""
        import messages as M

        text = random.choice(M.NUTRITION_BODY_STATS_ASK)
        self._state_service.set_pending(tid, "awaiting_body_stats")
        self._toggle_service.set_goal_offered(tid, "nutrition")
        return text

    def handle_body_stats(self, tid: int, text: str) -> str | None:
        """Parse height, weight, age from user text. Store on user profile."""
        import messages as M

        parts = [p.strip() for p in text.replace("/", ",").replace(" ", ",").split(",") if p.strip()]
        nums = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                continue

        if len(nums) < 3:
            return random.choice(M.NUTRITION_BODY_STATS_ASK)

        height, weight, age = nums[0], nums[1], int(nums[2])
        birth_year = datetime.now().year - age

        self._user_repo.update_fields(tid, {
            "height_cm": height,
            "weight_kg": weight,
            "birth_year": birth_year,
        })

        self._state_service.set_pending(tid, "awaiting_nutrition_method")
        return random.choice(M.NUTRITION_METHOD_ASK)

    def handle_nutrition_method(self, tid: int, text: str, profile: User | None = None) -> str:
        """Handle 'GPT suggest or manual?' response."""
        import messages as M

        lower = text.strip().lower()
        manual_keywords = ("בעצמי", "ידני", "manual", "לבד", "אני")
        is_manual = any(kw in lower for kw in manual_keywords)

        if is_manual:
            self._state_service.set_pending(tid, "awaiting_manual_targets")
            return random.choice(M.NUTRITION_MANUAL_ASK)

        # GPT suggest path
        if self._analyzer and profile:
            height = profile.height_cm or 170
            weight = profile.weight_kg or 70
            age = datetime.now().year - profile.birth_year if profile.birth_year else 30
            suggestion = self._analyzer.suggest_targets(height, weight, age)
            if suggestion:
                cal = suggestion.get("target_calories", 2000)
                prot = suggestion.get("target_protein", 150)
                self._toggle_service.set_goal_value(
                    tid, "nutrition", {"calories": cal, "protein": prot},
                )
                self._state_service.clear_pending(tid)
                pool = self._get_goal_set_pool("nutrition")
                return random.choice(pool)

        # Fallback if GPT fails
        self._state_service.set_pending(tid, "awaiting_manual_targets")
        return random.choice(M.NUTRITION_MANUAL_ASK)

    def handle_manual_targets(self, tid: int, text: str) -> str:
        """Parse manual calorie/protein entry."""
        import messages as M

        parts = [p.strip() for p in text.replace("/", ",").split(",") if p.strip()]
        nums = []
        for p in parts:
            try:
                nums.append(int(float(p)))
            except ValueError:
                continue

        if len(nums) < 2:
            return random.choice(M.NUTRITION_MANUAL_ASK)

        cal, prot = nums[0], nums[1]
        self._toggle_service.set_goal_value(
            tid, "nutrition", {"calories": cal, "protein": prot},
        )
        self._state_service.clear_pending(tid)

        pool = self._get_goal_set_pool("nutrition")
        return random.choice(pool)

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
            if kind in ("awaiting_body_stats", "awaiting_nutrition_method", "awaiting_manual_targets"):
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
