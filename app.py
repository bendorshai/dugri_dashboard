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
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 300  # 5 min cache for static files
    app.config["APP_CONFIG"] = config

    from auth import auth_bp
    from onboarding import onboarding_bp
    from dashboard_views import dashboard_bp
    from api import api_bp
    from admin_views import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_admin_flag():
        from flask import session as s
        admin_emails = config.get("admin_emails", [])
        return {"is_admin": s.get("user_email") in admin_emails}

    @app.after_request
    def set_cache_headers(response):
        if response.content_type and "text/html" in response.content_type:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.route("/")
    def landing():
        from flask import render_template, request, session, url_for
        import hebrew_strings as hs

        contact_email = config.get("contact_email", "")
        base_url = request.url_root.rstrip("/")
        og_image_url = base_url + url_for("static", filename="images/1.png")
        og_page_url = base_url + "/"

        return render_template(
            "landing.html",
            contact_email=contact_email,
            hs=hs,
            og_image_url=og_image_url,
            og_page_url=og_page_url,
        )

    @app.route("/prev-landing")
    def prev_landing():
        from flask import render_template, request, url_for
        import hebrew_strings as hs

        contact_email = config.get("contact_email", "")
        base_url = request.url_root.rstrip("/")
        og_image_url = base_url + url_for("static", filename="images/1.png")
        og_page_url = base_url + "/"

        return render_template(
            "prev_landing.html",
            contact_email=contact_email,
            hs=hs,
            og_image_url=og_image_url,
            og_page_url=og_page_url,
        )

    @app.route("/welcome")
    def welcome():
        from flask import render_template, redirect, url_for, session
        import hebrew_strings as hs

        if "user_email" not in session or "signup_session_token" not in session:
            return redirect(url_for("landing"))

        bot_username = config.get("dugri_bot_username", "")
        signup_token = session["signup_session_token"]
        user_name = session.get("user_name", "")
        deep_link = f"https://t.me/{bot_username}?start={signup_token}"

        return render_template(
            "welcome.html",
            deep_link=deep_link,
            user_name=user_name,
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

    @app.errorhandler(404)
    def page_not_found(e):
        from flask import render_template
        bot_username = config.get("dugri_bot_username", "skinny_slimmy_bot")
        return render_template("404.html", bot_username=bot_username), 404

    # Seed simulator test user
    mongo_cfg = config.get("mongodb", {})
    if mongo_cfg.get("uri"):
        try:
            from storage import DashboardStorage
            storage = DashboardStorage(uri=mongo_cfg["uri"], db_name=mongo_cfg["db_name"])
            if storage.seed_test_user():
                logger.info("Simulator test user seeded: test@dugri.simulator")
        except Exception:
            logger.exception("Failed to seed simulator test user")

    return app


if __name__ == "__main__":
    application = create_app()
    port = int(os.environ.get("PORT", 5000))
    debug = not os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    application.run(host="0.0.0.0", port=port, debug=debug)
