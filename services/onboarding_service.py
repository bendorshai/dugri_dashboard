"""
onboarding_service.py — אונבורדינג הדרגתי של משתמש חדש.

מנהל את ההיכרות הראשונית (שם, הסבר, ארוחה ראשונה) ואת ההצעות
ההדרגתיות של הרגלים ברגעים הטבעיים שלהם.

תלוי ב: repositories/user_repository, services/conversation_state_service.
נצרך על ידי: handlers/start_handler, handlers/base.
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.profile import UserProfile
from repositories.user_repository import UserRepository
from services.conversation_state_service import ConversationStateService


class OnboardingService:
    def __init__(self, user_repo: UserRepository, state_service: ConversationStateService):
        self._user_repo = user_repo
        self._state_service = state_service

    def start_onboarding(self, telegram_user_id: int) -> str:
        """Begin onboarding after successful linking. Returns the greeting message."""
        self._state_service.set_pending(telegram_user_id, "awaiting_name")
        return (
            "היי, אני דוגרי 👋\n\n"
            "הלב של מה שאני עושה הוא מודעות תזונתית — "
            "שלח לי את הארוחה הבאה שלך בכמה מילים ואני אעשה את החישוב.\n\n"
            "לפני שמתחילים, איך אתה רוצה שאקרא לך?"
        )

    def handle_name_response(self, telegram_user_id: int, name: str) -> str:
        """Process the user's name response."""
        self._user_repo.update_fields(telegram_user_id, {
            "name": name,
            "onboarding.name_collected": True,
        })
        self._state_service.clear_pending(telegram_user_id)

        return (
            f"נעים להכיר, {name}.\n\n"
            "מעכשיו, כל מה שתשלח לי — טקסט או תמונה של אוכל — "
            "אני אחשב קלוריות וחלבון.\n\n"
            "בוא נתחיל. מה אכלת?"
        )

    def should_offer_calorie_target(self, profile: UserProfile, meal_count: int) -> bool:
        """Should we offer calorie/protein targets? After first meal."""
        if meal_count != 1:
            return False
        habit = profile.onboarding.habits.nutrition
        return habit.state == "pending"

    def offer_calorie_target(self, telegram_user_id: int) -> str:
        """Offer to suggest calorie/protein targets."""
        self._state_service.set_pending(telegram_user_id, "awaiting_calorie_target_consent")
        self._user_repo.update_fields(telegram_user_id, {
            "onboarding.habits.nutrition.state": "offered",
            "onboarding.habits.nutrition.last_prompted_at": datetime.now(timezone.utc).isoformat(),
        })
        return (
            "\n\nרוצה שאציע יעד יומי של קלוריות וחלבון לפי נתוני הגוף שלך? "
            "אצטרך גובה, משקל וגיל."
        )

    def should_offer_eating_window(self, profile: UserProfile, meal_count: int) -> bool:
        """Should we offer eating window tracking? After first meal."""
        if meal_count != 1:
            return False
        habit = profile.onboarding.habits.eating_window
        return habit.state == "pending"

    def offer_eating_window(self, telegram_user_id: int) -> str:
        """Offer eating window tracking."""
        self._state_service.set_pending(telegram_user_id, "awaiting_eating_window_consent")
        self._user_repo.update_fields(telegram_user_id, {
            "onboarding.habits.eating_window.state": "offered",
            "onboarding.habits.eating_window.last_prompted_at": datetime.now(timezone.utc).isoformat(),
        })
        return "רוצה שגם נעקוב אחרי חלון האכילה? (כן/לא)"

    def should_offer_sleep(self, profile: UserProfile, hour: int) -> bool:
        """Should we offer sleep tracking? When active late at night or early morning."""
        if not (hour >= 22 or hour <= 6):
            return False
        habit = profile.onboarding.habits.sleep
        return habit.state == "pending"

    def offer_sleep(self, telegram_user_id: int) -> str:
        """Offer sleep tracking."""
        self._state_service.set_pending(telegram_user_id, "awaiting_sleep_consent")
        self._user_repo.update_fields(telegram_user_id, {
            "onboarding.habits.sleep.state": "offered",
            "onboarding.habits.sleep.last_prompted_at": datetime.now(timezone.utc).isoformat(),
        })
        return "בוקר טוב. אם בא לך, נעקוב גם אחרי שעת השינה? (כן/לא)"

    def should_offer_workouts(self, profile: UserProfile, days_since_signup: int) -> bool:
        """Should we offer workout tracking? End of first week."""
        if days_since_signup < 7:
            return False
        habit = profile.onboarding.habits.workouts
        return habit.state == "pending"

    def offer_workouts(self, telegram_user_id: int) -> str:
        """Offer workout tracking."""
        self._state_service.set_pending(telegram_user_id, "awaiting_workouts_consent")
        self._user_repo.update_fields(telegram_user_id, {
            "onboarding.habits.workouts.state": "offered",
            "onboarding.habits.workouts.last_prompted_at": datetime.now(timezone.utc).isoformat(),
        })
        return "השבוע הראשון מאחורינו. לעקוב גם אחרי אימונים? (כן/לא)"

    def should_offer_self_care(self, profile: UserProfile, days_since_signup: int) -> bool:
        """Should we offer self-care tracking? Start of second week."""
        if days_since_signup < 10:
            return False
        habit = profile.onboarding.habits.self_care
        return habit.state == "pending"

    def offer_self_care(self, telegram_user_id: int) -> str:
        """Offer self-care tracking."""
        self._state_service.set_pending(telegram_user_id, "awaiting_self_care_consent")
        self._user_repo.update_fields(telegram_user_id, {
            "onboarding.habits.self_care.state": "offered",
            "onboarding.habits.self_care.last_prompted_at": datetime.now(timezone.utc).isoformat(),
        })
        return "אם בא לך, נסמן יחד משהו נחמד שאתה עושה לעצמך השבוע. (כן/לא)"

    def handle_consent_response(
        self, telegram_user_id: int, kind: str, accepted: bool,
    ) -> str:
        """Handle yes/no response to a habit offer."""
        habit_map = {
            "awaiting_calorie_target_consent": "nutrition",
            "awaiting_eating_window_consent": "eating_window",
            "awaiting_sleep_consent": "sleep",
            "awaiting_workouts_consent": "workouts",
            "awaiting_self_care_consent": "self_care",
        }
        habit_name = habit_map.get(kind)
        if not habit_name:
            return ""

        new_state = "active" if accepted else "declined"
        self._user_repo.update_fields(telegram_user_id, {
            f"onboarding.habits.{habit_name}.state": new_state,
        })
        self._state_service.clear_pending(telegram_user_id)

        if accepted:
            if habit_name == "nutrition":
                self._user_repo.update_fields(telegram_user_id, {
                    "active_habits": ["nutrition"],
                })
                self._state_service.set_pending(telegram_user_id, "awaiting_body_stats")
                return "מעולה. שלח לי גובה (ס\"מ), משקל (ק\"ג) וגיל — בשורה אחת, מופרדים בפסיקים."
            elif habit_name == "eating_window":
                self._state_service.set_pending(telegram_user_id, "awaiting_eating_window")
                return "מתי חלון האכילה שלך? שלח בפורמט: HH:MM-HH:MM (למשל: 08:00-20:00)"

            return "יפה, נרשמתי."
        else:
            return "בסדר, נשאר ככה. אם תרצה בעתיד — אפשר מהתפריט."
