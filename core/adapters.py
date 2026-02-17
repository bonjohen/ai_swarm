"""Concrete model adapters for the AI Swarm platform."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from core.errors import ModelAPIError
from core.routing import ModelCallable, make_stub_model_call

logger = logging.getLogger(__name__)


@dataclass
class OllamaAdapter:
    """Ollama chat-completion adapter implementing the ModelAdapter protocol."""

    name: str = "local"
    model: str = "qwen2.5:7b"
    host: str = "http://localhost:11434"
    temperature: float = 0.2
    timeout: float = 120.0
    extra_options: dict[str, Any] = field(default_factory=dict)

    def call(self, system_prompt: str, user_message: str) -> str:
        """POST to Ollama /api/chat and return the assistant content string."""
        url = f"{self.host.rstrip('/')}/api/chat"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                **self.extra_options,
            },
        }

        try:
            response = httpx.post(url, json=payload, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ModelAPIError(
                model=self.model,
                message=f"Timeout after {self.timeout}s: {exc}",
                retryable=True,
            ) from exc
        except httpx.ConnectError as exc:
            raise ModelAPIError(
                model=self.model,
                message=f"Connection error: {exc}",
                retryable=True,
            ) from exc

        if response.status_code != 200:
            retryable = response.status_code in (429, 500, 502, 503)
            raise ModelAPIError(
                model=self.model,
                message=f"HTTP {response.status_code}: {response.text[:200]}",
                retryable=retryable,
            )

        try:
            data = response.json()
            content = data["message"]["content"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelAPIError(
                model=self.model,
                message=f"Malformed response: {exc}",
                retryable=False,
            ) from exc

        return content


def make_ollama_adapter(
    model: str | None = None,
    host: str | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
) -> OllamaAdapter:
    """Factory with config precedence: explicit arg > env var > default."""
    return OllamaAdapter(
        model=model or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
        host=host or os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        temperature=temperature if temperature is not None else 0.2,
        timeout=timeout if timeout is not None else 120.0,
    )


def make_model_call(mode: str) -> ModelCallable:
    """Parse a --model-call flag value and return the appropriate callable.

    Supported modes:
      - "stub"                → raises NotImplementedError (for testing)
      - "ollama"              → OllamaAdapter with env/default config
      - "ollama:<model_name>" → OllamaAdapter with explicit model
    """
    if mode == "stub":
        return make_stub_model_call()

    if mode == "ollama":
        adapter = make_ollama_adapter()
        logger.info("Using Ollama adapter: model=%s, host=%s", adapter.model, adapter.host)
        return adapter.call

    if mode.startswith("ollama:"):
        # Split on first colon only so "ollama:deepseek-r1:1.5b" works
        model_name = mode.split(":", 1)[1]
        adapter = make_ollama_adapter(model=model_name)
        logger.info("Using Ollama adapter: model=%s, host=%s", adapter.model, adapter.host)
        return adapter.call

    raise ValueError(
        f"Unknown model-call mode: {mode!r}. "
        "Supported: 'stub', 'ollama', 'ollama:<model_name>'"
    )
