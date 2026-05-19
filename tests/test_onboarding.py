"""Tests for the legacy onboarding redirect stub."""
from __future__ import annotations


def _login(client):
    with client.session_transaction() as sess:
        sess["user_email"] = "test@example.com"
        sess["user_name"] = "Test"


class TestOnboardingRedirects:
    def test_step1_redirects_to_landing(self, client):
        resp = client.get("/onboarding/step/1")
        assert resp.status_code == 302
        assert "/" in resp.headers["Location"]

    def test_step4_redirects_to_landing(self, client):
        resp = client.get("/onboarding/step/4")
        assert resp.status_code == 302

    def test_post_redirects_to_landing(self, client):
        resp = client.post("/onboarding/step/1", data={"birth_year": "1990"})
        assert resp.status_code == 302

    def test_invalid_step_redirects(self, client):
        resp = client.get("/onboarding/step/99")
        assert resp.status_code == 302
