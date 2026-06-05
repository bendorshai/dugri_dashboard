"""
feedback_service.py — לולאת פידבק opt-in עם steering prompt נלמד.

הפידבק מונחה ע"י feedback_steering_prompt — מחרוזת יחידה שמתפתחת
שמרנית מתגובות המשתמש. מחליף את gpt_insights.

תלוי ב: analyzer, repositories (food, user, feedback).
נצרך על ידי: handlers/base.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from analyzer import FoodAnalyzer
from repositories.food_repository import FoodRepository
from repositories.user_repository import UserRepository
from repositories.feedback_repository import WeeklyFeedbackRepository


class FeedbackService:
    def __init__(
        self,
        analyzer: FoodAnalyzer,
        food_repo: FoodRepository,
        user_repo: UserRepository,
        feedback_repo: WeeklyFeedbackRepository,
    ):
        self._analyzer = analyzer
        self._food_repo = food_repo
        self._user_repo = user_repo
        self._feedback_repo = feedback_repo

    def give_feedback(
        self,
        telegram_user_id: int,
        today_str: str,
        target_cal: int,
        target_prot: int,
        steering_prompt: str | None,
        is_first_feedback: bool,
    ) -> str:
        """Generate opt-in feedback. Returns feedback text + closing question."""
        today = datetime.strptime(today_str, "%d/%m/%Y").date()
        dates = [(today - timedelta(days=i)).strftime("%d/%m/%Y") for i in range(7)]
        entries = self._food_repo.get_by_user_and_dates(telegram_user_id, dates)

        if not entries:
            return "אין נתונים מהשבוע האחרון לתת עליהם משוב."

        csv_lines = ["תאריך,שעה,תיאור,קלוריות,חלבון"]
        for e in entries:
            csv_lines.append(f"{e.date},{e.time},{e.description},{e.calories},{e.protein}")
        week_csv = "\n".join(csv_lines)

        targets = {"calories": target_cal, "protein": target_prot}
        past_fb = [f.get("feedback_text", "") for f in self._feedback_repo.get_recent(telegram_user_id, limit=7)]

        feedback_result = self._analyzer.generate_weekly_feedback(week_csv, targets, past_fb)
        feedback_text = (feedback_result or {}).get("feedback_text", "")
        if not feedback_text:
            return "לא הצלחתי לייצר משוב כרגע."

        # Save to database
        self._feedback_repo.save(
            telegram_user_id=telegram_user_id,
            date_str=today_str,
            feedback_text=feedback_text,
            week_summary={"target_cal": target_cal, "target_prot": target_prot},
        )

        # Add closing question
        if is_first_feedback:
            closing = (
                "\n\nאיך זה בשבילך? אגב, אנחנו עדיין לומדים להכיר... "
                "מה שתגיד לי אחרי פידבקים יכול ממש לשנות את הטון שלי."
            )
        else:
            closing = "\n\nעבד לך? יותר מדי? פחות?"

        return f"💬 {feedback_text}{closing}"

    def process_reaction(
        self, telegram_user_id: int, reaction_text: str, current_steering: str | None,
    ) -> str:
        """Process user's reaction to feedback. Conservatively rewrite steering prompt."""
        from prompts import STEERING_REWRITE_PROMPT

        prompt = STEERING_REWRITE_PROMPT.format(
            current_steering=current_steering or "(אין היגוי קיים — זה הפידבק הראשון)",
            user_reaction=reaction_text,
        )

        try:
            response = self._analyzer.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                ],
                temperature=0,
                max_tokens=300,
            )
            new_steering = response.choices[0].message.content or current_steering or ""
            # Save to profile
            self._user_repo.update_fields(telegram_user_id, {
                "feedback_steering_prompt": new_steering,
            })
            return "תודה, רשמתי. הפידבק הבא יהיה מותאם יותר."
        except Exception:
            return "רשמתי, תודה."

    def should_offer_weekly(self, last_offered_at: datetime | None, now: datetime) -> bool:
        """Check if it's time for the weekly feedback offer."""
        if last_offered_at is None:
            return True
        return (now - last_offered_at).days >= 7

    def is_first_feedback(self, telegram_user_id: int) -> bool:
        """Check if this is the user's first feedback interaction."""
        recent = self._feedback_repo.get_recent(telegram_user_id, limit=1)
        return len(recent) == 0
