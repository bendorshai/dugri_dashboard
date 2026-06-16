"""
classification_guardrails.py - Post-classification context validation.

Validates LLM classification results against conversation context to catch
misclassifications that the LLM cannot detect (e.g., feedback_reaction when
no feedback was given, correction when no correctable entry exists).

Pure logic: no LLM calls, no DB access, no side effects.

Depends on: models/analyzer_models.py (RouterClassification)
Used by: handlers/base.py (_dispatch_v2)
"""

from __future__ import annotations

import logging

from models.analyzer_models import RouterClassification

logger = logging.getLogger(__name__)

# Classification types that indicate a logged entry (used to detect
# correctable context in recent messages).
_ENTRY_CLASSIFICATIONS = {"meal", "sleep", "workout", "self_care"}


def validate_classification(
    classification: RouterClassification,
    recent_messages: list[dict] | None,
    last_entry: dict | None,
    reply_context: str | None,
    name: str | None,
    gender: str | None,
) -> RouterClassification:
    """Apply context-aware guardrails to a classification result.

    Returns the original classification if valid, or an overridden one
    (typically 'conversational') when context doesn't support the classification.
    """
    ctype = classification.type

    if ctype == "feedback_reaction":
        if not _has_recent_feedback(recent_messages):
            logger.info("Guardrail: feedback_reaction -> conversational (no recent feedback)")
            return RouterClassification(type="conversational")

    if ctype == "correction":
        if not _has_correctable_context(recent_messages, last_entry, reply_context):
            logger.info("Guardrail: correction -> conversational (no correctable context)")
            return RouterClassification(type="conversational")

    if ctype == "name_declaration":
        if name:
            logger.info("Guardrail: name_declaration -> conversational (name already set)")
            return RouterClassification(type="conversational")

    if ctype == "gender_declaration":
        if gender:
            logger.info("Guardrail: gender_declaration -> conversational (gender already set)")
            return RouterClassification(type="conversational")

    return classification


def _has_recent_feedback(recent_messages: list[dict] | None) -> bool:
    """Check if bot sent feedback within the last 2 messages."""
    if not recent_messages:
        return False
    # Look at the last 2 messages for a bot message that was feedback
    tail = recent_messages[-2:]
    for msg in tail:
        if msg.get("role") != "bot":
            continue
        # Primary check: classification metadata
        classification = msg.get("classification")
        if classification and "feedback" in classification:
            return True
        # Fallback: 💬 emoji in text (backward compat for messages
        # stored before classification metadata was added)
        if "\U0001f4ac" in msg.get("text", ""):
            return True
    return False


def _has_correctable_context(
    recent_messages: list[dict] | None,
    last_entry: dict | None,
    reply_context: str | None,
) -> bool:
    """Check if there's a correctable entry in context."""
    # Case 1: Telegram reply to any bot/user message -> allow
    # (the user is explicitly pointing at a message to correct)
    if reply_context:
        return True

    # Case 2: In-memory last_entry exists (set after logging)
    if last_entry:
        return True

    # Case 3: Recent bot message was an entry confirmation (within last 2 msgs)
    if recent_messages:
        tail = recent_messages[-2:]
        for msg in tail:
            if msg.get("role") != "bot":
                continue
            # Primary check: classification metadata
            classification = msg.get("classification")
            if classification in _ENTRY_CLASSIFICATIONS:
                return True
            # Fallback: calorie/protein markers for food entries
            # (backward compat for messages without classification metadata)
            text = msg.get("text", "")
            if "\u05e7\u05dc\u05f3" in text and "\u05d7\u05dc\u05d1\u05d5\u05df" in text:
                return True

    return False
