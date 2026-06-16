"""
test_simulate.py - Unit tests for the admin simulator.

Tests SimulatorBot capture behavior and build_fake_update structure.
No real Telegram, MongoDB, or GPT calls.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock


# Ensure the health_tracker source is on path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


from simulate import SimulatorBot, build_fake_update


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.id = 12345
    bot.username = "test_bot"
    bot.first_name = "TestBot"
    return bot


@pytest.fixture
def sim_bot(mock_bot):
    return SimulatorBot(mock_bot)


class TestSimulatorBot:
    """SimulatorBot captures outgoing messages instead of sending to Telegram."""

    def test_captures_send_message(self, sim_bot):
        result = asyncio.run(
            sim_bot.send_message(chat_id=999, text="hello")
        )
        assert len(sim_bot.captured) == 1
        assert sim_bot.captured[0]["text"] == "hello"
        assert sim_bot.captured[0]["type"] == "message"
        # Returns a fake Message with expected fields
        assert result.message_id > 0
        assert result.text == "hello"

    def test_captures_multiple_messages(self, sim_bot):
        async def _run():
            await sim_bot.send_message(chat_id=1, text="first")
            await sim_bot.send_message(chat_id=1, text="second")
        asyncio.run(_run())
        assert len(sim_bot.captured) == 2
        assert sim_bot.captured[0]["text"] == "first"
        assert sim_bot.captured[1]["text"] == "second"

    def test_send_chat_action_is_noop(self, sim_bot):
        asyncio.run(
            sim_bot.send_chat_action(chat_id=1, action="typing")
        )
        assert len(sim_bot.captured) == 0

    def test_answer_callback_query_is_noop(self, sim_bot):
        asyncio.run(
            sim_bot.answer_callback_query(callback_query_id="123")
        )
        assert len(sim_bot.captured) == 0

    def test_captures_edit_message_text(self, sim_bot):
        asyncio.run(
            sim_bot.edit_message_text(text="edited", chat_id=1, message_id=5)
        )
        assert len(sim_bot.captured) == 1
        assert sim_bot.captured[0]["type"] == "edit"
        assert sim_bot.captured[0]["text"] == "edited"

    def test_serializes_reply_markup(self, sim_bot):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Click me", callback_data="test:1")]
        ])
        asyncio.run(
            sim_bot.send_message(chat_id=1, text="with buttons", reply_markup=markup)
        )
        captured = sim_bot.captured[0]
        rm = captured["reply_markup"]
        assert "inline_keyboard" in rm
        assert rm["inline_keyboard"][0][0]["text"] == "Click me"
        assert rm["inline_keyboard"][0][0]["callback_data"] == "test:1"

    def test_delegates_unknown_attrs_to_real_bot(self, sim_bot, mock_bot):
        mock_bot.some_attr = "value"
        assert sim_bot.some_attr == "value"


class TestBuildFakeUpdate:
    """build_fake_update creates proper Telegram Update dicts."""

    def test_text_message_structure(self, mock_bot):
        update = build_fake_update(999999, text="hello", bot=mock_bot)
        assert "update_id" in update
        assert "message" in update
        assert update["message"]["from"]["id"] == 999999
        assert update["message"]["text"] == "hello"
        assert update["message"]["chat"]["type"] == "private"

    def test_callback_query_structure(self, mock_bot):
        update = build_fake_update(999999, callback_data="menu:home", bot=mock_bot)
        assert "callback_query" in update
        assert "message" not in update
        assert update["callback_query"]["data"] == "menu:home"
        assert update["callback_query"]["from"]["id"] == 999999

    def test_text_and_callback_exclusive(self, mock_bot):
        # When callback_data is set, text is ignored
        update = build_fake_update(999999, text="ignored", callback_data="cb:1", bot=mock_bot)
        assert "callback_query" in update
