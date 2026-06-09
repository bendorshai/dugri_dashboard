"""
qa_service.py — עונה על שאלות על נתוני המשתמש.

טריפ שני: היסטוריית האכילה של המשתמש כ-context + השאלה.

תלוי ב: analyzer, repositories/food_repository.
נצרך על ידי: services/message_router_service.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from analyzer import FoodAnalyzer
from repositories.food_repository import FoodRepository


class QaService:
    def __init__(self, analyzer: FoodAnalyzer, food_repo: FoodRepository):
        self._analyzer = analyzer
        self._food_repo = food_repo

    def answer(
        self, telegram_user_id: int, question_text: str,
        today_str: str, target_cal: int, target_prot: int,
    ) -> str:
        today = datetime.strptime(today_str, "%d/%m/%Y").date()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]

        entries = self._food_repo.get_by_user_and_dates(telegram_user_id, dates)
        csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון"]
        for e in entries:
            csv_lines.append(f"{e.date},{e.time},{e.description},{e.calories},{e.protein}")
        week_csv = "\n".join(csv_lines)

        targets = {"calories": target_cal, "protein": target_prot}
        return self._analyzer.answer_question(question_text, week_csv, targets, today_str=today_str) or "לא הצלחתי לענות."
