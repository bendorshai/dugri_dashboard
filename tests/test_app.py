from __future__ import annotations

import json
import pytest

from app import create_app, load_config


class TestLoadConfig:
    def test_loads_from_file(self, tmp_path, monkeypatch):
        cfg = {"flask": {"secret_key": "s"}, "mongodb": {"uri": "x", "db_name": "y"}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr("app.CONFIG_PATH", path)
        result = load_config()
        assert result["flask"]["secret_key"] == "s"

    def test_loads_from_env_var(self, tmp_path, monkeypatch):
        cfg = {"flask": {"secret_key": "from-env"}}
        monkeypatch.setenv("DASHBOARD_CONFIG_JSON", json.dumps(cfg))
        result = load_config()
        assert result["flask"]["secret_key"] == "from-env"

    def test_env_var_takes_precedence(self, tmp_path, monkeypatch):
        file_cfg = {"flask": {"secret_key": "from-file"}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(file_cfg), encoding="utf-8")
        monkeypatch.setattr("app.CONFIG_PATH", path)
        env_cfg = {"flask": {"secret_key": "from-env"}}
        monkeypatch.setenv("DASHBOARD_CONFIG_JSON", json.dumps(env_cfg))
        result = load_config()
        assert result["flask"]["secret_key"] == "from-env"

    def test_exits_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.CONFIG_PATH", tmp_path / "missing.json")
        monkeypatch.delenv("DASHBOARD_CONFIG_JSON", raising=False)
        with pytest.raises(SystemExit):
            load_config()


class TestCreateApp:
    def test_app_created(self, app):
        assert app is not None

    def test_landing_page_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
