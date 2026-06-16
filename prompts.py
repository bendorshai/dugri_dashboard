"""
prompts.py - Centralized GPT system prompts with shared building blocks.

Content is loaded from .txt files in content/prompts/.
Building blocks are composed via {{include:filename}} directives in the .txt files.

Depends on: content/loader.py
Used by: analyzer.py, help_service.py, feedback_service.py, internal_api.py.
"""

import logging
from pathlib import Path
from content.loader import load_content

_logger = logging.getLogger(__name__)
_ns = load_content(Path(__file__).parent / "content" / "prompts", _logger)
globals().update(vars(_ns))
