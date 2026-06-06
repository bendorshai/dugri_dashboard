"""
test_photo_quality.py - TDD for photo quality warnings.

These tests call GPT-4o with real food photos to verify that photo_tips
correctly warns about quality issues instead of giving false "all good"
feedback.

Run with: pytest tests/test_photo_quality.py -v -m integration
Skip in CI: pytest -m "not integration"

Photo fixtures live in tests/fixtures/photos/. When a photo doesn't exist
yet (only a .missing marker), the test is skipped automatically.
The user will supply photos over time; tests will start passing as photos
arrive.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from analyzer import FoodAnalyzer

# ---------------------------------------------------------------------------
# Config / API key
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
try:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        _CONFIG = json.load(f)
    _API_KEY = _CONFIG.get("openai", {}).get("api_key", "")
except FileNotFoundError:
    _API_KEY = os.environ.get("OPENAI_API_KEY", "")

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "photos"

# Positive phrases that should NOT appear in warnings
POSITIVE_PHRASES = ["מצוין", "👍", "מעולה", "נהדר", "המשך לצלם ככה", "צילום טוב"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_photo_b64(name: str) -> str:
    """Load a fixture photo as base64. Fail test if photo not available."""
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.fail(f"Photo fixture missing: tests/fixtures/photos/{name} - supply this photo!")
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _make_analyzer() -> FoodAnalyzer:
    if not _API_KEY:
        pytest.skip("No OpenAI API key available")
    return FoodAnalyzer(api_key=_API_KEY)


def _assert_no_positive_feedback(photo_tips: list[str]):
    """Assert that none of the tips contain positive/compliment phrases."""
    combined = " ".join(photo_tips)
    for phrase in POSITIVE_PHRASES:
        assert phrase not in combined, (
            f"Expected a warning but got positive feedback containing '{phrase}': {combined}"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPiledFood:
    """Food piled/stacked on plate - portions hard to estimate."""

    def test_warns_about_piling(self):
        b64 = _load_photo_b64("piled_food.jpg")
        analyzer = _make_analyzer()

        result = analyzer.analyze_food_photo(b64, "05/06/2026")

        assert result is not None, "Analyzer returned None for piled food photo"
        assert result.photo_tips, "Expected photo_tips but got empty list"
        _assert_no_positive_feedback(result.photo_tips)

        # Should mention piling/stacking/overlapping in at least one tip
        combined = " ".join(result.photo_tips)
        piling_keywords = ["מוערמ", "ערימ", "חופפ", "נערם", "לפזר", "פזר", "מכס", "כיסוי"]
        assert any(kw in combined for kw in piling_keywords), (
            f"Expected warning about piled food, got: {combined}"
        )


class TestPartialPlate:
    """Only part of the plate visible in frame."""

    def test_warns_about_partial_plate(self):
        b64 = _load_photo_b64("partial_plate.jpg")
        analyzer = _make_analyzer()

        result = analyzer.analyze_food_photo(b64, "05/06/2026")

        assert result is not None
        assert result.photo_tips
        _assert_no_positive_feedback(result.photo_tips)


class TestOutOfFocus:
    """Blurry/out of focus photo."""

    def test_warns_about_focus(self):
        b64 = _load_photo_b64("out_of_focus.jpg")
        analyzer = _make_analyzer()

        result = analyzer.analyze_food_photo(b64, "05/06/2026")

        assert result is not None
        assert result.photo_tips
        _assert_no_positive_feedback(result.photo_tips)


class TestBadAngle:
    """Photo taken from too steep or flat an angle."""

    def test_warns_about_angle(self):
        b64 = _load_photo_b64("bad_angle.jpg")
        analyzer = _make_analyzer()

        result = analyzer.analyze_food_photo(b64, "05/06/2026")

        assert result is not None
        assert result.photo_tips
        _assert_no_positive_feedback(result.photo_tips)


class TestBadLighting:
    """Photo taken in poor lighting conditions."""

    def test_warns_about_lighting(self):
        b64 = _load_photo_b64("bad_lighting.jpg")
        analyzer = _make_analyzer()

        result = analyzer.analyze_food_photo(b64, "05/06/2026")

        assert result is not None
        assert result.photo_tips
        _assert_no_positive_feedback(result.photo_tips)


class TestUnidentifiedItem:
    """Photo quality is fine, but contains an item the LLM can't confidently identify."""

    def test_flags_unidentified_item(self):
        b64 = _load_photo_b64("unidentified_item.jpg")
        analyzer = _make_analyzer()

        result = analyzer.analyze_food_photo(b64, "06/06/2026")

        assert result is not None
        assert result.unidentified_items, (
            "Expected unidentified_items to flag the ambiguous cup, got empty list"
        )
        # Should describe what it sees but can't identify
        combined = " ".join(result.unidentified_items)
        assert len(combined) > 5, f"Description too vague: {combined}"
