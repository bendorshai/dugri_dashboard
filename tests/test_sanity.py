# test_sanity.py - Startup sanity checks.
#
# Three layers of defense against "bot won't start" bugs:
# 1. Syntax:  every .py file compiles (catches indentation, stray chars)
# 2. Imports: every production module imports (catches broken references)
# 3. Wiring:  create_bot() constructs the full handler tree with mocked deps
#             (catches signature mismatches like missing kwargs)

import importlib
import py_compile
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Collect source files
# ---------------------------------------------------------------------------

SOURCE_FILES = sorted(
    p for p in PROJECT_ROOT.rglob("*.py")
    if not any(part == ".claude" for part in p.relative_to(PROJECT_ROOT).parts)
    and "venv" not in p.parts
    and "__pycache__" not in p.parts
)

# Convert file paths to importable module names (relative to PROJECT_ROOT).
# e.g. services/toggle_service.py -> services.toggle_service
# Skip scripts/ and tests/ - only production modules.
_SKIP_DIRS = {"tests", "scripts"}

IMPORTABLE_MODULES = []
for p in SOURCE_FILES:
    rel = p.relative_to(PROJECT_ROOT)
    if rel.parts[0] in _SKIP_DIRS:
        continue
    # Turn path into dotted module name
    parts = list(rel.with_suffix("").parts)
    # Skip __init__ - parent package import covers it
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        continue
    IMPORTABLE_MODULES.append(".".join(parts))


# ---------------------------------------------------------------------------
# 1. Syntax: every file compiles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_file_compiles(path):
    py_compile.compile(str(path), doraise=True)


# ---------------------------------------------------------------------------
# 2. Imports: every production module imports without error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module", IMPORTABLE_MODULES)
def test_module_imports(module):
    """Import each production module. Catches broken imports, missing
    dependencies, and top-level code that blows up at import time."""
    importlib.import_module(module)


# ---------------------------------------------------------------------------
# 3. Wiring: create_bot() builds without TypeError
# ---------------------------------------------------------------------------

def test_create_bot_wiring():
    """Call create_bot() with mocked dependencies to verify the full
    constructor chain (create_bot -> HealthHandlers -> HandlerContext)
    has no signature mismatches.

    This does NOT start the bot or connect to Telegram - it only builds
    the Application object, which is safe to do locally without competing
    with the production instance."""
    from bot import create_bot

    with patch("bot.Application") as MockApp:
        # Application.builder().token(...).build() returns a mock app
        mock_app = MagicMock()
        MockApp.builder.return_value.token.return_value.build.return_value = mock_app

        app = create_bot(
            token="fake-token",
            analyzer=MagicMock(),
            user_repo=MagicMock(),
            food_repo=MagicMock(),
            feedback_repo=MagicMock(),
            error_repo=MagicMock(),
            eating_day_service=MagicMock(),
            sleep_repo=MagicMock(),
            workout_repo=MagicMock(),
            self_care_repo=MagicMock(),
            hook_schedule_store=MagicMock(),
            feature_request_repo=MagicMock(),
            admin_chat_id=0,
            token_log_repo=MagicMock(),
            emotional_support_config={"mode": "creator"},
            inappropriate_log_repo=MagicMock(),
        )

        assert app is mock_app
