from __future__ import annotations

import hashlib


def generate_bot_key(email: str, salt: str) -> str:
    return hashlib.md5((email + salt).encode("utf-8")).hexdigest()
