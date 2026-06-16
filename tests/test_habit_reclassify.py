"""
test_habit_reclassify — TDD tests for cross-habit reclassification.

Expected behavior:
- HabitCorrectionResult can include reclassify_to field
- When reclassify_to is set, original entry is deleted and new entry created in target repo
- Reclassification preserves date from original entry
- New entry has the corrected_note as its description/note
- Example: self_care "הלכתי לים" -> workout "אימון גלישה"
- Example: workout -> self_care
- Example: self_care -> sleep
"""

import sys
from unittest.mock import MagicMock, AsyncMock, call

import pytest

for mod in ["telegram", "telegram.ext", "pymongo", "openai"]:
    sys.modules.setdefault(mod, MagicMock())

from bson import ObjectId
from models.analyzer_models import HabitCorrectionResult


class TestHabitCorrectionResultReclassify:
    def test_reclassify_to_default_none(self):
        result = HabitCorrectionResult()
        assert result.reclassify_to is None

    def test_reclassify_to_workout(self):
        result = HabitCorrectionResult(
            reclassify_to="workout",
            corrected_note="אימון גלישה",
        )
        assert result.reclassify_to == "workout"
        assert result.corrected_note == "אימון גלישה"


def _make_ctx():
    ctx = MagicMock()
    ctx._send = AsyncMock()
    ctx.analyzer = MagicMock()
    ctx.sleep_repo = MagicMock()
    ctx.workout_repo = MagicMock()
    ctx.self_care_repo = MagicMock()
    return ctx


def _make_pending(habit_type, entry_id, date, **extra):
    import time
    entry = {"entry_id": entry_id, "date": date, **extra}
    return {
        "pending_habit_correction": {
            "habit_type": habit_type,
            "entry": entry,
            "timestamp": time.time(),
        }
    }


async def _run_reclassify(ctx, habit_type, entry_id, date, reclassify_result, **extra):
    from handlers.pending_handler import PendingHandler

    handler = PendingHandler(ctx)
    message = MagicMock()
    message.text = "תיקון"
    context = MagicMock()
    context.chat_data = _make_pending(habit_type, entry_id, date, **extra)
    profile = MagicMock()
    profile.timezone = "Asia/Jerusalem"

    with MagicMock() as mock_logger_svc:
        mock_logger_svc.extract_habit_correction.return_value = reclassify_result
        import services.logger_service
        original_cls = services.logger_service.LoggerService
        services.logger_service.LoggerService = lambda *a, **kw: mock_logger_svc
        try:
            result = await handler.handle_pending_habit_correction(
                message, context, 123, profile,
            )
        finally:
            services.logger_service.LoggerService = original_cls
    return result


VALID_OID = "aabbccddee112233aabbccdd"


class TestSelfCareToWorkout:
    @pytest.mark.asyncio
    async def test_deletes_original_self_care(self):
        ctx = _make_ctx()
        result = await _run_reclassify(
            ctx, "self_care", VALID_OID, "16/06/2026",
            HabitCorrectionResult(reclassify_to="workout", corrected_note="אימון גלישה"),
            description="הלכתי לים",
        )
        assert result is True
        ctx.self_care_repo.delete_by_id.assert_called_once_with(ObjectId(VALID_OID))

    @pytest.mark.asyncio
    async def test_creates_workout_in_target_repo(self):
        ctx = _make_ctx()
        await _run_reclassify(
            ctx, "self_care", VALID_OID, "16/06/2026",
            HabitCorrectionResult(reclassify_to="workout", corrected_note="אימון גלישה"),
            description="הלכתי לים",
        )
        ctx.workout_repo.insert.assert_called_once()
        new_log = ctx.workout_repo.insert.call_args[0][0]
        assert new_log.date == "16/06/2026"
        assert new_log.note == "אימון גלישה"
        assert new_log.telegram_user_id == 123

    @pytest.mark.asyncio
    async def test_preserves_original_date(self):
        ctx = _make_ctx()
        await _run_reclassify(
            ctx, "self_care", VALID_OID, "14/06/2026",
            HabitCorrectionResult(reclassify_to="workout", corrected_note="אימון"),
            description="הלכתי לים",
        )
        new_log = ctx.workout_repo.insert.call_args[0][0]
        assert new_log.date == "14/06/2026"

    @pytest.mark.asyncio
    async def test_uses_corrected_date_when_provided(self):
        ctx = _make_ctx()
        await _run_reclassify(
            ctx, "self_care", VALID_OID, "16/06/2026",
            HabitCorrectionResult(
                reclassify_to="workout",
                corrected_note="אימון",
                corrected_date="15/06/2026",
            ),
            description="הלכתי לים",
        )
        new_log = ctx.workout_repo.insert.call_args[0][0]
        assert new_log.date == "15/06/2026"


class TestWorkoutToSelfCare:
    @pytest.mark.asyncio
    async def test_deletes_workout_creates_self_care(self):
        ctx = _make_ctx()
        await _run_reclassify(
            ctx, "workout", VALID_OID, "16/06/2026",
            HabitCorrectionResult(reclassify_to="self_care", corrected_note="הליכה לים"),
            note="אימון",
        )
        ctx.workout_repo.delete_by_id.assert_called_once_with(ObjectId(VALID_OID))
        ctx.self_care_repo.insert.assert_called_once()
        new_log = ctx.self_care_repo.insert.call_args[0][0]
        assert new_log.description == "הליכה לים"
        assert new_log.date == "16/06/2026"


class TestSelfCareToSleep:
    @pytest.mark.asyncio
    async def test_deletes_self_care_creates_sleep(self):
        ctx = _make_ctx()
        await _run_reclassify(
            ctx, "self_care", VALID_OID, "16/06/2026",
            HabitCorrectionResult(reclassify_to="sleep", corrected_time="23:30"),
            description="הלכתי לישון מוקדם",
        )
        ctx.self_care_repo.delete_by_id.assert_called_once_with(ObjectId(VALID_OID))
        ctx.sleep_repo.insert.assert_called_once()
        new_log = ctx.sleep_repo.insert.call_args[0][0]
        assert new_log.sleep_time == "23:30"
        assert new_log.date == "16/06/2026"


class TestNoReclassifyToSameType:
    @pytest.mark.asyncio
    async def test_same_type_does_not_reclassify(self):
        """reclassify_to=same habit_type should be treated as a normal correction."""
        ctx = _make_ctx()
        await _run_reclassify(
            ctx, "workout", VALID_OID, "16/06/2026",
            HabitCorrectionResult(reclassify_to="workout", corrected_note="אימון יוגה"),
            note="אימון",
        )
        # Should NOT delete and recreate - just update in place
        ctx.workout_repo.delete_by_id.assert_not_called()
        ctx.workout_repo.update_by_id.assert_called_once()
