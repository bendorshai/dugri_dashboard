from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

import requests
from flask import Blueprint, render_template, current_app, request, jsonify

from admin_storage import AdminStorage
from storage import DashboardStorage
from auth import admin_required

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# OpenAI pricing per 1M tokens (source: openai.com/api/pricing, 2026-06-07)
MODEL_PRICING = {
    "gpt-4o":      {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def _format_tokens_tooltip(tokens_used: dict) -> str:
    """Build a tooltip string showing per-model token counts + USD cost."""
    if not tokens_used:
        return ""
    lines = []
    for model, counts in sorted(tokens_used.items()):
        if not isinstance(counts, dict):
            continue
        prompt = counts.get("prompt", 0)
        completion = counts.get("completion", 0)
        total = prompt + completion
        pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
        cost = prompt * pricing["input"] / 1_000_000 + completion * pricing["output"] / 1_000_000
        lines.append(f"{model}: {total:,} tokens (${cost:.4f})")
    return "\n".join(lines)

OUTREACH_TEMPLATES = {
    "super_active": "היי {name}, ראיתי שאתה ממש פעיל עם דוגרי. אשמח לשמוע מה עובד לך ומה אפשר לשפר",
    "consistently_active": "היי {name}, ראיתי שאתה מתעד באופן קבוע עם דוגרי. אשמח לשמוע מה עובד לך",
    "inconsistently_active": "היי {name}, ראיתי שאתה משתמש בדוגרי. אשמח לשמוע מה אפשר לעשות כדי שזה יהיה יותר קל",
    "stopped": "היי {name}, שמתי לב שלא התעדכנת כבר כמה ימים. הכל בסדר? אם יש משהו שאפשר לשפר אשמח לשמוע",
    "stuck_at_gate": "היי {name}, ראיתי שנרשמת לדוגרי אבל עדיין לא התחלת לתעד. צריך עזרה עם ההתחברות לבוט?",
}


def _get_admin_storage() -> AdminStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return AdminStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


@admin_bp.route("/")
@admin_required
def dashboard():
    storage = _get_admin_storage()

    # KPIs
    total_users = storage.get_total_users()
    total_signups = storage.get_total_signups()
    active_week = storage.get_active_this_week()
    funnel = storage.get_signup_funnel()

    # Charts
    dau = storage.get_dau_30_days()
    habits = storage.get_habit_adoption()
    hours = storage.get_activity_hours()
    churn = storage.get_churn_curve()

    # Hot leads
    super_active = storage.get_super_active_users()
    consistently_active = storage.get_consistently_active_users()
    inconsistently_active = storage.get_inconsistently_active_users()
    stopped = storage.get_stopped_users()
    stuck = storage.get_stuck_at_gate_users()

    # Pre-compute token tooltips for all leads
    for leads in [super_active, consistently_active, inconsistently_active, stopped, stuck]:
        for lead in leads:
            lead["tokens_tooltip"] = _format_tokens_tooltip(lead.get("tokens_used", {}))

    return render_template(
        "admin/dashboard.html",
        active_sub="dashboard",
        total_users=total_users,
        total_signups=total_signups,
        active_week=active_week,
        funnel=funnel,
        dau_json=json.dumps(dau),
        habits_json=json.dumps(habits),
        hours_json=json.dumps(hours),
        churn_json=json.dumps(churn),
        super_active=super_active,
        consistently_active=consistently_active,
        inconsistently_active=inconsistently_active,
        stopped=stopped,
        stuck=stuck,
        outreach_templates=OUTREACH_TEMPLATES,
        active_tab="admin",
    )


@admin_bp.route("/errors")
@admin_required
def errors():
    storage = _get_admin_storage()
    error_groups = storage.get_error_groups()
    daily_counts = storage.get_error_daily_counts()
    return render_template(
        "admin/errors.html",
        error_groups=error_groups,
        daily_counts_json=json.dumps(daily_counts, default=str),
        total_errors=sum(g["count"] for g in error_groups),
        unique_errors=len(error_groups),
        active_tab="admin",
        active_sub="errors",
    )


@admin_bp.route("/feature-requests")
@admin_required
def feature_requests():
    storage = _get_admin_storage()
    requests_list = storage.get_feature_requests()
    stats = storage.get_feature_request_stats()
    by_type = stats.get("by_type", {})
    return render_template(
        "admin/feature_requests.html",
        feature_requests=requests_list,
        total_requests=stats["total"],
        unique_users=stats["unique_users"],
        bugs=by_type.get("bug_report", 0),
        suggestions=by_type.get("feature_request", 0),
        habits=by_type.get("habit_of_interest", 0),
        knowledge_gaps=by_type.get("knowledge_gap", 0),
        active_tab="admin",
        active_sub="feature_requests",
    )


@admin_bp.route("/tokens")
@admin_required
def tokens():
    storage = _get_admin_storage()

    # Date range from query params, default last 30 days
    end_str = request.args.get("end", datetime.utcnow().strftime("%Y-%m-%d"))
    start_str = request.args.get("start", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))

    usage = storage.get_token_usage(start_str, end_str)
    totals = storage.get_token_totals(start_str, end_str)

    # Compute USD costs for totals
    totals_with_cost = {}
    grand_total_cost = 0.0
    grand_total_tokens = 0
    for model, counts in totals.items():
        pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
        cost = counts["prompt_tokens"] * pricing["input"] / 1_000_000 + counts["completion_tokens"] * pricing["output"] / 1_000_000
        total_tokens = counts["prompt_tokens"] + counts["completion_tokens"]
        totals_with_cost[model] = {
            "prompt_tokens": counts["prompt_tokens"],
            "completion_tokens": counts["completion_tokens"],
            "total_tokens": total_tokens,
            "cost": round(cost, 4),
        }
        grand_total_cost += cost
        grand_total_tokens += total_tokens

    return render_template(
        "admin/tokens.html",
        active_tab="admin",
        active_sub="tokens",
        start_date=start_str,
        end_date=end_str,
        usage_json=json.dumps(usage),
        totals=totals_with_cost,
        grand_total_cost=round(grand_total_cost, 4),
        grand_total_tokens=grand_total_tokens,
    )


SIMULATOR_EMAIL = "test@dugri.simulator"


def _get_dashboard_storage() -> DashboardStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


@admin_bp.route("/simulator")
@admin_required
def simulator():
    storage = _get_dashboard_storage()
    user = storage.get_user(SIMULATOR_EMAIL)
    if not user:
        storage.seed_test_user()
        user = storage.get_user(SIMULATOR_EMAIL)
    return render_template(
        "admin/simulator.html",
        active_tab="admin",
        active_sub="simulator",
        sim_user=user,
    )


@admin_bp.route("/simulator/state", methods=["GET"])
@admin_required
def simulator_get_state():
    storage = _get_dashboard_storage()
    user = storage.get_user(SIMULATOR_EMAIL)
    if not user:
        return jsonify({"error": "test user not found"}), 404
    user["_id"] = str(user["_id"])
    return jsonify(user)


@admin_bp.route("/simulator/state", methods=["POST"])
@admin_required
def simulator_update_state():
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400
    storage = _get_dashboard_storage()
    storage.update_user_raw(SIMULATOR_EMAIL, data)
    return jsonify({"ok": True})


@admin_bp.route("/simulator/reset", methods=["POST"])
@admin_required
def simulator_reset():
    storage = _get_dashboard_storage()
    user = storage.get_user(SIMULATOR_EMAIL)
    if not user:
        return jsonify({"error": "test user not found"}), 404

    now = datetime.now(timezone.utc).isoformat()
    fresh_toggle = {
        "status": "dormant",
        "revealed_at": None,
        "activated_at": None,
        "last_asked_at": None,
        "consecutive_unanswered": 0,
        "goal_status": "pending",
        "goal_value": None,
        "goal_remind_at": None,
        "goal_offered_at": None,
    }
    # Generate a signup token so /start {token} triggers the real linking flow
    import secrets
    signup_token = secrets.token_urlsafe(24)
    token_expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    # Clear activity logs BEFORE resetting telegram_user_id (delete_user_logs
    # needs the current tid to find entries in food_entries, sleep_logs, etc.)
    log_counts = storage.delete_user_logs(SIMULATOR_EMAIL)
    logger.info("Simulator reset: deleted logs %s", log_counts)

    reset_fields = {
        "toggles": {
            "sleep": {**fresh_toggle},
            "eating_window": {**fresh_toggle},
            "workouts": {**fresh_toggle},
            "self_care": {**fresh_toggle},
            "nutrition": {**fresh_toggle},
            "weekly_summary": {**fresh_toggle, "status": "active"},
        },
        "targets": {
            "calories": None, "protein": None,
            "sleep_time": None, "workouts_per_week": None,
            "weight_goal": None,
        },
        "eating_window": None,
        "subscription_status": "trial_pending",
        "trial_started_at": None,
        "telegram_user_id": None,
        "signup_session_token": signup_token,
        "signup_session_token_expires_at": token_expires,
        "recent_messages": [],
        "dashboard_intro_shown": False,
        "target_retry_done": False,
        "eating_window_retry_done": False,
        "name": None,
        "onboarding": {"name_collected": False, "habits": {}},
        "birth_year": None,
        "height_cm": None,
        "weight_kg": None,
        "gender": None,
        "feedback_steering_prompt": None,
        "last_feedback_offered_at": None,
        "discovered_patterns": [],
        "strikes": [],
        "banned_at": None,
        "gem_state": {
            "used_gem_ids": [],
            "cycle_number": 1,
            "last_delivered_at": None,
            "deliveries": [],
            "feedbacks": [],
            "threshold_adjustment": 0.0,
            "week_start_iso": None,
            "gem_delivered_this_week": False,
            "silent_week": False,
        },
        "re_engagement_stage": "none",
        "re_engagement_last_sent_at": None,
        "last_user_message_at": None,
        "trial_expiry_message_sent": False,
        "trial_expiry_at": None,
        "trial_end_acknowledged": False,
        "tokens_used": {},
        "self_care_activities": {},
    }
    ok = storage.update_user_raw(SIMULATOR_EMAIL, reset_fields)
    logger.info("Simulator reset: update_user_raw returned %s", ok)

    # Verify
    after = storage.get_user(SIMULATOR_EMAIL)
    msg_count = len(after.get("recent_messages", [])) if after else -1
    logger.info("Simulator reset: recent_messages after reset = %d", msg_count)

    return jsonify({"ok": True, "messages_after_reset": msg_count, "signup_token": signup_token})


@admin_bp.route("/simulator/clear-logs", methods=["POST"])
@admin_required
def simulator_clear_logs():
    storage = _get_dashboard_storage()
    counts = storage.delete_user_logs(SIMULATOR_EMAIL)
    return jsonify({"ok": True, "deleted": counts})


@admin_bp.route("/simulator/send", methods=["POST"])
@admin_required
def simulator_send():
    """Proxy a message to the bot's /internal/simulate endpoint."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    cfg = current_app.config["APP_CONFIG"]
    bot_url = cfg.get("bot_internal_url", "")
    secret = cfg.get("internal_secret", "")

    if not bot_url:
        return jsonify({"error": "bot_internal_url not configured"}), 500

    payload = {"email": SIMULATOR_EMAIL}
    if data.get("text"):
        payload["text"] = data["text"]
        if data.get("reply_to_message_id"):
            payload["reply_to_message_id"] = data["reply_to_message_id"]
            payload["reply_to_text"] = data.get("reply_to_text", "")
    elif data.get("callback_data"):
        payload["callback_data"] = data["callback_data"]
    else:
        return jsonify({"error": "text or callback_data required"}), 400

    try:
        resp = requests.post(
            f"{bot_url}/internal/simulate",
            json=payload,
            headers={"X-Internal-Secret": secret},
            timeout=30,
        )
        if resp.ok:
            return jsonify(resp.json())
        logger.error("Bot simulate error: %s %s", resp.status_code, resp.text)
        return jsonify({"error": "bot returned error", "status": resp.status_code}), 502
    except requests.Timeout:
        return jsonify({"error": "bot timeout"}), 504
    except Exception:
        logger.exception("Failed to reach bot simulate endpoint")
        return jsonify({"error": "bot unreachable"}), 502


SIMULATOR_TID = 999999999


@admin_bp.route("/simulator/history")
@admin_required
def simulator_history():
    """Return activity history for the simulator test user."""
    from api import format_activity_days

    storage = _get_dashboard_storage()

    # Ensure telegram_user_id is set so get_activity_history can query entries.
    # After a full reset telegram_user_id is temporarily None until /start links it.
    user = storage.get_user(SIMULATOR_EMAIL)
    if user and not user.get("telegram_user_id"):
        storage.update_user_raw(SIMULATOR_EMAIL, {"telegram_user_id": SIMULATOR_TID})

    today = date.today()
    start_date = today - timedelta(days=2)

    raw = storage.get_activity_history(SIMULATOR_EMAIL, start_date, today)
    days = format_activity_days(raw, start_date, today)

    return jsonify({"days": days})


@admin_bp.route("/simulator/hook-schedule")
@admin_required
def simulator_hook_schedule():
    """Return the current randomized hook fire times from the bot's hook_schedule collection."""
    storage = _get_dashboard_storage()
    doc = storage._db["hook_schedule"].find_one({"_id": "hook_schedule"})
    if not doc:
        return jsonify({"hooks": {}})
    doc.pop("_id", None)
    return jsonify({"hooks": doc})


@admin_bp.route("/simulator/tick", methods=["POST"])
@admin_required
def simulator_tick():
    """Proxy a scheduler tick to the bot's /internal/simulate-tick endpoint."""
    data = request.get_json() or {}
    fake_now = data.get("fake_now")
    if not fake_now:
        return jsonify({"error": "fake_now required"}), 400

    cfg = current_app.config["APP_CONFIG"]
    bot_url = cfg.get("bot_internal_url", "")
    secret = cfg.get("internal_secret", "")

    if not bot_url:
        return jsonify({"error": "bot_internal_url not configured"}), 500

    try:
        resp = requests.post(
            f"{bot_url}/internal/simulate-tick",
            json={"email": SIMULATOR_EMAIL, "fake_now": fake_now},
            headers={"X-Internal-Secret": secret},
            timeout=30,
        )
        if resp.ok:
            return jsonify(resp.json())
        logger.error("Bot simulate-tick error: %s %s", resp.status_code, resp.text)
        return jsonify({"error": "bot returned error", "status": resp.status_code}), 502
    except requests.Timeout:
        return jsonify({"error": "bot timeout"}), 504
    except Exception:
        logger.exception("Failed to reach bot simulate-tick endpoint")
        return jsonify({"error": "bot unreachable"}), 502


@admin_bp.route("/outreach", methods=["POST"])
@admin_required
def send_outreach():
    """Send a Telegram message from Dugri to a user, inviting them to chat with the founder."""
    data = request.get_json()
    if not data or not data.get("telegram_user_id"):
        return jsonify({"error": "missing telegram_user_id"}), 400

    cfg = current_app.config["APP_CONFIG"]
    bot_token = cfg.get("telegram_bot_token")
    founder_username = cfg.get("founder_telegram_username", "")
    if not bot_token:
        return jsonify({"error": "telegram_bot_token not configured"}), 500

    telegram_user_id = data["telegram_user_id"]
    user_name = data.get("name", "")

    greeting = f"היי {user_name}, " if user_name else "היי, "
    text = (
        f"{greeting}"
        "שי, היזם של דוגרי, רוצה להתחבר איתך כדי ללמוד על שביעות הרצון שלך מדוגרי. "
        "אם בא לך, לחצ/י על הכפתור למטה ותפתח שיחה ישירות איתו 👇"
    )

    payload = {
        "chat_id": telegram_user_id,
        "text": text,
    }
    if founder_username:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[
                {"text": "💬 פתח שיחה עם שי", "url": f"https://t.me/{founder_username}"},
            ]],
        })

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            return jsonify({"ok": True})
        logger.error("Telegram API error: %s", resp.text)
        return jsonify({"error": "telegram send failed"}), 502
    except Exception:
        logger.exception("Failed to send outreach message")
        return jsonify({"error": "telegram send failed"}), 502
