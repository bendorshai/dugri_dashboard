"""Integration tests for the new single-page onboarding flow."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def _login(client, token="test-token-abc"):
    with client.session_transaction() as sess:
        sess["user_email"] = "test@example.com"
        sess["user_name"] = "Test User"
        sess["signup_session_token"] = token


class TestLandingPage:
    def test_landing_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_landing_has_consent_checkboxes(self, client):
        resp = client.get("/")
        data = resp.data.decode("utf-8")
        assert "consent-terms" in data
        assert "consent-medical" in data
        assert "consent-marketing" not in data

    def test_landing_has_logo(self, client):
        resp = client.get("/")
        assert b"1.png" in resp.data

    def test_landing_has_google_login_link(self, client):
        resp = client.get("/")
        assert b"/auth/login" in resp.data

    def test_landing_has_footer_links(self, client):
        resp = client.get("/")
        data = resp.data.decode("utf-8")
        assert "/terms" in data
        assert "/privacy" in data
        assert "/about" in data


class TestSignupPage:
    FAQ_LINES = [
        "כותבים או מצלמים לדוגרי את מה שאתם אוכלים",
        "דוגרי עוקב ומכניס אתכם לעניינים לאט לאט",
        "תנו לדוגרי חודש והוא כבר יקלוט אתכם בקטע מפתיע",
    ]
    TITLE = "סוף סוף להיות על זה"
    KICKER = "14 יום ניסיון. בלי כרטיס אשראי."

    def test_signup_returns_200(self, client):
        resp = client.get("/signup")
        assert resp.status_code == 200

    def test_signup_has_faq_lines(self, client):
        data = client.get("/signup").data.decode("utf-8")
        for line in self.FAQ_LINES:
            assert line in data

    def test_signup_faq_between_title_and_kicker(self, client):
        # Order must be: title -> micro-FAQ -> trial kicker -> checkboxes
        data = client.get("/signup").data.decode("utf-8")
        title_i = data.index(self.TITLE)
        faq_i = data.index(self.FAQ_LINES[0])
        kicker_i = data.index(self.KICKER)
        consents_i = data.index("signup-consents")
        assert title_i < faq_i < kicker_i < consents_i

    def test_signup_kicker_moved_after_title(self, client):
        # The trial line now sits after the title, not before it.
        data = client.get("/signup").data.decode("utf-8")
        assert data.index(self.TITLE) < data.index(self.KICKER)


class TestWelcomePage:
    def test_welcome_shows_telegram_link(self, client):
        _login(client)
        resp = client.get("/welcome")
        data = resp.data.decode("utf-8")
        assert "t.me/TestDugriBot" in data
        assert "test-token-abc" in data

    def test_welcome_shows_user_name(self, client):
        _login(client)
        resp = client.get("/welcome")
        data = resp.data.decode("utf-8")
        assert "Test User" in data

    def test_welcome_has_logo(self, client):
        _login(client)
        resp = client.get("/welcome")
        assert b"1.png" in resp.data

    def test_welcome_redirects_without_session(self, client):
        resp = client.get("/welcome")
        assert resp.status_code == 302

    def test_welcome_redirects_without_token(self, client):
        with client.session_transaction() as sess:
            sess["user_email"] = "test@example.com"
            # No signup_session_token
        resp = client.get("/welcome")
        assert resp.status_code == 302

    def test_welcome_shows_home_screen_tip(self, client):
        _login(client)
        resp = client.get("/welcome")
        data = resp.data.decode("utf-8")
        assert "טיפ שעושה את כל ההבדל" in data
        assert "אנדרואיד" in data
        assert "אייפון" in data

    def test_welcome_protip_above_button(self, client):
        # The Pro-Tip section must render above the Telegram CTA button.
        _login(client)
        data = client.get("/welcome").data.decode("utf-8")
        assert data.index("tip-section") < data.index("welcome-cta")

    def test_welcome_intro_asks_how_to_add_icon(self, client):
        _login(client)
        data = client.get("/welcome").data.decode("utf-8")
        assert "איך לשים את דוגרי כאייקון נפרד בפלאפון?" in data
        # Old phrasing is gone.
        assert "עובד הכי טוב כשהוא נגיש מהמסך הראשי" not in data


class TestLegalPages:
    def test_terms_page_renders(self, client):
        resp = client.get("/terms")
        assert resp.status_code == 200
        assert "תנאי שימוש".encode() in resp.data

    def test_terms_has_medical_disclaimer(self, client):
        resp = client.get("/terms")
        assert "הצהרה רפואית".encode() in resp.data

    def test_privacy_page_renders(self, client):
        resp = client.get("/privacy")
        assert resp.status_code == 200
        assert "מדיניות פרטיות".encode() in resp.data

    def test_privacy_has_data_collection_section(self, client):
        resp = client.get("/privacy")
        assert "המידע שאנחנו אוספים".encode() in resp.data

    def test_about_page_renders(self, client):
        resp = client.get("/about")
        assert resp.status_code == 200
        assert "מי עומד מאחורי דוגרי".encode() in resp.data


class TestRegenerateBotLink:
    @patch("api.DashboardStorage")
    def test_regenerate_returns_deep_link(self, mock_storage_cls, client):
        mock_storage = MagicMock()
        mock_storage.regenerate_signup_session_token.return_value = "new-token-xyz"
        mock_storage_cls.return_value = mock_storage

        _login(client)
        resp = client.post("/api/regenerate-bot-link")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "new-token-xyz" in data["deep_link"]
        assert "TestDugriBot" in data["deep_link"]
        assert data["token"] == "new-token-xyz"

    def test_regenerate_requires_login(self, client):
        resp = client.post("/api/regenerate-bot-link")
        assert resp.status_code == 302  # redirected to login
