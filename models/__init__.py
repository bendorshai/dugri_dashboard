"""
models — מודלי הדומיין של דוגרי.

כל ישות דומיין היא מחלקת Pydantic שמספקת ולידציה אוטומטית וטייפינג חזק.
ה-repositories מקבלות ומחזירות מודלים מכאן — לא מילונים חשופים.
"""

from models.profile import UserProfile, Targets, EatingWindow, PendingState
from models.food import FoodEntry

__all__ = [
    "UserProfile",
    "Targets",
    "EatingWindow",
    "PendingState",
    "FoodEntry",
]
