"""Small Ollama HTTP adapter used by the local agent models."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.config import settings
from backend.app.models.base import LLMModel, VisionModel

logger = logging.getLogger("models.ollama")


class OllamaError(RuntimeError):
    """Raised when the local Ollama server cannot complete a generation."""


class OllamaModel(LLMModel, VisionModel):
    """Lazy, dependency-free client for Ollama's ``/api/generate`` endpoint."""

    def __init__(self, model: str, host: str | None = None, timeout: float | None = None):
        self.model = model
        self.host = (host or settings.ollama_host).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.ollama_timeout_seconds

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

        request = Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise OllamaError(
                f"Ollama request failed for model '{self.model}' ({exc.code}): {detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama request failed for model '{self.model}': {exc}") from exc

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
            headers={"Content-Type": "application/json"},
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
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise OllamaError(
                f"Ollama stream failed for model '{self.model}' ({exc.code}): {detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama stream failed for model '{self.model}': {exc}") from exc

    def analyze_image(self, image_path: str, instruction: str) -> str:
        from pathlib import Path
        import base64

        image_data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        return self._generate(instruction, images=[image_data])


_job_model: OllamaModel | None = None


def get_job_model() -> OllamaModel:
    global _job_model
    if _job_model is None:
        _job_model = OllamaModel(settings.model_email)
    return _job_model


def get_vision_model() -> OllamaModel:
    return OllamaModel(settings.model_vision)