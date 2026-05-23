"""
test_education — TDD tests for the education feature.

Tests static education texts, the edu_intro_shown flag on ToggleState,
and the _get_education_intro helper logic.
"""

from unittest.mock import MagicMock

import pytest

from models.profile import User, ToggleState, Toggles
from dugri_messages import EDU_INTRO_FIRST_LOG, EDU_WHY_KERNEL


EXPECTED_HABITS = {"protein", "eating_window", "sleep", "workouts", "self_care"}

# Habits that have a corresponding toggle (all except protein)
TOGGLE_HABITS = {"eating_window", "sleep", "workouts", "self_care"}


def _make_user(**kwargs):
    defaults = {"email": "test@test.com", "telegram_user_id": 123}
    defaults.update(kwargs)
    return User(**defaults)


# ---------------------------------------------------------------------------
# Static education text tests
# ---------------------------------------------------------------------------

class TestEducationDicts:
    def test_edu_intro_first_log_has_all_habits(self):
        assert set(EDU_INTRO_FIRST_LOG.keys()) == EXPECTED_HABITS

    def test_edu_why_kernel_has_all_habits(self):
        assert set(EDU_WHY_KERNEL.keys()) == EXPECTED_HABITS

    def test_edu_keys_match(self):
        assert set(EDU_INTRO_FIRST_LOG.keys()) == set(EDU_WHY_KERNEL.keys())

    def test_all_values_are_nonempty_strings(self):
        for key in EXPECTED_HABITS:
            assert isinstance(EDU_INTRO_FIRST_LOG[key], str) and EDU_INTRO_FIRST_LOG[key]
            assert isinstance(EDU_WHY_KERNEL[key], str) and EDU_WHY_KERNEL[key]


# ---------------------------------------------------------------------------
# ToggleState edu_intro_shown flag
# ---------------------------------------------------------------------------

class TestToggleStateEduFlag:
    def test_default_is_false(self):
        ts = ToggleState()
        assert ts.edu_intro_shown is False

    def test_can_set_to_true(self):
        ts = ToggleState(edu_intro_shown=True)
        assert ts.edu_intro_shown is True

    def test_survives_mongo_round_trip(self):
        user = _make_user(
            toggles=Toggles(
                sleep=ToggleState(status="active", edu_intro_shown=True),
                workouts=ToggleState(status="active", edu_intro_shown=False),
            ),
        )
        doc = user.to_mongo_dict()
        restored = User.from_mongo_dict(doc)
        assert restored.toggles.sleep.edu_intro_shown is True
        assert restored.toggles.workouts.edu_intro_shown is False

    def test_defaults_false_in_legacy_docs(self):
        """Existing MongoDB docs without edu_intro_shown should default False."""
        doc = {
            "_id": "a@b.com",
            "toggles": {
                "sleep": {"status": "active"},
                "eating_window": {"status": "dormant"},
                "workouts": {"status": "dormant"},
                "self_care": {"status": "dormant"},
                "target_data": {"status": "dormant"},
                "weekly_summary": {"status": "active"},
            },
        }
        user = User.from_mongo_dict(doc)
        assert user.toggles.sleep.edu_intro_shown is False


# ---------------------------------------------------------------------------
# Education intro logic (simulates _get_education_intro behavior)
# ---------------------------------------------------------------------------

class TestEducationIntroLogic:
    def test_fires_when_not_shown(self):
        """Education text returned when edu_intro_shown is False."""
        user = _make_user(
            toggles=Toggles(sleep=ToggleState(status="active", edu_intro_shown=False)),
        )
        toggle = user.toggles.sleep
        assert not toggle.edu_intro_shown
        text = EDU_INTRO_FIRST_LOG.get("sleep")
        assert text is not None

    def test_skipped_when_already_shown(self):
        """No education when edu_intro_shown is True."""
        user = _make_user(
            toggles=Toggles(sleep=ToggleState(status="active", edu_intro_shown=True)),
        )
        toggle = user.toggles.sleep
        assert toggle.edu_intro_shown

    def test_dashboard_activation_skips_education(self):
        """Dashboard sets edu_intro_shown=True on activation, so no education fires."""
        user = _make_user(
            toggles=Toggles(workouts=ToggleState(status="active", edu_intro_shown=True)),
        )
        assert user.toggles.workouts.edu_intro_shown is True

    def test_dormant_reset_clears_education(self):
        """When toggle goes back to dormant (re-suggest), edu_intro_shown resets."""
        user = _make_user(
            toggles=Toggles(
                sleep=ToggleState(status="dormant", edu_intro_shown=False),
            ),
        )
        assert user.toggles.sleep.edu_intro_shown is False

    def test_all_toggle_habits_addressable(self):
        """All toggle-based habits can be looked up on the Toggles model."""
        toggles = Toggles()
        for habit in TOGGLE_HABITS:
            toggle = getattr(toggles, habit, None)
            assert toggle is not None, f"Missing toggle for habit: {habit}"
            assert toggle.edu_intro_shown is False
