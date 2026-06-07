from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import requests
from flask import Blueprint, render_template, current_app, request, jsonify

from admin_storage import AdminStorage
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
    return render_template(
        "admin/feature_requests.html",
        feature_requests=requests_list,
        total_requests=stats["total"],
        unique_users=stats["unique_users"],
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
