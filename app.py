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
        from flask import render_template
        return render_template("landing.html")

    return app


if __name__ == "__main__":
    application = create_app()
    port = int(os.environ.get("PORT", 5000))
    debug = not os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    application.run(host="0.0.0.0", port=port, debug=debug)
