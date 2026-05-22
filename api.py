from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, request, current_app, session

from auth import login_required
from analyzer import DashboardAnalyzer
from storage import DashboardStorage

# Hebrew day names (Sunday=0 .. Saturday=6 mapped from Python's Monday=0)
_HEBREW_DAYS = {
    0: "יום שני",
    1: "יום שלישי",
    2: "יום רביעי",
    3: "יום חמישי",
    4: "יום שישי",
    5: "יום שבת",
    6: "יום ראשון",
}

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


@api_bp.route("/activity-history", methods=["GET"])
@login_required
def activity_history():
    """Return activity data organized by date for the history page."""
    storage = _get_storage()
    email = session["user_email"]

    # Parse date range (defaults to last 7 days)
    today = date.today()
    start_str = request.args.get("start")
    end_str = request.args.get("end")

    try:
        start_date = date.fromisoformat(start_str) if start_str else today - timedelta(days=6)
        end_date = date.fromisoformat(end_str) if end_str else today
    except ValueError:
        return jsonify({"error": "invalid date format, use YYYY-MM-DD"}), 400

    # Cap range to 31 days
    if (end_date - start_date).days > 31:
        start_date = end_date - timedelta(days=31)

    raw = storage.get_activity_history(email, start_date, end_date)
    targets = raw["targets"]

    # Group food by date
    food_by_date: dict[str, list] = {}
    for entry in raw["food"]:
        d = entry["date"]
        food_by_date.setdefault(d, []).append({
            "time": entry.get("time", ""),
            "description": entry.get("description", ""),
            "calories": entry.get("calories", 0),
            "protein": entry.get("protein", 0),
        })

    # Sort meals by time within each day
    for meals in food_by_date.values():
        meals.sort(key=lambda m: m["time"])

    # Group workouts by date
    workouts_by_date: dict[str, list] = {}
    for entry in raw["workouts"]:
        d = entry["date"]
        workouts_by_date.setdefault(d, []).append({
            "note": entry.get("note", ""),
        })

    # Group sleep by date
    sleep_by_date: dict[str, dict] = {}
    for entry in raw["sleep"]:
        sleep_by_date[entry["date"]] = {
            "sleep_time": entry.get("sleep_time", ""),
        }

    # Self-care by week_id
    self_care_by_week: dict[str, list] = {}
    for entry in raw["self_care"]:
        wid = entry.get("week_id", "")
        self_care_by_week.setdefault(wid, []).append({
            "description": entry.get("description", ""),
        })

    # Build day-by-day response (newest first)
    days = []
    total_cal = 0
    total_prot = 0
    days_with_food = 0
    workout_count = 0
    sleep_logged = 0

    current = end_date
    while current >= start_date:
        dd_mm_yyyy = current.strftime("%d/%m/%Y")
        day_name = _HEBREW_DAYS[current.weekday()]
        date_display = f"{current.strftime('%d/%m')} — {day_name}"

        meals = food_by_date.get(dd_mm_yyyy, [])
        day_cal = sum(m["calories"] for m in meals)
        day_prot = sum(m["protein"] for m in meals)

        if meals:
            total_cal += day_cal
            total_prot += day_prot
            days_with_food += 1

        day_workouts = workouts_by_date.get(dd_mm_yyyy, [])
        workout_count += len(day_workouts)

        day_sleep = sleep_by_date.get(dd_mm_yyyy)
        if day_sleep:
            sleep_logged += 1

        # Self-care for this day's week
        iso_year, iso_week, _ = current.isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"
        day_self_care = self_care_by_week.get(week_id, [])

        days.append({
            "date": current.isoformat(),
            "date_display": date_display,
            "meals": meals,
            "meals_total": {"calories": day_cal, "protein": day_prot},
            "workouts": day_workouts,
            "sleep": day_sleep,
            "self_care": day_self_care if current.weekday() == 6 else [],  # show on Sunday only to avoid repetition
        })

        current -= timedelta(days=1)

    num_days = (end_date - start_date).days + 1
    weekly_totals = {
        "avg_calories": round(total_cal / days_with_food) if days_with_food else 0,
        "avg_protein": round(total_prot / days_with_food) if days_with_food else 0,
        "workout_count": workout_count,
        "sleep_logged_days": sleep_logged,
        "total_days": num_days,
    }

    return jsonify({
        "days": days,
        "weekly_totals": weekly_totals,
        "targets": {
            "calories": targets.get("calories"),
            "protein": targets.get("protein"),
            "workouts_per_week": targets.get("workouts_per_week"),
        },
    })
