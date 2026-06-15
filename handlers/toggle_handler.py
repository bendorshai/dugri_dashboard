"""
toggle_handler.py - Toggle lifecycle, goal flows, and opt-in logic.
"""

from __future__ import annotations

import logging

from models.profile import UserProfile
from handlers.context import HandlerContext

logger = logging.getLogger(__name__)


class ToggleHandler:
    def __init__(self, ctx: HandlerContext, parent=None):
        self.ctx = ctx
        self._parent = parent


    async def handle_conversation_reply(
        self, message, context, tid: int, profile: UserProfile, classification,
    ):
        """Handle a message classified as conversation_reply by GPT.

        Routes based on toggle_state + conversation history. No pending_state.
        conversation_reply = cooperation. The user is responding positively
        to whatever the bot asked.
        """
        text = message.text.strip()
        response = None

        # Nutrition goal flow (multi-step: body stats -> weight goal -> confirm)
        nt = profile.toggles.nutrition
        if nt.status == "active" and nt.goal_status == "pending" and nt.goal_offered_at and self.ctx.goal_service:
            response = self._route_nutrition_goal_flow(tid, text, profile)
            if response:
                await self.ctx._send(response, tid=tid, message=message)
                return

        # Other habit goal flows (sleep, workouts, eating_window)
        for name in ("sleep", "eating_window", "workouts"):
            toggle = getattr(profile.toggles, name, None)
            if toggle and toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
                if self.ctx.goal_service:
                    response = self.ctx.goal_service.handle_goal_value(tid, name, text)
                    if response:
                        await self.ctx._send(response, tid=tid, message=message)
                        return

        # Remind pending: user is answering "want me to remind you?"
        for name in ("nutrition", "sleep", "eating_window", "workouts"):
            toggle = getattr(profile.toggles, name, None)
            if toggle and toggle.goal_status == "remind_pending":
                if self.ctx.goal_service:
                    response = self.ctx.goal_service.handle_remind_accept(tid, name)
                    if response:
                        await self.ctx._send(response, tid=tid, message=message)
                        return

        # Offered but not activated: user is accepting the offer
        for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care"):
            toggle = getattr(profile.toggles, name, None)
            if toggle and toggle.revealed_at and toggle.status == "dormant":
                self.ctx.toggle_service.activate_toggle(tid, name)
                if self.ctx.goal_service and self.ctx.goal_service.should_offer_goal(profile, name):
                    response = self.ctx.goal_service.offer_goal_with_shortcut(tid, name, text)
                else:
                    import messages as M
                    loop_close = M.LOOP_CLOSE_ACTIVATION.get(name, "")
                    response = "יפה, נרשמתי." + loop_close
                await self.ctx._send(response, tid=tid, message=message)
                return

        # Safety net: no route matched
        logger.warning("conversation_reply matched no route for tid=%d, text=%r", tid, text)
        fallback = "לא הבנתי על מה אתה עונה. אפשר לנסות שוב?"
        await self.ctx._send(fallback, tid=tid, message=message)

    def _route_nutrition_goal_flow(self, tid: int, text: str, profile: UserProfile) -> str | None:
        """Route within the nutrition multi-step goal flow."""
        import messages as M

        nt = profile.toggles.nutrition

        # Step 3: suggestion was presented (goal_value stored by handle_weight_goal)
        if nt.goal_value:
            return self.ctx.goal_service.handle_nutrition_confirm(tid, text)

        # Step 2: bot asked about weight goal direction
        recent = self.ctx.user_repo.get_recent_messages(tid, 5)
        last_bot_msg = ""
        for msg in reversed(recent):
            if msg.get("role") == "bot":
                last_bot_msg = msg.get("text", "")
                break

        if last_bot_msg in M.NUTRITION_WEIGHT_GOAL_ASK:
            return self.ctx.goal_service.handle_weight_goal(tid, text, self.ctx._get_profile(tid))

        # Step 1 (default): collect body stats
        return self.ctx.goal_service.handle_body_stats(tid, text)

    # ------------------------------------------------------------------
    # Toggle flow guards
    # ------------------------------------------------------------------

    def is_toggle_in_flow(self, profile: UserProfile, toggle_name: str) -> bool:
        toggle = getattr(profile.toggles, toggle_name, None)
        if not toggle:
            return False
        if toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
            return True
        if toggle.status == "dormant" and toggle.revealed_at:
            return True
        if toggle.goal_status == "remind_pending":
            return True
        return False

    def any_toggle_in_flow(self, profile: UserProfile) -> bool:
        for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care", "weekly_summary"):
            if self.is_toggle_in_flow(profile, name):
                return True
        return False

    # ------------------------------------------------------------------
    # Toggle cancel handler (context-aware refusal)
    # ------------------------------------------------------------------

    async def handle_toggle_cancel(
        self, message, context, tid: int, profile: UserProfile, classification,
    ):
        import messages as M
        import random

        if not self.ctx.toggle_service:
            return

        toggle_name = classification.toggle_name
        if not toggle_name:
            for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care"):
                toggle = getattr(profile.toggles, name, None)
                if toggle and toggle.revealed_at and toggle.status == "dormant":
                    toggle_name = name
                    break
            if not toggle_name:
                for name in ("nutrition", "sleep", "eating_window", "workouts"):
                    toggle = getattr(profile.toggles, name, None)
                    if toggle and toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
                        toggle_name = name
                        break

        if not toggle_name or toggle_name not in {"sleep", "eating_window", "workouts", "self_care", "nutrition", "weekly_summary"}:
            return

        toggle = getattr(profile.toggles, toggle_name, None)
        tone = classification.refusal_tone or "sharp"

        # Case 1: Decline during remind_pending
        if toggle and toggle.goal_status == "remind_pending":
            self.ctx.toggle_service.cancel_toggle(tid, toggle_name)
            response = random.choice(M.GOAL_DECLINED_FOREVER)
            await self.ctx._send(response, tid=tid, message=message)
            return

        # Case 2: Decline during goal-setting (active + goal pending)
        if toggle and toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
            if self.ctx.goal_service:
                self.ctx.goal_service.skip_goal(tid, toggle_name)

                soft_pools = {
                    "nutrition": M.GOAL_SOFT_DECLINE_NUTRITION,
                    "sleep": M.GOAL_SOFT_DECLINE_SLEEP,
                    "workouts": M.GOAL_SOFT_DECLINE_WORKOUTS,
                    "eating_window": M.GOAL_SOFT_DECLINE_EATING_WINDOW,
                }
                pool = soft_pools.get(toggle_name)
                if pool:
                    decline_msg = random.choice(pool)
                    remind_msg = self.ctx.goal_service.ask_remind(tid, toggle_name)
                    response = decline_msg + "\n\n" + remind_msg
                else:
                    response = self.ctx.goal_service.ask_remind(tid, toggle_name)

                await self.ctx._send(response, tid=tid, message=message)
            return

        # Case 3: Decline during offer (dormant + revealed, not yet activated)
        if toggle and toggle.revealed_at and toggle.status == "dormant":
            if tone == "soft":
                response = random.choice(M.OFFER_SOFT_DECLINE)
            else:
                response = random.choice(M.OFFER_SHARP_DECLINE)
            if self.ctx.goal_service:
                self.ctx.goal_service.ask_remind(tid, toggle_name)
            await self.ctx._send(response, tid=tid, message=message)
            return

        # Case 4: Cancel an active habit (no pending flow)
        self.ctx.toggle_service.cancel_toggle(tid, toggle_name)
        await self.ctx._send(M.EXIT_DOOR_CANCELLED, tid=tid, message=message)

    # ------------------------------------------------------------------
    # Opt-in unified handler (Router v2 dispatch)
    # ------------------------------------------------------------------

    async def handle_opt_in(
        self, message, context, tid: int, profile: UserProfile, router_result,
    ):
        text = message.text.strip()

        toggle_name = router_result.toggle_name
        if not toggle_name:
            for name in ("nutrition", "sleep", "eating_window", "workouts", "self_care"):
                if self.is_toggle_in_flow(profile, name):
                    toggle_name = name
                    break

        # Use parent's method if available (allows test mocking)
        _conv_reply = self._parent._handle_conversation_reply if self._parent else self.handle_conversation_reply

        if toggle_name:
            toggle = getattr(profile.toggles, toggle_name, None)
            if toggle:
                # Goal pending
                if toggle.status == "active" and toggle.goal_status == "pending" and toggle.goal_offered_at:
                    await _conv_reply(message, context, tid, profile, router_result)
                    return

                # Remind pending
                if toggle.goal_status == "remind_pending":
                    await _conv_reply(message, context, tid, profile, router_result)
                    return

                # Offered (dormant + revealed)
                if toggle.revealed_at and toggle.status == "dormant":
                    await _conv_reply(message, context, tid, profile, router_result)
                    return

                # Active with goal -> possible goal update
                if toggle.goal_status == "set" and self.ctx.goal_service:
                    response = self.ctx.goal_service.handle_goal_update(tid, toggle_name, text, profile)
                    if response:
                        await self.ctx._send(response, tid=tid, message=message)
                        return

        # User-initiated tracking request (toggle dormant/cancelled)
        if toggle_name and self.ctx.toggle_service:
            toggle = getattr(profile.toggles, toggle_name, None)
            if toggle and toggle.status in ("dormant", "cancelled"):
                self.ctx.toggle_service.activate_toggle(tid, toggle_name)
                if self.ctx.goal_service and self.ctx.goal_service.should_offer_goal(profile, toggle_name):
                    response = self.ctx.goal_service.offer_goal_with_shortcut(tid, toggle_name, text)
                    await self.ctx._send(response, tid=tid, message=message)
                else:
                    import messages as M
                    loop_close = M.LOOP_CLOSE_ACTIVATION.get(toggle_name, "")
                    response = "יפה, נרשמתי. מעכשיו אני עוקב." + loop_close
                    await self.ctx._send(response, tid=tid, message=message)
                return

        # Fallback
        await _conv_reply(message, context, tid, profile, router_result)
