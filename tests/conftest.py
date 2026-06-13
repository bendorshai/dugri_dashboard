# conftest.py - Shared test fixtures and early imports.
#
# Import the real telegram module early, before any test file can
# mock it via sys.modules.setdefault("telegram", MagicMock()).
# This ensures tests that need real telegram classes (e.g. test_super_debug)
# get the actual module, while tests using setdefault will also get it
# (since setdefault is a no-op if the key already exists).

import telegram  # noqa: F401
import telegram.ext  # noqa: F401
