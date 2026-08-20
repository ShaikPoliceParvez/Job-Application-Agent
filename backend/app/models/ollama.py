"""Small Ollama HTTP adapter for local and cloud inference."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import settings
from .base import LLMModel, VisionModel

logger = logging.getLogger("models.ollama")


class OllamaError(RuntimeError):
    """Raised when Ollama cannot complete a generation."""


class OllamaModel(LLMModel, VisionModel):
    """Lazy, dependency-free client for Ollama's ``/api/generate`` endpoint."""

    def __init__(self, model: str, host: str | None = None, timeout: float | None = None):
        self.model = model
        self.host = (host or settings.ollama_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.ollama_timeout_seconds

    @staticmethod
    def _retryable_status(status: int) -> bool:
        return status == 408 or status == 425 or status == 429 or status >= 500

    def _request_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.llm_mode == "cloud":
            if not settings.ollama_api_key:
                raise OllamaError("OLLAMA_API_KEY is not configured.")
            headers["Authorization"] = f"Bearer {settings.ollama_api_key}"
        return headers

    def _request(self, payload: dict[str, Any]) -> Any:
        request = Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._request_headers(),
            method="POST",
        )
        attempts = settings.ollama_max_retries + 1
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if not self._retryable_status(exc.code) or attempt == attempts - 1:
                    if exc.code in (401, 403):
                        message = "Ollama Cloud authentication failed. Check OLLAMA_API_KEY."
                    elif exc.code == 404:
                        message = "Ollama model was not found. Check OLLAMA_MODEL."
                    elif exc.code == 429:
                        message = "Ollama Cloud rate limit exceeded. Try again later."
                    else:
                        message = "Ollama request failed. Check OLLAMA_BASE_URL and OLLAMA_MODEL."
                    raise OllamaError(message) from exc
            except (URLError, TimeoutError) as exc:
                if attempt == attempts - 1:
                    raise OllamaError("Ollama request failed due to a network or timeout error.") from exc
            except json.JSONDecodeError as exc:
                raise OllamaError("Ollama returned malformed JSON.") from exc
            time.sleep(2**attempt)
        raise OllamaError("Ollama request failed.")

    def _generate(self, prompt: str, images: list[str] | None = None, **kwargs: Any) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": {
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": settings.ollama_num_predict,
                "temperature": settings.ollama_temperature,
            },
            **kwargs,
        }
        if images:
            payload["images"] = images

        body = self._request(payload)

        if not isinstance(body, dict):
            raise OllamaError("Ollama returned a malformed model response.")
        generated = body.get("response")
        if not isinstance(generated, str) or not generated.strip():
            raise OllamaError(f"Ollama returned no text for model '{self.model}'")
        return generated.strip()

    def generate(self, prompt: str, **kwargs: Any) -> str:
        return self._generate(prompt, **kwargs)

    def generate_stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        options = {
            "num_ctx": settings.ollama_num_ctx,
            "num_predict": settings.ollama_num_predict,
            "temperature": settings.ollama_temperature,
        }
        options.update(kwargs.pop("options", {}))
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": settings.ollama_keep_alive,
            "options": options,
            **kwargs,
        }
        request = Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._request_headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                for line in response:
                    if not line.strip():
                        continue
                    body = json.loads(line.decode("utf-8"))
                    chunk = body.get("response", "")
                    if chunk:
                        yield chunk
                    if body.get("done"):
                        break
        except HTTPError as exc:
            if exc.code in (401, 403):
                message = "Ollama Cloud authentication failed. Check OLLAMA_API_KEY."
            elif exc.code == 404:
                message = "Ollama model was not found. Check OLLAMA_MODEL."
            else:
                message = "Ollama stream request failed. Check Ollama configuration."
            raise OllamaError(message) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama stream request failed due to a network or timeout error.") from exc

    def analyze_image(self, image_path: str, instruction: str) -> str:
        from pathlib import Path
        import base64

        image_data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        return self._generate(instruction, images=[image_data])


_job_model: OllamaModel | None = None


def get_job_model() -> OllamaModel:
    global _job_model
    if _job_model is None:
        _job_model = OllamaModel(settings.ollama_model)
    return _job_model


def get_vision_model() -> OllamaModel:
    return OllamaModel(settings.model_vision)