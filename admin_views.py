from __future__ import annotations

import json
import logging

from flask import Blueprint, render_template, current_app

from admin_storage import AdminStorage
from auth import admin_required

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

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

    return render_template(
        "admin/dashboard.html",
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
