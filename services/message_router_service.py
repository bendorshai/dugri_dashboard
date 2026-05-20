"""
message_router_service.py — מנתב הודעות מסווגות ל-service הנכון.

מקבל תוצאת-סיווג מהמסווג ומנתב ל-service הנכון. זה ה-glue
שמתרגם type -> פעולה.

תלוי ב: services (habit, qa, help), repositories (food).
נצרך על ידי: handlers/base.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.habit_service import HabitService
from services.qa_service import QaService
from services.help_service import HelpService


@dataclass
class RouteResult:
    response_text: str
    light_confirmation: bool = False


class MessageRouterService:
    def __init__(
        self,
        habit_service: HabitService,
        qa_service: QaService,
        help_service: HelpService,
    ):
        self._habit = habit_service
        self._qa = qa_service
        self._help = help_service

    def route_sleep(
        self, telegram_user_id: int, sleep_time: str, date: str,
    ) -> RouteResult:
        self._habit.log_sleep(telegram_user_id, sleep_time, date)
        return RouteResult(
            response_text=f"רשמתי שינה ב-{sleep_time}. (אם התכוונת למשהו אחר, תכתוב לי.)",
            light_confirmation=True,
        )

    def route_workout(
        self, telegram_user_id: int, date: str, note: str | None = None,
    ) -> RouteResult:
        self._habit.log_workout(telegram_user_id, date, note)
        return RouteResult(
            response_text="רשמתי אימון. (אם התכוונת למשהו אחר, תכתוב לי.)",
            light_confirmation=True,
        )

    def route_self_care(
        self, telegram_user_id: int, description: str, week_id: str,
    ) -> RouteResult:
        self._habit.log_self_care(telegram_user_id, description, week_id)
        return RouteResult(
            response_text="יפה. רשמתי 'משהו לעצמי' השבוע.",
            light_confirmation=True,
        )

    def route_help(self, question_text: str) -> RouteResult:
        answer = self._help.answer(question_text)
        return RouteResult(response_text=answer)

    def route_answer_question(
        self, telegram_user_id: int, question_text: str,
        today_str: str, target_cal: int, target_prot: int,
    ) -> RouteResult:
        answer = self._qa.answer(telegram_user_id, question_text, today_str, target_cal, target_prot)
        return RouteResult(response_text=answer)

    def route_feedback_request(self) -> RouteResult:
        return RouteResult(
            response_text="בקרוב אוסיף אפשרות לפידבק מותאם אישית. בינתיים, אפשר מכפתור הפידבק בתפריט.",
        )

    def route_none(self) -> RouteResult:
        return RouteResult(
            response_text="לא הבנתי. שלח לי תיאור של מה שאכלת, או הקלד /menu לתפריט.",
        )
