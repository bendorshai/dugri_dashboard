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
    return redirect(url_for("dashboard_views.goals"))


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


@dashboard_bp.route("/subscription")
@login_required
def subscription():
    storage = _get_storage()
    user = storage.get_user(session["user_email"])
    return render_template("dashboard/subscription.html", user=user, active_tab="subscription")
