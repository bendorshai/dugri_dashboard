from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from analyzer import DashboardAnalyzer


@pytest.fixture()
def analyzer():
    with patch("analyzer.OpenAI") as mock_openai:
        a = DashboardAnalyzer(api_key="test-key")
        yield a, mock_openai


class TestSuggestTargets:
    def test_returns_targets_on_success(self, analyzer):
        a, _ = analyzer
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(
                content=json.dumps({"target_calories": 2200, "target_protein": 165})
            ))
        ]
        a.client.chat.completions.create.return_value = mock_response

        result = a.suggest_targets(height_cm=180, weight_kg=85, age=30)
        assert result == {"target_calories": 2200, "target_protein": 165}

    def test_returns_none_on_api_failure(self, analyzer):
        a, _ = analyzer
        a.client.chat.completions.create.side_effect = Exception("API down")
        result = a.suggest_targets(height_cm=180, weight_kg=85, age=30)
        assert result is None

    def test_calls_openai_with_correct_model(self, analyzer):
        a, _ = analyzer
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(
                content=json.dumps({"target_calories": 2000, "target_protein": 150})
            ))
        ]
        a.client.chat.completions.create.return_value = mock_response

        a.suggest_targets(height_cm=175, weight_kg=80, age=25)
        call_kwargs = a.client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
