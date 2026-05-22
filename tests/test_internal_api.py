"""
test_internal_api — TDD tests for the internal webhook module.
"""

import pytest

from internal_api import validate_secret, build_target_change_prompt


class TestValidateSecret:
    def test_valid_secret(self):
        assert validate_secret("my-secret", "my-secret") is True

    def test_invalid_secret(self):
        assert validate_secret("wrong", "my-secret") is False

    def test_empty_strings(self):
        assert validate_secret("", "") is True


class TestBuildTargetChangePrompt:
    def test_includes_old_and_new_values(self):
        prompt = build_target_change_prompt(2000, 1800, 150, 130)
        assert "2000" in prompt
        assert "1800" in prompt
        assert "150" in prompt
        assert "130" in prompt

    def test_handles_none_values(self):
        prompt = build_target_change_prompt(None, 1800, None, 130)
        assert "לא הוגדר" in prompt
        assert "1800" in prompt

    def test_returns_hebrew_prompt(self):
        prompt = build_target_change_prompt(2000, 1800, 150, 130)
        assert "דוגרי" in prompt
