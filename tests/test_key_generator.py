from __future__ import annotations

from key_generator import generate_bot_key


class TestGenerateBotKey:
    def test_returns_hex_string(self):
        key = generate_bot_key("test@example.com", "salt123")
        assert isinstance(key, str)
        assert len(key) == 32
        int(key, 16)  # validates it's hex

    def test_deterministic(self):
        key1 = generate_bot_key("a@b.com", "salt")
        key2 = generate_bot_key("a@b.com", "salt")
        assert key1 == key2

    def test_different_emails_different_keys(self):
        key1 = generate_bot_key("a@b.com", "salt")
        key2 = generate_bot_key("c@d.com", "salt")
        assert key1 != key2

    def test_different_salts_different_keys(self):
        key1 = generate_bot_key("a@b.com", "salt1")
        key2 = generate_bot_key("a@b.com", "salt2")
        assert key1 != key2
