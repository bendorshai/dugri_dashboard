from __future__ import annotations

from flask import (
    Blueprint, render_template, redirect, url_for, request, session, current_app,
)

from auth import login_required
from storage import DashboardStorage
from key_generator import generate_bot_key

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")

TOTAL_STEPS = 4


def _get_storage() -> DashboardStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


@onboarding_bp.route("/step/<int:step_num>", methods=["GET"])
@login_required
def step(step_num: int):
    if step_num < 1 or step_num > TOTAL_STEPS:
        return redirect(url_for("onboarding.step", step_num=1))

    storage = _get_storage()
    user = storage.get_user(session["user_email"])

    if step_num == 1:
        return render_template(
            "onboarding/step1_profile.html",
            step=step_num, total=TOTAL_STEPS, user=user,
        )
    elif step_num == 2:
        return render_template(
            "onboarding/step2_goals.html",
            step=step_num, total=TOTAL_STEPS, user=user,
        )
    elif step_num == 3:
        return render_template(
            "onboarding/step3_terms.html",
            step=step_num, total=TOTAL_STEPS, user=user,
        )
    elif step_num == 4:
        cfg = current_app.config["APP_CONFIG"]
        bot_key = user.get("bot_key") or generate_bot_key(
            session["user_email"], cfg["bot_key_salt"],
        )
        telegram_bot_url = cfg.get("telegram_bot_url", "")
        return render_template(
            "onboarding/step4_bot_key.html",
            step=step_num, total=TOTAL_STEPS,
            bot_key=bot_key, telegram_bot_url=telegram_bot_url,
        )


@onboarding_bp.route("/step/<int:step_num>", methods=["POST"])
@login_required
def step_post(step_num: int):
    storage = _get_storage()
    email = session["user_email"]

    if step_num == 1:
        profile_data = {}
        birth_year = request.form.get("birth_year", "").strip()
        weight_kg = request.form.get("weight_kg", "").strip()
        height_cm = request.form.get("height_cm", "").strip()

        if birth_year:
            profile_data["birth_year"] = int(birth_year)
        if weight_kg:
            profile_data["weight_kg"] = int(weight_kg)
        if height_cm:
            profile_data["height_cm"] = int(height_cm)

        if profile_data:
            storage.update_user_profile(email, profile_data)

        return redirect(url_for("onboarding.step", step_num=2))

    elif step_num == 2:
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
        return redirect(url_for("onboarding.step", step_num=3))

    elif step_num == 3:
        storage.update_user_profile(email, {"terms_accepted": True})
        return redirect(url_for("onboarding.step", step_num=4))

    elif step_num == 4:
        storage.complete_onboarding(email)
        return redirect(url_for("dashboard_views.goals"))

    return redirect(url_for("onboarding.step", step_num=1))
