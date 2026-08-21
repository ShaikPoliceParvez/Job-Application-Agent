from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.gmail import service
from backend.app.main import app


def test_oauth_state_is_loaded_from_persistent_store(monkeypatch):
    stored = {}
    settings.google_client_id = "client-id"
    settings.google_client_secret = "client-secret"
    settings.google_redirect_uri = "https://example.com/auth/gmail/callback"

    class Credentials:
        token = "access-token"
        refresh_token = "refresh-token"
        token_uri = "https://oauth2.googleapis.com/token"
        expiry = None

    class Flow:
        def __init__(self, state=None):
            self.state = state
            self.redirect_uri = ""
            self.credentials = Credentials()

        @classmethod
        def from_client_config(cls, config, scopes, state=None):
            return cls(state)

        def authorization_url(self, **kwargs):
            return "https://accounts.google.com/o/oauth2/auth", "persistent-state"

        def fetch_token(self, code):
            assert code == "authorization-code"

    monkeypatch.setattr("google_auth_oauthlib.flow.Flow", Flow)
    monkeypatch.setattr(settings, "upstash_redis_rest_url", "https://redis.example.com")
    monkeypatch.setattr(settings, "upstash_redis_rest_token", "redis-token")
    monkeypatch.setattr(service, "_redis_set", lambda key, value, ttl=None: stored.update(key=key, data=value, ttl=ttl))
    monkeypatch.setattr(service, "_redis_get", lambda key: __import__("json").dumps(stored["data"]))
    monkeypatch.setattr(service, "_redis_delete", lambda key: None)
    monkeypatch.setattr(service, "gmail_account", lambda: "candidate@example.com")

    service.authorization_url()
    assert service.finish_authorization("authorization-code", "persistent-state") == "candidate@example.com"
    assert stored["key"] == service.GMAIL_CREDENTIALS_KEY
    assert stored["data"]["token"] == "access-token"
    assert stored["data"]["refresh_token"] == "refresh-token"
    assert stored["ttl"] is None
    assert "client_secret" not in stored["data"]


def test_oauth_state_uses_required_key_and_ttl(monkeypatch):
    captured = {}
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "https://example.com/callback")

    class Flow:
        @classmethod
        def from_client_config(cls, config, scopes, state=None):
            instance = cls()
            instance.redirect_uri = ""
            return instance

        def authorization_url(self, **kwargs):
            return "https://accounts.google.com", "state-value"

    monkeypatch.setattr("google_auth_oauthlib.flow.Flow", Flow)
    monkeypatch.setattr(service, "_redis_set", lambda key, value, ttl=None: captured.update(key=key, value=value, ttl=ttl))
    service.authorization_url()

    assert captured["key"] == "job-agent:gmail:oauth-state"
    assert captured["ttl"] == 600


def test_raw_resume_attachment_does_not_require_attachment_path():
    message = service.build_mime_message(
        "hr@example.com",
        "Application",
        "Dear HR Team,\n\nPlease find my resume attached.",
        attachment_bytes=b"%PDF-test",
        attachment_source_name="original-resume.pdf",
    )

    assert message.get_payload(1).get_filename() == "original-resume.pdf"


def test_gmail_send_accepts_browser_resume_without_disk_resume(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "email_send_mode", "mock")
    monkeypatch.setattr(settings, "log_dir", tmp_path / "logs")
    monkeypatch.setattr("backend.app.main.load_candidate_context", lambda: ({}, "", ""))

    response = TestClient(app).post(
        "/gmail/send",
        data={"recipient": "hr@example.com", "subject": "Application", "body": "Please review."},
        files={"file": ("original.pdf", b"%PDF-test", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["attachment_name"] == "Candidate_resume.pdf"
    assert not list(tmp_path.glob("**/original.pdf"))


def test_resume_upload_ocr_is_in_memory(monkeypatch):
    captured = {}

    def fake_ocr(raw, filename, content_type):
        captured.update(raw=raw, filename=filename, content_type=content_type)
        return {"text": "Candidate resume", "confidence": 0.99, "blocks": []}

    monkeypatch.setattr("backend.app.main.extract_ocr_text", fake_ocr)
    response = TestClient(app).post(
        "/resume",
        files={"file": ("resume.pdf", b"%PDF-test", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Candidate resume"
    assert captured == {
        "raw": b"%PDF-test",
        "filename": "resume.pdf",
        "content_type": "application/pdf",
    }


def test_env_example_contains_only_current_variables():
    expected = {
        "PADDLEOCR_API_URL", "PADDLEOCR_ACCESS_TOKEN", "GROQ_API_KEY", "GROQ_MODEL",
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
        "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
    }
    names = {
        line.split("=", 1)[0]
        for line in Path(".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert names == expected


def test_credential_data_excludes_secrets():
    class Credentials:
        token = "access-token"
        refresh_token = "refresh-token"
        token_uri = "https://oauth2.googleapis.com/token"
        expiry = datetime.now(timezone.utc)
        client_secret = "must-not-be-stored"

    data = service._credential_data(Credentials())
    assert set(data) == {"token", "refresh_token", "token_uri", "expiry"}
    assert "client_secret" not in data