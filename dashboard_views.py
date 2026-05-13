from __future__ import annotations

from flask import (
    Blueprint, render_template, redirect, url_for, request, session, current_app,
)

from auth import login_required
from storage import DashboardStorage

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
    telegram_bot_url = cfg.get("telegram_bot_url", "")
    return render_template(
        "dashboard/home.html", active_tab="home",
        telegram_bot_url=telegram_bot_url,
    )


@dashboard_bp.route("/goals", methods=["GET"])
@login_required
def goals():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    return render_template("dashboard/goals.html", user=user, active_tab="goals")


@dashboard_bp.route("/goals", methods=["POST"])
@login_required
def goals_post():
    storage = _get_storage()
    email = session["user_email"]

    goals = {}

    if request.form.get("calories_enabled"):
        goals["calories"] = {
            "enabled": True,
            "target": int(request.form.get("calories_target", 2000)),
        }
    if request.form.get("protein_enabled"):
        goals["protein"] = {
            "enabled": True,
            "target": int(request.form.get("protein_target", 150)),
        }
    if request.form.get("eating_window_enabled"):
        goals["eating_window"] = {
            "enabled": True,
            "start": request.form.get("eating_window_start", "08:00"),
            "end": request.form.get("eating_window_end", "20:00"),
        }
    if request.form.get("sleep_enabled"):
        goals["sleep"] = {
            "enabled": True,
            "target_time": request.form.get("sleep_target", "23:00"),
        }
    if request.form.get("coffee_enabled"):
        goals["coffee"] = {
            "enabled": True,
            "target": int(request.form.get("coffee_target", 3)),
        }
    if request.form.get("workouts_enabled"):
        goals["workouts"] = {
            "enabled": True,
            "weekly_target": int(request.form.get("workouts_target", 3)),
        }

    storage.update_user_goals(email, goals)
    return redirect(url_for("dashboard_views.goals"))


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


@dashboard_bp.route("/subscription")
@login_required
def subscription():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    return render_template("dashboard/subscription.html", user=user, active_tab="subscription")
