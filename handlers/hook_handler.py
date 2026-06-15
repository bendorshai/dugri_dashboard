"""
hook_handler.py - Piggyback hooks fired after meals.
"""

from __future__ import annotations

import asyncio
import logging
import random

from models.profile import UserProfile
from handlers.context import HandlerContext

logger = logging.getLogger(__name__)


class HookHandler:
    def __init__(self, ctx: HandlerContext):
        self.ctx = ctx

    async def check_inline_hooks(self, message, tid: int, profile: UserProfile):
        """After a meal is logged, check if any hooks should fire inline.

        Waits INLINE_HOOK_DELAY_SECONDS before sending, so the bot feels
        like it's pausing before bringing up a new topic.
        """
        if not self.ctx.toggle_service:
            return

        from scheduler import should_fire_inline
        from user_clock import UserClock
        import messages as M
        from constants import (
            WORKOUTS_ANCHOR_DAY, SELF_CARE_ANCHOR_DAY, WEEKLY_SUMMARY_ANCHOR_DAY,
            INLINE_HOOK_DELAY_SECONDS,
            SLEEP_HOOK_WINDOW, WORKOUTS_HOOK_WINDOW, SELF_CARE_HOOK_WINDOW,
            WEEKLY_SUMMARY_HOOK_WINDOW,
        )

        await asyncio.sleep(INLINE_HOOK_DELAY_SECONDS)

        clock = UserClock(profile.timezone)
        day_number = self.ctx.toggle_service.get_day_number(profile)
        weekday = clock.weekday()

        # Goal reminders (due reminders fire first)
        if self.ctx.goal_service:
            due = self.ctx.goal_service.check_goal_reminders(profile)
            if due:
                text = self.ctx.goal_service.fire_goal_reminder(tid, due[0])
                await self.ctx._send(text, tid=tid, message=message)
                return

        # Nutrition reveal (after first meal, gate_days=0)
        if self.ctx.toggle_service.should_reveal_nutrition(profile):
            self.ctx.toggle_service.reveal_toggle(tid, "nutrition")
            await self.ctx._send(M.REVEAL_NUTRITION, tid=tid, message=message)
            return

        # Day 16 dashboard intro
        if self.ctx.toggle_service.should_show_dashboard_intro(profile, day_number):
            self.ctx.user_repo.update_fields(tid, {"dashboard_intro_shown": True})
            await self.ctx._send(M.DASHBOARD_INTRO, tid=tid, message=message, save=False)

        # Toggle reveals (one-time offers)
        reveals = [
            ("sleep", self.ctx.toggle_service.should_reveal_sleep(profile), M.REVEAL_SLEEP),
            ("eating_window", self.ctx.toggle_service.should_reveal_eating_window(profile), M.REVEAL_EATING_WINDOW),
            ("workouts", self.ctx.toggle_service.should_reveal_workouts(profile, weekday), M.REVEAL_WORKOUTS),
            ("self_care", self.ctx.toggle_service.should_reveal_self_care(profile, weekday), M.REVEAL_SELF_CARE),
        ]

        for toggle_name, should_reveal, reveal_msg in reveals:
            if should_reveal:
                self.ctx.toggle_service.reveal_toggle(tid, toggle_name)
                await self.ctx._send(reveal_msg, tid=tid, message=message)
                return

        # Recurring hooks (with anchor day + time window checks)
        now = clock.now()
        inline_hooks = [
            ("sleep", M.HOOK_SLEEP_PROMPTS, None, SLEEP_HOOK_WINDOW),
            ("workouts", M.HOOK_WORKOUTS_PROMPTS, WORKOUTS_ANCHOR_DAY, WORKOUTS_HOOK_WINDOW),
            ("self_care", M.HOOK_SELF_CARE_PROMPTS, SELF_CARE_ANCHOR_DAY, SELF_CARE_HOOK_WINDOW),
        ]

        for toggle_name, pool, anchor_day, window in inline_hooks:
            if anchor_day is not None and weekday != anchor_day:
                continue
            if not (window[0] <= now.hour < window[1]):
                continue
            if should_fire_inline(profile, toggle_name, clock):
                if toggle_name == "self_care":
                    from services.hook_prompt_service import HookPromptService
                    text = HookPromptService.pick_self_care_prompt(
                        profile.self_care_activities, pool,
                    )
                else:
                    text = random.choice(pool)
                if self.ctx.toggle_service.should_show_exit_door(profile, toggle_name):
                    habit_names = {
                        "sleep": "שינה", "eating_window": "חלון אכילה",
                        "workouts": "אימונים", "self_care": "משהו לעצמי",
                    }
                    text += "\n\n" + random.choice(M.EXIT_DOOR_PROMPTS).format(
                        habit=habit_names.get(toggle_name, "")
                    )
                self.ctx.toggle_service.record_asked(tid, toggle_name)
                self.ctx.toggle_service.increment_unanswered(tid, profile, toggle_name)
                await self.ctx._send(text, tid=tid, message=message)
                return

        # Weekly summary inline hook (Sunday, within window only)
        if (weekday == WEEKLY_SUMMARY_ANCHOR_DAY
                and WEEKLY_SUMMARY_HOOK_WINDOW[0] <= now.hour < WEEKLY_SUMMARY_HOOK_WINDOW[1]
                and should_fire_inline(profile, "weekly_summary", clock)):
            self.ctx.toggle_service.record_asked(tid, "weekly_summary")
            self.ctx.toggle_service.increment_unanswered(tid, profile, "weekly_summary")
            await self.ctx._send(M.WEEKLY_SUMMARY_OFFER, tid=tid, message=message)
            return

        # Wisdom gem (lowest priority)
        if self.ctx.gem_service:
            gem_result = self.ctx.gem_service.try_deliver_gem(profile, clock)
            if gem_result:
                from keyboards import make_gem_feedback_keyboard
                kb = make_gem_feedback_keyboard(gem_result.gem_id)
                await self.ctx._send(gem_result.dressed_text, tid=tid, message=message, reply_markup=kb)
