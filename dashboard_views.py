from __future__ import annotations

import logging

import requests
from flask import (
    Blueprint, render_template, redirect, url_for, request, session, current_app,
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
    storage = _get_storage()
    email = session["user_email"]

    user = storage.get_user(email)
    existing_toggles = user.get("toggles", {}) if user else {}

    # Build toggles
    toggle_names = ["sleep", "eating_window", "workouts", "self_care", "target_data", "weekly_summary"]
    toggles = {}
    for name in toggle_names:
        existing = existing_toggles.get(name, {})
        enabled = request.form.get(f"{name}_enabled")
        if enabled:
            toggles[name] = {**existing, "status": "active"}
        else:
            if existing.get("status") == "active":
                toggles[name] = {**existing, "status": "cancelled"}
            else:
                toggles[name] = existing or {"status": "dormant"}

    storage.update_user_toggles(email, toggles)

    # Build targets
    cal_str = request.form.get("calories", "").strip()
    prot_str = request.form.get("protein", "").strip()
    calories = int(cal_str) if cal_str else None
    protein = int(prot_str) if prot_str else None

    old_targets = storage.update_user_targets(email, calories, protein)

    # Additional targets: sleep_time, workouts_per_week
    extra = {}
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
# Weekly summaries archive
# ------------------------------------------------------------------

@dashboard_bp.route("/weekly-summaries")
@login_required
def weekly_summaries():
    storage = _get_storage()
    summaries = storage.get_weekly_summaries(session["user_email"])
    return render_template(
        "dashboard/weekly_summaries.html",
        summaries=summaries,
        active_tab="weekly_summaries",
    )


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
    birth_year = request.form.get("birth_year", "").strip()
    weight_kg = request.form.get("weight_kg", "").strip()
    height_cm = request.form.get("height_cm", "").strip()

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


# ------------------------------------------------------------------
# Legacy goals redirect
# ------------------------------------------------------------------

@dashboard_bp.route("/goals", methods=["GET", "POST"])
@login_required
def goals():
    """Redirect legacy goals URL to preferences page."""
    return redirect(url_for("dashboard_views.preferences"))
