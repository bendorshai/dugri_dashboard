# Every .py file in the project must compile without syntax errors.
# Catches indentation mistakes, stray characters, and other parse-time failures
# that would prevent the bot from starting.

import py_compile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Collect all .py files, excluding worktrees and venvs
SOURCE_FILES = sorted(
    p for p in PROJECT_ROOT.rglob("*.py")
    if not any(part == ".claude" for part in p.relative_to(PROJECT_ROOT).parts)
    and "venv" not in p.parts
    and "__pycache__" not in p.parts
)


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_file_compiles(path):
    py_compile.compile(str(path), doraise=True)
