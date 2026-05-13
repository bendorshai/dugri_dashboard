from __future__ import annotations

import logging
import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint, redirect, url_for, session, current_app, request, flash,
)

from storage import DashboardStorage
from key_generator import generate_bot_key

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_email" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def _get_storage() -> DashboardStorage:
    cfg = current_app.config["APP_CONFIG"]
    mongo_cfg = cfg["mongodb"]
    return DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])


def _get_oauth_config() -> dict:
    return current_app.config["APP_CONFIG"]["google_oauth"]


@auth_bp.route("/login")
def login():
    oauth_cfg = _get_oauth_config()
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    params = {
        "client_id": oauth_cfg["client_id"],
        "redirect_uri": url_for("auth.callback", _external=True),
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
        flash("ההתחברות נכשלה. נסה שוב.", "error")
        return redirect(url_for("landing"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or state != session.pop("oauth_state", None):
        flash("ההתחברות נכשלה. נסה שוב.", "error")
        return redirect(url_for("landing"))

    oauth_cfg = _get_oauth_config()

    # Exchange code for token
    token_resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": oauth_cfg["client_id"],
        "client_secret": oauth_cfg["client_secret"],
        "redirect_uri": url_for("auth.callback", _external=True),
        "grant_type": "authorization_code",
    }, timeout=10)

    if token_resp.status_code != 200:
        logger.error("Token exchange failed: %s", token_resp.text)
        flash("ההתחברות נכשלה. נסה שוב.", "error")
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
        flash("ההתחברות נכשלה. נסה שוב.", "error")
        return redirect(url_for("landing"))

    userinfo = userinfo_resp.json()
    email = userinfo["email"]
    name = userinfo.get("name", "")

    # Create or get user
    storage = _get_storage()
    user = storage.get_user(email)
    if user is None:
        cfg = current_app.config["APP_CONFIG"]
        bot_key = generate_bot_key(email, cfg["bot_key_salt"])
        user = storage.create_user(email, name)
        storage.update_user_profile(email, {"bot_key": bot_key})

    session["user_email"] = email
    session["user_name"] = name

    if not user.get("onboarding_complete"):
        return redirect(url_for("onboarding.step", step_num=1))

    return redirect(url_for("dashboard_views.goals"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))
