"""
eating_day_service.py — לוגיקת יום-אכילה וסיכומים.

הקובץ הזה אחראי על חישוב "מה נכלל ביום-אכילה לוגי" — שזה לא בהכרח
יום קלנדרי. יום-אכילה רץ מ-window_start ביום X עד window_start ביום X+1.
ארוחה בשעה 02:00 בלילה שייכת ליום-האכילה הקודם.

תלוי ב: repositories/food_repository, models/profile, parsing.
נצרך על ידי: handlers, scheduler.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from models.food import FoodEntry
from models.profile import UserProfile
from parsing import is_within_eating_window, get_user_now
from repositories.food_repository import FoodRepository


class EatingDayService:
    def __init__(self, food_repo: FoodRepository):
        self._food_repo = food_repo

    def get_stats_date(self, profile: UserProfile, now: datetime) -> str:
        """איזה תאריך להציג סטטיסטיקות עבורו.

        בתוך החלון -> היום.
        אחרי סגירת החלון (ערב) -> היום (יום שהסתיים).
        לפני פתיחת החלון (בוקר) -> אתמול.
        """
        window_start = profile.eating_window.start if profile.eating_window else "08:00"
        window_end = profile.eating_window.end if profile.eating_window else "20:00"

        if is_within_eating_window(now, window_start, window_end):
            return now.strftime("%d/%m/%Y")

        current_minutes = now.hour * 60 + now.minute
        start_h, start_m = int(window_start.split(":")[0]), int(window_start.split(":")[1])
        start_minutes = start_h * 60 + start_m

        if current_minutes < start_minutes:
            yesterday = now - timedelta(days=1)
            return yesterday.strftime("%d/%m/%Y")
        return now.strftime("%d/%m/%Y")

    def get_eating_day_entries(
        self, profile: UserProfile, date_str: str,
    ) -> list[FoodEntry]:
        """כל הרשומות של יום-אכילה לוגי. מקור-אמת יחיד לתצוגות יומיות."""
        day = datetime.strptime(date_str, "%d/%m/%Y").date()
        next_day_str = (day + timedelta(days=1)).strftime("%d/%m/%Y")
        window_start = profile.eating_window.start if profile.eating_window else "08:00"

        entries = self._food_repo.get_by_user_and_dates(
            profile.telegram_user_id, [date_str, next_day_str],
        )

        results = []
        for entry in entries:
            if entry.date == date_str:
                if not entry.time or entry.time >= window_start:
                    results.append(entry)
            elif entry.date == next_day_str:
                if entry.time and entry.time < window_start:
                    results.append(entry)
        return results

    def get_eating_day_totals(
        self, profile: UserProfile, date_str: str,
    ) -> tuple[int, int]:
        """סך קלוריות וחלבון ליום-אכילה לוגי."""
        entries = self.get_eating_day_entries(profile, date_str)
        total_cal = 0
        total_prot = 0
        for entry in entries:
            total_cal += entry.calories
            total_prot += entry.protein
        return total_cal, total_prot
