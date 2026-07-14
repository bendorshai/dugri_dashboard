from __future__ import annotations

from datetime import date, datetime, timedelta

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


def format_activity_days(raw: dict, start_date: date, end_date: date) -> list[dict]:
    """Group raw activity data into day-by-day dicts (newest first).

    Shared by the history API and the simulator history endpoint.
    """
    # Group food by date
    food_by_date: dict[str, list] = {}
    for entry in raw["food"]:
        d = entry["date"]
        food_by_date.setdefault(d, []).append({
            "id": str(entry["_id"]),
            "time": entry.get("time", ""),
            "description": entry.get("description", ""),
            "calories": entry.get("calories", 0),
            "protein": entry.get("protein", 0),
            "within_window": entry.get("within_window", True),
        })

    for meals in food_by_date.values():
        meals.sort(key=lambda m: m["time"])

    # Group workouts by date
    workouts_by_date: dict[str, list] = {}
    for entry in raw["workouts"]:
        d = entry["date"]
        workouts_by_date.setdefault(d, []).append({
            "id": str(entry["_id"]),
            "note": entry.get("note", ""),
        })

    # Group sleep by date
    sleep_by_date: dict[str, dict] = {}
    for entry in raw["sleep"]:
        sleep_by_date[entry["date"]] = {
            "id": str(entry["_id"]),
            "sleep_time": entry.get("sleep_time", ""),
        }

    # Self-care by week_id
    self_care_by_week: dict[str, list] = {}
    for entry in raw["self_care"]:
        wid = entry.get("week_id", "")
        self_care_by_week.setdefault(wid, []).append({
            "id": str(entry["_id"]),
            "description": entry.get("description", ""),
        })

    days = []
    current = end_date
    while current >= start_date:
        dd_mm_yyyy = current.strftime("%d/%m/%Y")
        day_name = _HEBREW_DAYS[current.weekday()]
        date_display = f"{current.strftime('%d/%m')} - {day_name}"

        meals = food_by_date.get(dd_mm_yyyy, [])
        day_cal = sum(m["calories"] for m in meals)
        day_prot = sum(m["protein"] for m in meals)

        day_workouts = workouts_by_date.get(dd_mm_yyyy, [])
        day_sleep = sleep_by_date.get(dd_mm_yyyy)

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
            "self_care": day_self_care,
        })

        current -= timedelta(days=1)

    return days


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
    eating_window = raw.get("eating_window")

    days = format_activity_days(raw, start_date, end_date)

    # Compute weekly totals
    total_cal = 0
    total_prot = 0
    days_with_food = 0
    workout_count = 0
    sleep_logged = 0
    for day in days:
        if day["meals"]:
            total_cal += day["meals_total"]["calories"]
            total_prot += day["meals_total"]["protein"]
            days_with_food += 1
        workout_count += len(day["workouts"])
        if day["sleep"]:
            sleep_logged += 1

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
            "sleep_time": targets.get("sleep_time"),
        },
        "eating_window": eating_window,
    })


# -- Activity CRUD endpoints --

@api_bp.route("/food-entry", methods=["POST"])
@login_required
def create_food_entry():
    data = request.get_json()
    if not data or not data.get("date") or not data.get("description"):
        return jsonify({"error": "missing fields"}), 400
    date_str = datetime.strptime(data["date"], "%Y-%m-%d").strftime("%d/%m/%Y")
    now = datetime.now()
    time_str = data.get("time") or now.strftime("%H:%M")
    storage = _get_storage()
    entry_id = storage.create_food_entry(
        session["user_email"],
        date_str,
        time_str,
        data["description"],
        int(data.get("calories", 0)),
        int(data.get("protein", 0)),
    )
    if entry_id:
        return jsonify({"ok": True, "id": entry_id}), 201
    return jsonify({"error": "could not create"}), 400


@api_bp.route("/food-entry/<entry_id>", methods=["DELETE"])
@login_required
def delete_food_entry(entry_id):
    storage = _get_storage()
    if storage.delete_food_entry(session["user_email"], entry_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@api_bp.route("/workout-log/<entry_id>", methods=["DELETE"])
@login_required
def delete_workout_log(entry_id):
    storage = _get_storage()
    if storage.delete_workout_log(session["user_email"], entry_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@api_bp.route("/sleep-log/<entry_id>", methods=["DELETE"])
@login_required
def delete_sleep_log(entry_id):
    storage = _get_storage()
    if storage.delete_sleep_log(session["user_email"], entry_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@api_bp.route("/self-care-log/<entry_id>", methods=["DELETE"])
@login_required
def delete_self_care_log(entry_id):
    storage = _get_storage()
    if storage.delete_self_care_log(session["user_email"], entry_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@api_bp.route("/food-entry/<entry_id>", methods=["PATCH"])
@login_required
def update_food_entry(entry_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing data"}), 400
    storage = _get_storage()
    if storage.update_food_entry(session["user_email"], entry_id, data):
        return jsonify({"ok": True})
    return jsonify({"error": "not found or unchanged"}), 404


@api_bp.route("/workout-log/<entry_id>", methods=["PATCH"])
@login_required
def update_workout_log(entry_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing data"}), 400
    storage = _get_storage()
    if storage.update_workout_log(session["user_email"], entry_id, data):
        return jsonify({"ok": True})
    return jsonify({"error": "not found or unchanged"}), 404


@api_bp.route("/self-care-log/<entry_id>", methods=["PATCH"])
@login_required
def update_self_care_log(entry_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing data"}), 400
    storage = _get_storage()
    if storage.update_self_care_log(session["user_email"], entry_id, data):
        return jsonify({"ok": True})
    return jsonify({"error": "not found or unchanged"}), 404


@api_bp.route("/workout-log", methods=["POST"])
@login_required
def create_workout_log():
    data = request.get_json()
    if not data or not data.get("date"):
        return jsonify({"error": "missing date"}), 400
    # Convert ISO date (YYYY-MM-DD) to DD/MM/YYYY for MongoDB
    date_str = datetime.strptime(data["date"], "%Y-%m-%d").strftime("%d/%m/%Y")
    storage = _get_storage()
    entry_id = storage.create_workout_log(
        session["user_email"], date_str, data.get("note", ""),
    )
    if entry_id:
        return jsonify({"ok": True, "id": entry_id}), 201
    return jsonify({"error": "could not create"}), 400


@api_bp.route("/sleep-log", methods=["POST"])
@login_required
def create_sleep_log():
    data = request.get_json()
    if not data or not data.get("date") or not data.get("sleep_time"):
        return jsonify({"error": "missing date or sleep_time"}), 400
    date_str = datetime.strptime(data["date"], "%Y-%m-%d").strftime("%d/%m/%Y")
    storage = _get_storage()
    entry_id = storage.create_sleep_log(
        session["user_email"], date_str, data["sleep_time"],
    )
    if entry_id:
        return jsonify({"ok": True, "id": entry_id}), 201
    return jsonify({"error": "could not create"}), 400


@api_bp.route("/self-care-log", methods=["POST"])
@login_required
def create_self_care_log():
    data = request.get_json()
    if not data or not data.get("date") or not data.get("description"):
        return jsonify({"error": "missing date or description"}), 400
    # Compute ISO week_id from date
    d = datetime.strptime(data["date"], "%Y-%m-%d")
    iso_year, iso_week, _ = d.isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"
    storage = _get_storage()
    entry_id = storage.create_self_care_log(
        session["user_email"], week_id, data["description"],
    )
    if entry_id:
        return jsonify({"ok": True, "id": entry_id}), 201
    return jsonify({"error": "could not create"}), 400


@api_bp.route("/meta-identifiers", methods=["POST"])
def meta_identifiers():
    """Browser fallback: persist _fbp/_fbc/fbclid for the logged-in user."""
    email = session.get("user_email")
    if not email:
        return jsonify({"error": "not logged in"}), 401
    data = request.get_json(silent=True) or {}
    fbc = data.get("fbc")
    fbclid = data.get("fbclid")
    if not fbc and fbclid:
        # Meta's documented format when only fbclid is available.
        fbc = f"fb.1.{int(datetime.now().timestamp() * 1000)}.{fbclid}"
    storage = _get_storage()
    storage.set_meta_identifiers(
        email,
        fbp=data.get("fbp") or None,
        fbc=fbc or None,
        fbclid=fbclid or None,
        landing_url=data.get("landing_url") or None,
    )
    return jsonify({"status": "ok"})
