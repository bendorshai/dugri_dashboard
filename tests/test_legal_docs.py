"""Regression tests for the 2026-07 legal-docs rewrite (Terms + Privacy).

These lock in the decisions from
`plans/2026-07-09-legal-docs-review-and-edit-plan.md`. Each assertion maps to a
finding in that plan. They are pure render/unit tests - no MongoDB needed.

Expected behavior (source of truth):
- H1  : contact info ALWAYS renders (no `{% if contact_email %}` gate); a missing
        config key falls back to support@dugri.life, never a blank contract.
- H7/R2-01 : both docs print a single-sourced "גרסה N · בתוקף מ-<date>"; the same
        integer N is frozen into consents.doc_version at signup.
- H10 : no "כולל מע\"מ" anywhere (עוסק פטור); operator name + address rendered.
- H11 : ער"ן (1201) crisis signposting present in Terms.
- H9  : severability clause present in Terms.
- R2-15 : no marketing clause in either doc.
- C3  : Privacy acknowledges special-sensitivity health data.
- M10 : Privacy no longer asserts OpenAI "does not train on your data".
- H3  : Privacy discloses internal use incl. conversation content.
"""
from __future__ import annotations

import json

import pytest

from app import create_app
from hebrew_strings import DOC_VERSION, DOC_VERSION_DATE


def _config(**overrides):
    cfg = {
        "flask": {"secret_key": "test-secret", "debug": True},
        "google_oauth": {"client_id": "x", "client_secret": "y"},
        "openai": {"api_key": "k"},
        "mongodb": {"uri": "mongodb://localhost:27017", "db_name": "test_db"},
        "dugri_bot_username": "TestDugriBot",
        "contact_email": "test@dugri.co",
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture()
def client_with(monkeypatch):
    def _make(**cfg_overrides):
        app = create_app(config=_config(**cfg_overrides))
        app.config["TESTING"] = True
        return app.test_client()
    return _make


class TestVersioning:
    def test_terms_shows_version_and_effective_date(self, client_with):
        data = client_with().get("/terms").data.decode("utf-8")
        assert f"גרסה {DOC_VERSION}" in data
        assert DOC_VERSION_DATE in data

    def test_privacy_shows_version_and_effective_date(self, client_with):
        data = client_with().get("/privacy").data.decode("utf-8")
        assert f"גרסה {DOC_VERSION}" in data
        assert DOC_VERSION_DATE in data

    def test_build_consents_freezes_integer_doc_version(self, client_with):
        # R2-01: consents.doc_version is a static integer frozen at consent time.
        app = create_app(config=_config())
        from auth import _build_consents
        with app.test_request_context():
            from flask import session
            session["pending_consents"] = {"terms": True, "medical": True, "marketing": False}
            consents = _build_consents()
        assert consents["doc_version"] == DOC_VERSION
        assert isinstance(consents["doc_version"], int)


class TestContactAlwaysRenders:
    def test_terms_contact_falls_back_when_config_missing(self, client_with):
        # H1: even with no contact_email configured, the contract must not blank
        # the contact block - it falls back to the hard-coded support address.
        client = client_with(contact_email="")
        data = client.get("/terms").data.decode("utf-8")
        assert "support@dugri.life" in data

    def test_privacy_contact_falls_back_when_config_missing(self, client_with):
        client = client_with(contact_email="")
        data = client.get("/privacy").data.decode("utf-8")
        assert "support@dugri.life" in data

    def test_terms_renders_operator_identity(self, client_with):
        data = client_with().get("/terms").data.decode("utf-8")
        assert "שי בן-דור מאיר" in data
        assert "הזית 28ה, זכרון יעקב" in data


class TestNoVat:
    def test_terms_has_no_vat_wording(self, client_with):
        # H10: עוסק פטור - never "כולל מע\"מ".
        data = client_with().get("/terms").data.decode("utf-8")
        assert 'מע"מ' not in data
        assert "47 ₪" in data


class TestNoMarketing:
    def test_terms_has_no_marketing_clause(self, client_with):
        # R2-15: marketing dropped entirely.
        data = client_with().get("/terms").data.decode("utf-8")
        assert "תקשורת שיווקית" not in data

    def test_privacy_has_no_marketing_clause(self, client_with):
        data = client_with().get("/privacy").data.decode("utf-8")
        assert "תקשורת שיווקית" not in data
        assert "הסכמה נפרדת" not in data


class TestSafetyAndEnforceability:
    def test_terms_has_eran_crisis_signposting(self, client_with):
        # H11: named crisis resource ער"ן + hotline number.
        data = client_with().get("/terms").data.decode("utf-8")
        assert 'ער"ן' in data
        assert "1201" in data

    def test_terms_has_severability_clause(self, client_with):
        # H9.
        data = client_with().get("/terms").data.decode("utf-8")
        assert "ביטול חלקי" in data

    def test_terms_liability_cap_excludes_bodily_harm(self, client_with):
        # C2: the economic-loss cap must NOT cover נזקי גוף/נפש.
        data = client_with().get("/terms").data.decode("utf-8")
        assert "לנזקי גוף או נפש" in data


class TestPrivacySensitiveData:
    def test_privacy_acknowledges_special_sensitivity(self, client_with):
        # C3.
        data = client_with().get("/privacy").data.decode("utf-8")
        assert "רגישות מיוחדת" in data

    def test_privacy_drops_openai_training_claim(self, client_with):
        # M10: no absolute "OpenAI does not train on your data" claim.
        data = client_with().get("/privacy").data.decode("utf-8")
        assert "אימון מודליה" not in data
        assert "לאימון המודלים" not in data

    def test_privacy_discloses_internal_use_of_conversations(self, client_with):
        # H3/R2-09.
        data = client_with().get("/privacy").data.decode("utf-8")
        assert "תוכן השיחות" in data
