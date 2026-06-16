"""
message_router_service.py - מנתב הודעות מסווגות ל-service הנכון.

מקבל תוצאת-סיווג מהמסווג ומנתב ל-service הנכון. זה ה-glue
שמתרגם type -> פעולה.

תלוי ב: services (habit, qa, help), repositories (food).
נצרך על ידי: handlers/base.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from services.habit_service import HabitService
from services.qa_service import QaService
from services.help_service import HelpService

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    response_text: str
    light_confirmation: bool = False
    entry_id: str | None = None


class MessageRouterService:
    def __init__(
        self,
        habit_service: HabitService,
        qa_service: QaService,
        help_service: HelpService,
        feature_request_repo=None,
        analyzer=None,
        user_repo=None,
    ):
        self._habit = habit_service
        self._qa = qa_service
        self._help = help_service
        self._feature_request_repo = feature_request_repo
        self._analyzer = analyzer
        self._user_repo = user_repo

    def route_sleep(
        self, telegram_user_id: int, sleep_time: str, date: str,
        date_label: str | None = None,
    ) -> RouteResult:
        saved = self._habit.log_sleep(telegram_user_id, sleep_time, date)
        if date_label:
            text = f"רשמתי שינה ב-{sleep_time} ביום {date_label}."
        else:
            text = f"רשמתי שינה ב-{sleep_time}."
        return RouteResult(
            response_text=text,
            light_confirmation=True,
            entry_id=saved.id,
        )

    def route_workout(
        self, telegram_user_id: int, date: str, note: str | None = None,
        date_label: str | None = None,
    ) -> RouteResult:
        saved = self._habit.log_workout(telegram_user_id, date, note)
        if date_label:
            text = f"רשמתי אימון ביום {date_label}."
        else:
            text = "רשמתי אימון."
        return RouteResult(
            response_text=text,
            light_confirmation=True,
            entry_id=saved.id,
        )

    def route_self_care(
        self, telegram_user_id: int, description: str, date: str,
        date_label: str | None = None,
    ) -> RouteResult:
        saved = self._habit.log_self_care(telegram_user_id, description, date)

        if self._analyzer and self._user_repo:
            normalized = self._analyzer.normalize_self_care_activity(description)
            if normalized:
                self._user_repo.increment_activity(telegram_user_id, normalized)

        if date_label:
            text = f"יפה. רשמתי 'משהו לעצמי' ביום {date_label}."
        else:
            text = "יפה. רשמתי 'משהו לעצמי' השבוע."
        return RouteResult(
            response_text=text,
            light_confirmation=True,
            entry_id=saved.id,
        )

    def route_help(
        self,
        question_text: str,
        recent_messages: list[dict] | None = None,
        telegram_user_id: int | None = None,
    ) -> RouteResult:
        result = self._help.answer(question_text, recent_messages=recent_messages)

        if result.knowledge_gap and self._feature_request_repo and telegram_user_id:
            try:
                self._feature_request_repo.log(
                    telegram_user_id=telegram_user_id,
                    question_text=question_text,
                    bot_response=result.response_text,
                    request_type="knowledge_gap",
                    chat_history=recent_messages,
                )
            except Exception:
                logger.exception("Failed to log feature request")

        return RouteResult(response_text=result.response_text)

    def route_feature_request(
        self,
        telegram_user_id: int,
        message_text: str,
        request_type: str,
        bot_response: str,
        message_id: int | None = None,
        chat_id: int | None = None,
        chat_history: list[dict] | None = None,
    ) -> RouteResult:
        if self._feature_request_repo:
            try:
                self._feature_request_repo.log(
                    telegram_user_id=telegram_user_id,
                    question_text=message_text,
                    bot_response=bot_response,
                    request_type=request_type,
                    message_id=message_id,
                    chat_id=chat_id,
                    chat_history=chat_history,
                )
            except Exception:
                logger.exception("Failed to log feature request")
        return RouteResult(response_text=bot_response)

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
