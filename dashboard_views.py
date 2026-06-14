from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from flask import (
    Blueprint, jsonify, render_template, redirect, url_for, request, session, current_app,
)

from auth import login_required
from storage import DashboardStorage

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
    return render_template("dashboard/profile.html", user=user, active_tab="profile")


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
    if gender in ("male", "female"):
        profile_data["gender"] = gender
    else:
        profile_data["gender"] = None
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

    storage.update_user_profile(email, profile_data)
    return redirect(url_for("dashboard_views.profile"))


# ------------------------------------------------------------------
# Subscription (unchanged)
# ------------------------------------------------------------------

@dashboard_bp.route("/subscription")
@login_required
def subscription():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    return render_template("dashboard/subscription.html", user=user, active_tab="subscription")
