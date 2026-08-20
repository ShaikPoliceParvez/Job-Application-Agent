import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from backend.app.config import settings
from backend.app.models.ollama import OllamaError, OllamaModel


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_cloud_request_uses_server_side_bearer_auth(monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "cloud")
    monkeypatch.setattr(settings, "ollama_api_key", "secret-value")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.headers)
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse({"response": "Hello."})

    with patch("backend.app.models.ollama.urlopen", side_effect=fake_urlopen):
        assert OllamaModel("cloud-model", "https://ollama.com").generate("Greet") == "Hello."

    assert captured["headers"]["Authorization"] == "Bearer secret-value"
    assert captured["url"] == "https://ollama.com/api/generate"


def test_cloud_requires_api_key_without_making_request(monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "cloud")
    monkeypatch.setattr(settings, "ollama_api_key", None)
    with pytest.raises(OllamaError, match="OLLAMA_API_KEY is not configured"):
        OllamaModel("cloud-model").generate("Greet")


def test_local_request_does_not_send_bearer_auth(monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "local")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.headers)
        return FakeResponse({"response": "Hello."})

    with patch("backend.app.models.ollama.urlopen", side_effect=fake_urlopen):
        assert OllamaModel("local-model", "http://localhost:11434").generate("Greet") == "Hello."

    assert "Authorization" not in captured["headers"]


def test_invalid_cloud_credentials_are_not_retried(monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "cloud")
    monkeypatch.setattr(settings, "ollama_api_key", "secret-value")
    error = HTTPError("https://ollama.com/api/generate", 401, "Unauthorized", {}, BytesIO())
    with patch("backend.app.models.ollama.urlopen", side_effect=error) as request:
        with pytest.raises(OllamaError, match="authentication failed"):
            OllamaModel("cloud-model").generate("Greet")
    request.assert_called_once()