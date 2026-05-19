from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from flask import Flask

CONFIG_PATH = Path(__file__).parent / "config" / "config.json"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _parse_last_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    text = text.strip()
    result = None
    pos = 0
    while pos < len(text):
        try:
            obj, end = decoder.raw_decode(text, pos)
            result = obj
            pos = end
        except json.JSONDecodeError:
            pos += 1
    if result is None:
        raise json.JSONDecodeError("No valid JSON found", text, 0)
    return result


def load_config() -> dict:
    env_json = os.environ.get("DASHBOARD_CONFIG_JSON")
    if env_json:
        logger.info("Loading config from environment variable")
        try:
            result = json.loads(env_json)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        return _parse_last_json(env_json)
    if not CONFIG_PATH.exists():
        logger.error("Config file not found: %s", CONFIG_PATH)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return _parse_last_json(f.read())


def create_app(config: dict | None = None) -> Flask:
    if config is None:
        config = load_config()

    app = Flask(__name__)
    app.secret_key = config.get("flask", {}).get("secret_key", "change-me")
    app.config["DEBUG"] = config.get("flask", {}).get("debug", False)
    app.config["APP_CONFIG"] = config

    from auth import auth_bp
    from onboarding import onboarding_bp
    from dashboard_views import dashboard_bp
    from api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)

    @app.route("/")
    def landing():
        from flask import render_template, request, session
        import hebrew_strings as hs

        post_signup = request.args.get("post_signup") == "1" and "user_email" in session
        bot_username = config.get("dugri_bot_username", "")
        contact_email = config.get("contact_email", "")
        signup_token = session.get("signup_session_token", "")
        user_name = session.get("user_name", "")
        deep_link = f"https://t.me/{bot_username}?start={signup_token}" if signup_token else ""

        return render_template(
            "landing.html",
            post_signup=post_signup,
            deep_link=deep_link,
            user_name=user_name,
            contact_email=contact_email,
            bot_username=bot_username,
            hs=hs,
        )

    @app.route("/terms")
    def terms():
        from flask import render_template
        import hebrew_strings as hs
        contact_email = config.get("contact_email", "")
        return render_template("terms.html", hs=hs, contact_email=contact_email)

    @app.route("/privacy")
    def privacy():
        from flask import render_template
        import hebrew_strings as hs
        contact_email = config.get("contact_email", "")
        return render_template("privacy.html", hs=hs, contact_email=contact_email)

    @app.route("/about")
    def about():
        from flask import render_template
        import hebrew_strings as hs
        return render_template("about.html", hs=hs)

    return app


if __name__ == "__main__":
    application = create_app()
    port = int(os.environ.get("PORT", 5000))
    debug = not os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    application.run(host="0.0.0.0", port=port, debug=debug)
