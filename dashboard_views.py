from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone

import requests
from flask import (
    Blueprint, flash, jsonify, render_template, redirect, url_for, request, session, current_app,
)

from auth import login_required
from storage import DashboardStorage
from services.green_invoice import GreenInvoiceService, GreenInvoiceError
from supported_timezones import SUPPORTED_TIMEZONES, DEFAULT_TIMEZONE, is_valid_timezone

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard_views", __name__, url_prefix="/dashboard")


def _get_storage() -> DashboardStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


@dashboard_bp.route("/")
@login_required
def index():
    return redirect(url_for("dashboard_views.home"))


@dashboard_bp.route("/home")
@login_required
def home():
    cfg = current_app.config["APP_CONFIG"]
    bot_username = cfg.get("dugri_bot_username", "")
    return render_template(
        "dashboard/home.html", active_tab="home",
        telegram_bot_url=f"https://t.me/{bot_username}",
    )


# ------------------------------------------------------------------
# Preferences (merged toggles + targets)
# ------------------------------------------------------------------

@dashboard_bp.route("/preferences", methods=["GET"])
@login_required
def preferences():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    return render_template("dashboard/preferences.html", user=user, active_tab="preferences")


@dashboard_bp.route("/preferences", methods=["POST"])
@login_required
def preferences_post():
    # ---------------------------------------------------------------
    # IMPORTANT: Toggle state invariants
    #
    # The bot's ToggleService (health_tracker/services/toggle_service.py)
    # enforces these invariants when changing toggle status:
    #
    #   activate_toggle() sets: status="active", activated_at=now,
    #                           consecutive_unanswered=0
    #   reveal_toggle()   sets: revealed_at=now
    #   cancel_toggle()   sets: status="cancelled"
    #
    # The dashboard writes directly to MongoDB (no shared service layer
    # with the bot), so it MUST maintain these invariants manually.
    # Failing to do so creates impossible states that break the bot's
    # lazy opt-in flow (e.g. status="active" with activated_at=None
    # makes the bot think a goal flow is pending that was never started).
    #
    # When changing toggle status here, always use _apply_toggle_status()
    # to ensure the right timestamp fields are set.
    # ---------------------------------------------------------------
    storage = _get_storage()
    email = session["user_email"]

    user = storage.get_user(email)
    existing_toggles = user.get("toggles", {}) if user else {}

    toggle_names = ["sleep", "eating_window", "workouts", "self_care", "nutrition", "weekly_summary"]
    toggles = {}
    for name in toggle_names:
        existing = existing_toggles.get(name, {})
        status = request.form.get(f"{name}_status")
        if status in ("dormant", "active", "cancelled"):
            toggles[name] = _apply_toggle_status(existing, status)
        else:
            enabled = request.form.get(f"{name}_enabled")
            if enabled:
                toggles[name] = _apply_toggle_status(existing, "active")
            else:
                toggles[name] = existing or {"status": "dormant"}

    storage.update_user_toggles(email, toggles)

    # Build targets
    cal_str = request.form.get("calories", "").strip()
    prot_str = request.form.get("protein", "").strip()
    calories = int(cal_str) if cal_str else None
    protein = int(prot_str) if prot_str else None

    old_targets = storage.update_user_targets(email, calories, protein)

    # Additional targets: weight_goal, sleep_time, workouts_per_week
    extra = {}
    weight_goal = request.form.get("weight_goal", "").strip()
    if weight_goal in ("lose", "maintain", "gain"):
        extra["targets.weight_goal"] = weight_goal
    elif weight_goal == "":
        extra["targets.weight_goal"] = None

    sleep_target = request.form.get("sleep_target", "").strip()
    if sleep_target:
        extra["targets.sleep_time"] = sleep_target
    workouts_str = request.form.get("workouts_per_week", "").strip()
    if workouts_str:
        extra["targets.workouts_per_week"] = int(workouts_str)

    # Eating window
    ew_start = request.form.get("eating_window_start", "").strip()
    ew_end = request.form.get("eating_window_end", "").strip()
    if ew_start and ew_end and toggles.get("eating_window", {}).get("status") == "active":
        extra["eating_window"] = {"start": ew_start, "end": ew_end}

    if extra:
        storage.update_user_profile(email, extra)

    # Notify bot if calorie/protein targets changed
    new_targets = {"calories": calories, "protein": protein}
    if old_targets.get("calories") != calories or old_targets.get("protein") != protein:
        _notify_bot_target_change(email, old_targets, new_targets)

    return redirect(url_for("dashboard_views.preferences"))


# Legacy redirects
@dashboard_bp.route("/toggles", methods=["GET", "POST"])
@login_required
def toggles():
    return redirect(url_for("dashboard_views.preferences"))


@dashboard_bp.route("/targets", methods=["GET", "POST"])
@login_required
def targets():
    return redirect(url_for("dashboard_views.preferences"))


def _apply_toggle_status(existing: dict, new_status: str) -> dict:
    """Build a toggle dict with the correct timestamp fields for a status change.

    Mirrors the invariants from the bot's ToggleService:
    - dormant:   clear revealed_at, activated_at; reset edu_intro_shown
    - active:    set activated_at (and revealed_at if missing); set edu_intro_shown
    - cancelled: keep timestamps as-is (for historical record)

    Always preserves goal_value, goal_status, and other fields from existing.
    """
    toggle = {**existing, "status": new_status}
    now = datetime.now(timezone.utc).isoformat()

    if new_status == "dormant":
        toggle["revealed_at"] = None
        toggle["activated_at"] = None
        toggle["edu_intro_shown"] = False
        toggle["consecutive_unanswered"] = 0
    elif new_status == "active":
        # Only set timestamps if transitioning TO active (not already active)
        if existing.get("status") != "active":
            toggle["activated_at"] = now
            if not toggle.get("revealed_at"):
                toggle["revealed_at"] = now
            toggle["consecutive_unanswered"] = 0
        toggle["edu_intro_shown"] = True
    # cancelled: preserve existing timestamps, no special fields needed

    return toggle


def _notify_bot_target_change(email: str, old_targets: dict, new_targets: dict):
    """Send target change notification to bot's internal webhook."""
    cfg = current_app.config["APP_CONFIG"]
    bot_url = cfg.get("bot_internal_url", "")
    secret = cfg.get("internal_secret", "")

    if not bot_url:
        return

    user = _get_storage().get_user(email)
    if not user or not user.get("telegram_user_id"):
        return

    try:
        requests.post(
            f"{bot_url}/internal/notify-target-update",
            json={
                "telegram_user_id": user["telegram_user_id"],
                "old_targets": old_targets,
                "new_targets": new_targets,
            },
            headers={"X-Internal-Secret": secret},
            timeout=5,
        )
    except Exception:
        logger.exception("Failed to notify bot about target change")


# ------------------------------------------------------------------
# Activity history
# ------------------------------------------------------------------

@dashboard_bp.route("/history")
@login_required
def history():
    return render_template("dashboard/history.html", active_tab="history")


# ------------------------------------------------------------------
# Weekly summaries archive
# ------------------------------------------------------------------

@dashboard_bp.route("/weekly-summaries")
@login_required
def weekly_summaries():
    storage = _get_storage()
    email = session["user_email"]
    summaries = storage.get_weekly_summaries(email)
    trend = storage.get_trend_data(email, days=30)
    return render_template(
        "dashboard/weekly_summaries.html",
        summaries=summaries,
        trend_days=trend["days"],
        trend_targets=trend["targets"],
        active_tab="weekly_summaries",
    )


@dashboard_bp.route("/api/trend")
@login_required
def trend_api():
    """JSON endpoint for trend data (calories, protein, workouts)."""
    storage = _get_storage()
    try:
        days = int(request.args.get("days", 30))
    except (ValueError, TypeError):
        days = 30
    if days < 0:
        days = 30
    data = storage.get_trend_data(session["user_email"], days=days)
    return jsonify(data)


# ------------------------------------------------------------------
# Profile (unchanged)
# ------------------------------------------------------------------

@dashboard_bp.route("/profile", methods=["GET"])
@login_required
def profile():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    # Dropdown options: the curated list, plus the user's current zone if it was
    # auto-detected to something we don't list (so it still displays as selected).
    current_tz = (user or {}).get("timezone") or DEFAULT_TIMEZONE
    tz_options = list(SUPPORTED_TIMEZONES)
    if current_tz not in tz_options:
        tz_options.insert(0, current_tz)
    return render_template(
        "dashboard/profile.html",
        user=user,
        active_tab="profile",
        timezone_options=tz_options,
        current_timezone=current_tz,
    )


@dashboard_bp.route("/profile", methods=["POST"])
@login_required
def profile_post():
    storage = _get_storage()
    email = session["user_email"]

    profile_data = {}
    name = request.form.get("name", "").strip()
    birth_year = request.form.get("birth_year", "").strip()
    weight_kg = request.form.get("weight_kg", "").strip()
    height_cm = request.form.get("height_cm", "").strip()

    gender = request.form.get("gender", "").strip()

    if name:
        profile_data["name"] = name
        profile_data["onboarding.name_collected"] = True
    else:
        profile_data["name"] = None
    if gender in ("male", "female", "other"):
        profile_data["gender"] = gender
    else:
        profile_data["gender"] = None
    address_form = request.form.get("address_form", "").strip()
    if gender == "other" and address_form in ("male", "female"):
        profile_data["address_form"] = address_form
    elif gender in ("male", "female"):
        profile_data["address_form"] = None
    if birth_year:
        profile_data["birth_year"] = int(birth_year)
    else:
        profile_data["birth_year"] = None
    if weight_kg:
        profile_data["weight_kg"] = int(weight_kg)
    else:
        profile_data["weight_kg"] = None
    if height_cm:
        profile_data["height_cm"] = int(height_cm)
    else:
        profile_data["height_cm"] = None

    # Timezone: written only when the submitted zone actually DIFFERS from the
    # stored one. Diffing (rather than trusting the JS-set source field) means a
    # manual dropdown change persists even if client JS failed to set the source,
    # while an unrelated profile save (unchanged zone) never clobbers the stored
    # provenance/updated_at. The source refines manual vs the banner's confirmed;
    # anything else is treated as manual. Invalid values are silently ignored
    # (house rule: silent errors, server log only).
    tz = request.form.get("timezone", "").strip()
    if tz and is_valid_timezone(tz):
        # Compare against the SAME effective zone the page rendered in the dropdown
        # (a legacy user with no stored timezone key renders the default), so an
        # unrelated save that submits the unchanged default is not misread as a
        # deliberate change that fabricates 'user_manual' provenance.
        stored_tz = (storage.get_user(email) or {}).get("timezone") or DEFAULT_TIMEZONE
        if tz != stored_tz:
            tz_source = request.form.get("timezone_source", "").strip()
            if tz_source not in ("user_manual", "user_confirmed"):
                tz_source = "user_manual"
            profile_data["timezone"] = tz
            profile_data["timezone_source"] = tz_source
            profile_data["timezone_updated_at"] = datetime.now(timezone.utc).isoformat()
    elif tz:
        logger.warning("profile_post: ignoring invalid timezone %r for %s", tz, email)

    storage.update_user_profile(email, profile_data)
    return redirect(url_for("dashboard_views.profile"))


# ------------------------------------------------------------------
# Subscription
# ------------------------------------------------------------------

def _get_gi_service() -> GreenInvoiceService:
    cfg = current_app.config["APP_CONFIG"]
    gi_cfg = cfg["green_invoice"]
    return GreenInvoiceService(
        api_id=gi_cfg["api_id"],
        api_secret=gi_cfg["api_secret"],
        sandbox=gi_cfg.get("sandbox", True),
    )


def _subscription_price() -> int:
    cfg = current_app.config["APP_CONFIG"]
    return cfg.get("green_invoice", {}).get("subscription_price_ils", 47)


def _format_date_he(iso_str: str | None) -> str:
    """Format an ISO datetime string as DD/MM/YYYY for Hebrew display."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str))
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return ""


@dashboard_bp.route("/subscription")
@login_required
def subscription():
    import hebrew_strings as hs

    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    cfg = current_app.config["APP_CONFIG"]
    price = _subscription_price()
    contact_email = cfg.get("contact_email", "")

    status = user.get("subscription_status", "trial_pending") if user else "trial_pending"
    expires_at = _format_date_he(user.get("subscription_expires_at")) if user else ""

    return render_template(
        "dashboard/subscription.html",
        user=user,
        active_tab="subscription",
        price=price,
        status=status,
        expires_at=expires_at,
        contact_email=contact_email,
        hs=hs,
    )


@dashboard_bp.route("/subscription/start", methods=["POST"])
@login_required
def subscription_start():
    """Generate Green Invoice payment form URL and redirect user."""
    storage = _get_storage()
    email = session["user_email"]
    user = storage.get_user(email)

    price = _subscription_price()
    base_url = request.url_root.rstrip("/")
    success_url = f"{base_url}{url_for('dashboard_views.subscription_success')}"
    failure_url = f"{base_url}{url_for('dashboard_views.subscription_failure')}"
    notify_url = f"{base_url}{url_for('dashboard_views.subscription_webhook')}"

    try:
        gi = _get_gi_service()
        form_url = gi.get_payment_form_url(
            user_email=email,
            user_name=user.get("name", "") if user else "",
            amount_ils=price,
            success_url=success_url,
            failure_url=failure_url,
            notify_url=notify_url,
        )
        return redirect(form_url)
    except GreenInvoiceError:
        logger.exception("Failed to create payment form")
        import hebrew_strings as hs
        flash(hs.SUB_FAILURE_FLASH, "error")
        return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/success")
@login_required
def subscription_success():
    import hebrew_strings as hs
    flash(hs.SUB_SUCCESS_FLASH, "success")
    return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/failure")
@login_required
def subscription_failure():
    import hebrew_strings as hs
    flash(hs.SUB_FAILURE_FLASH, "error")
    return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/cancel", methods=["POST"])
@login_required
def subscription_cancel():
    """Cancel subscription - keeps access until period ends."""
    storage = _get_storage()
    email = session["user_email"]
    user = storage.get_user(email)

    if user and user.get("subscription_status") == "paid":
        storage.update_user_profile(email, {
            "subscription_status": "cancelled",
            "subscription_cancelled_at": DashboardStorage._now(),
        })

    return redirect(url_for("dashboard_views.subscription"))


@dashboard_bp.route("/subscription/webhook", methods=["POST"])
def subscription_webhook():
    """Green Invoice IPN webhook - called by GI servers after payment."""
    gi_type = request.args.get("gi-type", "")

    if gi_type != "ipn":
        return jsonify({"status": "ignored"}), 200

    data = request.json or request.form.to_dict()
    user_email = data.get("custom", "")
    token_id = data.get("tokenId") or data.get("token_id", "")

    if not user_email:
        logger.warning("Webhook missing user email in custom field")
        return jsonify({"error": "missing user email"}), 400

    storage = _get_storage()
    user = storage.get_user(user_email)
    if not user:
        logger.warning("Webhook for unknown user: %s", user_email)
        return jsonify({"error": "user not found"}), 404

    now = DashboardStorage._now()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    storage.update_user_profile(user_email, {
        "subscription_status": "paid",
        "subscription_token_id": token_id,
        "subscription_started_at": now,
        "subscription_expires_at": expires_at,
        "subscription_last_charged_at": now,
        "subscription_expiry_message_sent": False,
        "subscription_end_acknowledged": False,
    })

    # Fire the Meta Purchase conversion event (best-effort, deduped by token id).
    try:
        import services.meta_capi as meta_capi
        cfg = current_app.config["APP_CONFIG"]
        price = cfg.get("green_invoice", {}).get("subscription_price_ils", 47)
        event_id = meta_capi._sha256(f"purchase:{token_id or user_email}")
        outcome = meta_capi.send_event(
            cfg.get("meta", {}),
            email=user_email,
            event_name="Purchase",
            event_id=event_id,
            user_meta=user.get("meta"),
            custom_data={"value": price, "currency": "ILS"},
            action_source="website",
        )
        # Record it in our own audit log (only when a send was actually attempted).
        if outcome is not None:
            storage.log_meta_event(
                telegram_user_id=user.get("telegram_user_id"), user_email=user_email,
                event_key="paid", event_name="Purchase", action_source="website",
                event_time=None, custom_data={"value": price, "currency": "ILS"},
                **outcome,
            )
    except Exception:
        logger.warning("Meta Purchase event failed (non-fatal)", exc_info=True)

    logger.info("Subscription activated for %s (token: %s)", user_email, token_id[:8] if token_id else "none")
    return jsonify({"status": "ok"}), 200
