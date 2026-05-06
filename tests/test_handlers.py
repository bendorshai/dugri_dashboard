from __future__ import annotations

import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Stub heavy imports
for mod in [
    "telegram", "telegram.ext", "telegram.ext._application",
    "pymongo", "openai", "gspread",
    "google", "google.oauth2", "google.oauth2.service_account",
]:
    sys.modules.setdefault(mod, MagicMock())

# Need to set up telegram module attributes
mock_telegram = sys.modules["telegram"]
mock_telegram.Update = MagicMock
mock_telegram.InlineKeyboardButton = MagicMock
mock_telegram.InlineKeyboardMarkup = MagicMock

mock_ext = sys.modules["telegram.ext"]
mock_ext.ContextTypes = MagicMock()
mock_ext.ContextTypes.DEFAULT_TYPE = MagicMock

from analyzer import FoodItem, FoodAnalysisResult
from keyboards import format_daily_status


class TestFormatDailyStatus:
    def test_under_calorie_target(self):
        result = format_daily_status(1500, 120, 2000, 150)
        assert "✅" in result
        assert "1500/2000" in result
        assert "500" in result  # remaining

    def test_over_calorie_target(self):
        result = format_daily_status(2200, 120, 2000, 150)
        assert "⚠️" in result
        assert "2200/2000" in result

    def test_protein_above_target(self):
        result = format_daily_status(1500, 160, 2000, 150)
        assert "✅" in result
        assert "160" in result

    def test_protein_below_target(self):
        result = format_daily_status(1500, 100, 2000, 150)
        # Should have warning for protein
        lines = result.split("\n")
        protein_line = [l for l in lines if "חלבון" in l][0]
        assert "⚠️" in protein_line


class TestCrossingAlerts:
    """Test crossing alert logic from HealthHandlers."""

    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        h.chat_id = 123
        h.mongo = MagicMock()
        h.mongo.get_user_profile.return_value = {
            "target_calories": 2000,
            "target_protein": 150,
        }
        return h

    def test_no_alert_when_both_within_range(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1000, 80, 1500, 100, profile)
        assert result == ""

    def test_protein_target_reached(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1000, 130, 1400, 155, profile)
        assert "כל הכבוד" in result
        assert "חלבון" in result

    def test_calorie_target_exceeded(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1800, 100, 2100, 120, profile)
        assert "עברת" in result
        assert "קלוריות" in result

    def test_both_alerts(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        result = h._check_crossing_alerts(1800, 140, 2100, 160, profile)
        assert "כל הכבוד" in result
        assert "עברת" in result


class TestDailyTotalsCalculation:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        return h

    def test_empty_entries(self):
        h = self._make_handler()
        cal, prot = h._calculate_daily_totals([])
        assert cal == 0
        assert prot == 0

    def test_multiple_entries(self):
        h = self._make_handler()
        entries = [
            {"calories": 400, "protein": 30},
            {"calories": 300, "protein": 25},
            {"calories": 200, "protein": 10},
        ]
        cal, prot = h._calculate_daily_totals(entries)
        assert cal == 900
        assert prot == 65


class TestBuildFoodResponse:
    def _make_handler(self):
        from handlers.base import HealthHandlers
        h = HealthHandlers.__new__(HealthHandlers)
        return h

    def test_includes_items_and_status(self):
        h = self._make_handler()
        profile = {"target_calories": 2000, "target_protein": 150}
        response = h._build_food_response("• שניצל: 400 קל׳", 400, 30, profile)
        assert "שניצל" in response
        assert "400/2000" in response
        assert "30g/150g" in response


class TestOneRowPerMessage:
    """Verify that multiple food items get consolidated into one description."""

    def test_items_joined_with_comma(self):
        items = [
            MagicMock(description="שניצל", calories=400, protein=30),
            MagicMock(description="סלט", calories=50, protein=3),
        ]
        combined = ", ".join(item.description for item in items)
        assert combined == "שניצל, סלט"

    def test_totals_summed(self):
        items = [
            MagicMock(description="שניצל", calories=400, protein=30),
            MagicMock(description="סלט", calories=50, protein=3),
        ]
        total_cal = sum(item.calories for item in items)
        total_prot = sum(item.protein for item in items)
        assert total_cal == 450
        assert total_prot == 33
