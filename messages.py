"""
messages.py - All Hebrew text that Dugri says.

Content is loaded from .txt files in content/messages/.
Edit the text files directly to change Dugri's voice without touching code.

Depends on: content/loader.py
Used by: handlers, services, scheduler.
"""

import logging
from pathlib import Path
from content.loader import load_content

_logger = logging.getLogger(__name__)
_ns = load_content(Path(__file__).parent / "content" / "messages", _logger)
globals().update(vars(_ns))
