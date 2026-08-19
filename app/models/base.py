"""
Common model interface so agent/node code never depends on a specific
model implementation directly (spec section 37).

Only OCRModel is used in Phase 1. LLMModel and VisionModel are the
contracts that Qwen (via Ollama) and Gemma vision (via Ollama) will
implement in later phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OCRModel(ABC):
    @abstractmethod
    def extract_text(self, image_path: str) -> dict[str, Any]:
        """Return {"text": str, "confidence": float, "blocks": list[dict]}."""
        raise NotImplementedError


class LLMModel(ABC):
    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError


class VisionModel(ABC):
    @abstractmethod
    def analyze_image(self, image_path: str, instruction: str) -> str:
        raise NotImplementedError
