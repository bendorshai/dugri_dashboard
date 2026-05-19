from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app, session

from auth import login_required
from analyzer import DashboardAnalyzer
from storage import DashboardStorage

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _get_storage() -> DashboardStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


@api_bp.route("/suggest-targets", methods=["POST"])
@login_required
def suggest_targets():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing data"}), 400

    height_cm = data.get("height_cm")
    weight_kg = data.get("weight_kg")
    birth_year = data.get("birth_year")

    if not all([height_cm, weight_kg, birth_year]):
        return jsonify({"error": "missing fields"}), 400

    from datetime import date
    age = date.today().year - int(birth_year)

    cfg = current_app.config["APP_CONFIG"]
    analyzer = DashboardAnalyzer(api_key=cfg["openai"]["api_key"])
    result = analyzer.suggest_targets(
        height_cm=int(height_cm),
        weight_kg=int(weight_kg),
        age=age,
    )

    if result is None:
        return jsonify({"error": "suggestion failed"}), 500

    return jsonify(result)


@api_bp.route("/regenerate-bot-link", methods=["POST"])
@login_required
def regenerate_bot_link():
    email = session["user_email"]
    storage = _get_storage()
    token = storage.regenerate_signup_session_token(email)
    session["signup_session_token"] = token

    cfg = current_app.config["APP_CONFIG"]
    bot_username = cfg.get("dugri_bot_username", "")
    deep_link = f"https://t.me/{bot_username}?start={token}"

    return jsonify({"deep_link": deep_link, "token": token})
