from __future__ import annotations

import json
import os
import pytest

from app import create_app


# Allow pointing tests at a reachable Mongo (e.g. the Railway public proxy) via
# env var, mirroring the bot's E2E_MONGO_URI convention. Falls back to localhost.
# The db name stays "test_health_tracker" so real users are never touched.
_TEST_MONGO_URI = os.environ.get("DASHBOARD_TEST_MONGO_URI", "mongodb://localhost:27017")

SAMPLE_CONFIG = {
    "flask": {"secret_key": "test-secret", "debug": True},
    "google_oauth": {"client_id": "test-id", "client_secret": "test-secret"},
    "openai": {"api_key": "test-openai-key"},
    "mongodb": {"uri": _TEST_MONGO_URI, "db_name": "test_health_tracker"},
    "dugri_bot_username": "TestDugriBot",
    "contact_email": "test@dugri.co",
    "admin_emails": ["admin@test.com"],
    "green_invoice": {
        "sandbox": {"api_id": "sandbox-gi-id", "api_secret": "sandbox-gi-secret"},
        "realdeal": {"api_id": "realdeal-gi-id", "api_secret": "realdeal-gi-secret"},
        "subscription_price_ils": 1,
    },
}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG), encoding="utf-8")
    monkeypatch.setattr("app.CONFIG_PATH", config_file)
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()
