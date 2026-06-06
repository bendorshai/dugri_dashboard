"""
dugri_messages.py - Education messages (backward-compat wrapper).

Content now lives in content/messages/ alongside all other messages.
This module re-exports EDU_* names so existing imports continue to work.
"""

from messages import EDU_INTRO_FIRST_LOG, EDU_WHY_KERNEL

__all__ = ["EDU_INTRO_FIRST_LOG", "EDU_WHY_KERNEL"]
