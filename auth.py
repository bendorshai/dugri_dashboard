from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint, redirect, url_for, session, current_app, request, flash,
)

from storage import DashboardStorage
from hebrew_strings import ERROR_MISSING_CONSENT, ERROR_OAUTH_FAILED, DOC_VERSION

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_email" not in session:
            session["redirect_after_login"] = request.path
            return redirect(url_for("auth.login", returning="1"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        admin_emails = current_app.config["APP_CONFIG"].get("admin_emails", [])
        if session["user_email"] not in admin_emails:
            from flask import abort
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _get_storage() -> DashboardStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


def _get_oauth_config() -> dict:
    return current_app.config["APP_CONFIG"]["google_oauth"]


def _build_consents() -> dict:
    """Build a consents dict from session-stored pending consents."""
    now = datetime.now(timezone.utc).isoformat()
    pending = session.get("pending_consents", {})
    marketing = pending.get("marketing", False)
    return {
        "terms_accepted_at": now,
        "privacy_accepted_at": now,
        "medical_disclaimer_accepted_at": now,
        "marketing_opt_in": marketing,
        "marketing_opt_in_at": now if marketing else None,
        "doc_version": DOC_VERSION,
    }


@auth_bp.route("/login")
def login():
    # Read consent params from signup form (terms + medical required)
    terms = request.args.get("terms")
    medical = request.args.get("medical")
    returning = request.args.get("returning")

    # For returning users (session expired or explicit returning flag), skip consent check
    is_returning = "user_email" in session or returning == "1"

    if not is_returning:
        if not terms or not medical:
            flash(ERROR_MISSING_CONSENT, "error")
            return redirect(url_for("landing"))

        session["pending_consents"] = {
            "terms": True,
            "medical": True,
            "marketing": False,
        }

    oauth_cfg = _get_oauth_config()
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    redirect_uri = url_for("auth.callback", _external=True, _scheme="https")

    params = {
        "client_id": oauth_cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@auth_bp.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        logger.warning("OAuth error: %s", error)
        flash(ERROR_OAUTH_FAILED, "error")
        return redirect(url_for("landing"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or state != session.pop("oauth_state", None):
        flash(ERROR_OAUTH_FAILED, "error")
        return redirect(url_for("landing"))

    oauth_cfg = _get_oauth_config()

    # Exchange code for token
    token_resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": oauth_cfg["client_id"],
        "client_secret": oauth_cfg["client_secret"],
        "redirect_uri": url_for("auth.callback", _external=True, _scheme="https"),
        "grant_type": "authorization_code",
    }, timeout=10)

    if token_resp.status_code != 200:
        logger.error("Token exchange failed: %s", token_resp.text)
        flash(ERROR_OAUTH_FAILED, "error")
        return redirect(url_for("landing"))

    access_token = token_resp.json().get("access_token")

    # Get user info
    userinfo_resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )

    if userinfo_resp.status_code != 200:
        logger.error("Userinfo fetch failed: %s", userinfo_resp.text)
        flash(ERROR_OAUTH_FAILED, "error")
        return redirect(url_for("landing"))

    userinfo = userinfo_resp.json()
    email = userinfo["email"]
    name = userinfo.get("name", "")
    photo_url = userinfo.get("picture")

    storage = _get_storage()
    user = storage.get_user(email)

    if user is None:
        # New user — consents required
        pending = session.pop("pending_consents", None)
        if not pending or not pending.get("terms") or not pending.get("medical"):
            flash(ERROR_MISSING_CONSENT, "error")
            return redirect(url_for("landing"))

        consents = _build_consents()
        user = storage.create_user(email, name, photo_url=photo_url, consents=consents)
    else:
        # Returning user — update photo if we got a new one
        if photo_url and photo_url != user.get("photo_url"):
            storage.update_user_profile(email, {"photo_url": photo_url})

    session["user_email"] = email
    session["user_name"] = name

    # Redirect to original page if user was trying to reach a specific route
    redirect_target = session.pop("redirect_after_login", None)

    # Returning user with telegram linked → dashboard
    if user.get("telegram_user_id"):
        return redirect(redirect_target or url_for("dashboard_views.home"))

    # Generate fresh signup session token for Telegram deep link
    token = storage.regenerate_signup_session_token(email)
    session["signup_session_token"] = token

    return redirect(redirect_target or url_for("welcome"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))
