"""
test_correction_context_msg.py - TDD tests for contextual habit correction messages.

Expected behavior:
- Reclassification message tells user what changed: "עידכנתי מ-משהו לעצמי ל-אימון בשבת"
- Same-type corrections describe what changed: "תיקנתי שינה ל-23:00"
- Date-move corrections: "טיפלתי לך בזה - העברתי אימון ליום שבת"
- Prefix rotates randomly between: עידכנתי, תיקנתי, טיפלתי לך בזה
- HABIT_TYPE_LABELS maps internal types to Hebrew display names
"""

import sys
import os
import re
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from models.analyzer_models import HabitCorrectionResult


# ============================================================================
# HABIT_TYPE_LABELS
# ============================================================================


class TestHabitTypeLabels:
    def test_labels_exist(self):
        from messages import HABIT_TYPE_LABELS

        assert "sleep" in HABIT_TYPE_LABELS
        assert "workout" in HABIT_TYPE_LABELS
        assert "self_care" in HABIT_TYPE_LABELS

    def test_labels_are_hebrew(self):
        from messages import HABIT_TYPE_LABELS

        assert HABIT_TYPE_LABELS["sleep"] == "שינה"
        assert HABIT_TYPE_LABELS["workout"] == "אימון"
        assert HABIT_TYPE_LABELS["self_care"] == "משהו לעצמי"


# ============================================================================
# Correction confirmation message builder
# ============================================================================


class TestBuildCorrectionMessage:
    """Test the correction message builder function."""

    def test_reclassify_message_contains_both_types(self):
        from messages import build_habit_correction_msg

        msg = build_habit_correction_msg(
            original_type="self_care",
            result=HabitCorrectionResult(
                reclassify_to="workout",
                corrected_note="אימון הליכה",
            ),
            entry_date="14/06/2026",
        )
        assert "משהו לעצמי" in msg
        assert "אימון" in msg

    def test_reclassify_message_contains_day_name(self):
        from messages import build_habit_correction_msg

        msg = build_habit_correction_msg(
            original_type="self_care",
            result=HabitCorrectionResult(
                reclassify_to="workout",
                corrected_note="אימון הליכה",
            ),
            entry_date="13/06/2026",  # Saturday
        )
        assert "שבת" in msg

    def test_date_move_message_contains_new_day(self):
        from messages import build_habit_correction_msg

        msg = build_habit_correction_msg(
            original_type="workout",
            result=HabitCorrectionResult(
                corrected_date="13/06/2026",
            ),
            entry_date="13/06/2026",
        )
        assert "שבת" in msg

    def test_note_change_message_contains_new_value(self):
        from messages import build_habit_correction_msg

        msg = build_habit_correction_msg(
            original_type="workout",
            result=HabitCorrectionResult(
                corrected_note="אימון יוגה",
            ),
            entry_date="16/06/2026",
        )
        assert "אימון יוגה" in msg

    def test_sleep_time_change_contains_time(self):
        from messages import build_habit_correction_msg

        msg = build_habit_correction_msg(
            original_type="sleep",
            result=HabitCorrectionResult(
                corrected_time="23:30",
            ),
            entry_date="16/06/2026",
        )
        assert "23:30" in msg

    def test_message_starts_with_checkmark(self):
        from messages import build_habit_correction_msg

        msg = build_habit_correction_msg(
            original_type="self_care",
            result=HabitCorrectionResult(
                reclassify_to="workout",
                corrected_note="אימון",
            ),
            entry_date="14/06/2026",
        )
        assert msg.startswith("✅")

    def test_prefix_is_one_of_three(self):
        """The prefix rotates between עידכנתי, תיקנתי, טיפלתי לך בזה."""
        from messages import build_habit_correction_msg

        prefixes_seen = set()
        for _ in range(30):
            msg = build_habit_correction_msg(
                original_type="self_care",
                result=HabitCorrectionResult(
                    reclassify_to="workout",
                    corrected_note="אימון",
                ),
                entry_date="14/06/2026",
            )
            # Extract prefix between ✅ and the dash/content
            text = msg.lstrip("✅ ")
            for prefix in ["עידכנתי", "תיקנתי", "טיפלתי לך בזה"]:
                if text.startswith(prefix):
                    prefixes_seen.add(prefix)
        # With 30 tries, should see at least 2 of the 3 prefixes
        assert len(prefixes_seen) >= 2


# ============================================================================
# Integration with pending_handler
# ============================================================================


class TestPendingHandlerUsesContextMessage:
    """Verify pending_handler calls build_habit_correction_msg."""

    def _make_ctx(self):
        ctx = MagicMock()
        ctx._send = AsyncMock()
        ctx.analyzer = MagicMock()
        ctx.sleep_repo = MagicMock()
        ctx.workout_repo = MagicMock()
        ctx.self_care_repo = MagicMock()
        return ctx

    def _make_pending(self, habit_type, entry_id, date, **extra):
        import time as _time
        entry = {"entry_id": entry_id, "date": date, **extra}
        return {
            "pending_habit_correction": {
                "habit_type": habit_type,
                "entry": entry,
                "timestamp": _time.time(),
            }
        }

    async def _run_with_mock_result(self, ctx, habit_type, entry_id, date, mock_result, **extra):
        """Run handle_pending_habit_correction with a mocked LoggerService result."""
        from handlers.pending_handler import PendingHandler
        import services.logger_service

        handler = PendingHandler(ctx)
        message = MagicMock()
        message.text = "תיקון"
        context = MagicMock()
        context.chat_data = self._make_pending(habit_type, entry_id, date, **extra)
        profile = MagicMock()
        profile.timezone = "Asia/Jerusalem"

        mock_svc = MagicMock()
        mock_svc.extract_habit_correction.return_value = mock_result
        original_cls = services.logger_service.LoggerService
        services.logger_service.LoggerService = lambda *a, **kw: mock_svc
        try:
            await handler.handle_pending_habit_correction(message, context, tid=123, profile=profile)
        finally:
            services.logger_service.LoggerService = original_cls

    @pytest.mark.asyncio
    async def test_reclassify_sends_context_message(self):
        """Reclassification should send a contextual message, not just 'עודכן'."""
        ctx = self._make_ctx()
        mock_result = HabitCorrectionResult(
            reclassify_to="workout",
            corrected_note="אימון הליכה",
        )
        await self._run_with_mock_result(
            ctx, "self_care", "aabbccddee112233aabbccdd", "13/06/2026",
            mock_result, description="הליכה ברגל",
        )

        sent_text = ctx._send.call_args_list[0][0][0]
        assert "משהו לעצמי" in sent_text
        assert "אימון" in sent_text

    @pytest.mark.asyncio
    async def test_date_correction_sends_context_message(self):
        """Date move should send a contextual message."""
        ctx = self._make_ctx()
        mock_result = HabitCorrectionResult(corrected_date="14/06/2026")
        await self._run_with_mock_result(
            ctx, "workout", "aabbccddee112233aabbccdd", "16/06/2026",
            mock_result, note="אימון",
        )

        sent_text = ctx._send.call_args_list[0][0][0]
        assert "ראשון" in sent_text  # 14/06/2026 is Sunday
