"""Server-side Groq chat-completions adapter."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.config import settings


class GroqError(RuntimeError):
    """Raised when Groq cannot complete a generation."""


class GroqModel:
    def __init__(self, model: str | None = None):
        self.model = model or settings.groq_model

    def _request(self, prompt: str, *, stream: bool, format: str | None, options: dict[str, Any] | None):
        if not settings.groq_api_key:
            raise GroqError("GROQ_API_KEY is not configured.")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings.groq_temperature,
            "max_tokens": (options or {}).get("num_predict", settings.groq_max_tokens),
            "stream": stream,
        }
        if format == "json":
            body["response_format"] = {"type": "json_object"}
        request = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            return urlopen(request, timeout=settings.groq_timeout_seconds)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise GroqError("Groq authentication failed. Check GROQ_API_KEY.") from exc
            if exc.code == 429:
                raise GroqError("Groq rate limit exceeded. Try again later.") from exc
            raise GroqError("Groq request failed.") from exc
        except (URLError, TimeoutError) as exc:
            raise GroqError("Groq request failed due to a network or timeout error.") from exc

    def generate(self, prompt: str, **kwargs: Any) -> str:
        response = self._request(
            prompt,
            stream=False,
            format=kwargs.get("format"),
            options=kwargs.get("options"),
        )
        try:
            body = json.loads(response.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GroqError("Groq returned malformed JSON.") from exc
        choices = body.get("choices") if isinstance(body, dict) else None
        content = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(content, str) or not content.strip():
            raise GroqError("Groq returned no text.")
        return content.strip()

    def generate_stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        response = self._request(
            prompt,
            stream=True,
            format=kwargs.get("format"),
            options=kwargs.get("options"),
        )
        try:
            for line in response:
                if not line.startswith(b"data: "):
                    continue
                value = line[6:].strip()
                if value == b"[DONE]":
                    break
                body = json.loads(value.decode("utf-8"))
                delta = body.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    yield delta
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GroqError("Groq returned malformed streaming data.") from exc


_job_model: GroqModel | None = None


def get_job_model() -> GroqModel:
    global _job_model
    if _job_model is None:
        _job_model = GroqModel()
    return _job_model
