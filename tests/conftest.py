from __future__ import annotations

import json
import pytest

from app import create_app


SAMPLE_CONFIG = {
    "flask": {"secret_key": "test-secret", "debug": True},
    "google_oauth": {"client_id": "test-id", "client_secret": "test-secret"},
    "openai": {"api_key": "test-openai-key"},
    "mongodb": {"uri": "mongodb://localhost:27017", "db_name": "test_health_tracker"},
    "dugri_bot_username": "TestDugriBot",
    "contact_email": "test@dugri.co",
    "admin_emails": ["admin@test.com"],
    "green_invoice": {
        "api_id": "test-gi-id",
        "api_secret": "test-gi-secret",
        "sandbox": True,
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
