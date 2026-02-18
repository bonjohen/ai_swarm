"""Concrete model adapters for the AI Swarm platform."""

from __future__ import annotations

import logging
import os
import time
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
    max_tokens: int = 4096
    context_length: int = 4096
    extra_options: dict[str, Any] = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    call_count: int = 0

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
            "format": "json",
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": self.context_length,
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

        self.total_input_tokens += data.get("prompt_eval_count", 0)
        self.total_output_tokens += data.get("eval_count", 0)
        self.call_count += 1

        return content


def make_ollama_adapter(
    model: str | None = None,
    host: str | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    context_length: int | None = None,
) -> OllamaAdapter:
    """Factory with config precedence: explicit arg > env var > default."""
    return OllamaAdapter(
        model=model or os.environ.get("OLLAMA_MODEL", "llama3:8b-instruct-q8_0"),
        host=host or os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        temperature=temperature if temperature is not None else 0.2,
        timeout=timeout if timeout is not None else 300.0,
        max_tokens=max_tokens if max_tokens is not None else 4096,
        context_length=context_length if context_length is not None else 8192,
    )


def make_micro_adapter() -> OllamaAdapter:
    """Tier 1 micro adapter — fast classification/routing with minimal context."""
    model = os.environ.get("OLLAMA_TIER1_MODEL", "deepseek-r1:1.5b")
    return OllamaAdapter(
        name="micro",
        model=model,
        temperature=0.0,
        max_tokens=128,
        context_length=2048,
    )


def make_light_adapter() -> OllamaAdapter:
    """Tier 2 light adapter — extraction/summarisation with moderate context."""
    model = os.environ.get("OLLAMA_TIER2_MODEL", "deepseek-r1:1.5b")
    return OllamaAdapter(
        name="light",
        model=model,
        temperature=0.2,
        max_tokens=1024,
        context_length=4096,
    )


def make_json_recovery_adapter() -> OllamaAdapter:
    """Small model for recovering structured JSON from freeform LLM output.

    Uses the tier2 light model with enough context to ingest the raw text and
    enough output tokens to produce the full JSON structure.
    """
    model = os.environ.get("OLLAMA_TIER2_MODEL", "deepseek-r1:1.5b")
    return OllamaAdapter(
        name="json_recovery",
        model=model,
        temperature=0.0,
        max_tokens=2048,
        context_length=8192,
    )


@dataclass
class AnthropicAdapter:
    """Anthropic Messages API adapter implementing the ModelAdapter protocol."""

    name: str = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout: float = 120.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    call_count: int = 0
    min_interval: float = 0.0  # seconds between calls (rate limiter)
    _last_call_time: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def call(self, system_prompt: str, user_message: str) -> str:
        """POST to Anthropic /v1/messages and return the assistant text."""
        if self.min_interval > 0 and self._last_call_time > 0:
            elapsed = time.monotonic() - self._last_call_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_call_time = time.monotonic()

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
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
            retryable = response.status_code in (429, 500, 502, 503, 529)
            raise ModelAPIError(
                model=self.model,
                message=f"HTTP {response.status_code}: {response.text[:200]}",
                retryable=retryable,
            )

        try:
            data = response.json()
            content = data["content"][0]["text"]
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ModelAPIError(
                model=self.model,
                message=f"Malformed response: {exc}",
                retryable=False,
            ) from exc

        usage = data.get("usage", {})
        self.total_input_tokens += usage.get("input_tokens", 0)
        self.total_output_tokens += usage.get("output_tokens", 0)
        self.call_count += 1

        return content


@dataclass
class OpenAIAdapter:
    """OpenAI-compatible chat completions adapter implementing ModelAdapter protocol."""

    name: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout: float = 120.0

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")

    def call(self, system_prompt: str, user_message: str) -> str:
        """POST to chat/completions endpoint and return the assistant text."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
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
            content = data["choices"][0]["message"]["content"]
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ModelAPIError(
                model=self.model,
                message=f"Malformed response: {exc}",
                retryable=False,
            ) from exc

        return content


@dataclass
class DGXSparkAdapter:
    """DGX Spark adapter — delegates to a remote Ollama instance with hardware-specific defaults."""

    name: str = "dgx_spark"
    model: str = "llama3:70b"
    host: str = "http://dgx-spark:11434"
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout: float = 300.0

    def __post_init__(self) -> None:
        self._inner = OllamaAdapter(
            name=self.name,
            model=self.model,
            host=self.host,
            temperature=self.temperature,
            timeout=self.timeout,
            max_tokens=self.max_tokens,
            context_length=8192,
        )

    def call(self, system_prompt: str, user_message: str) -> str:
        """Delegate to inner OllamaAdapter."""
        return self._inner.call(system_prompt, user_message)


def make_router_from_config(config_path: str) -> "ModelRouter":
    """Build a fully-wired ModelRouter from a router_config.yaml file.

    Creates Tier 1 (micro) and Tier 2 (light) local adapters from the config,
    loads Tier 3 frontier providers into a ProviderRegistry, and wires
    everything into a ModelRouter with the config's escalation criteria.
    """
    from core.routing import ModelRouter, load_router_config
    from core.provider_registry import ProviderRegistry, load_providers_from_config

    config = load_router_config(config_path)

    # Build tier adapters from config
    tier1 = OllamaAdapter(
        name="micro",
        model=config.tier1.model,
        temperature=config.tier1.temperature,
        max_tokens=config.tier1.max_tokens,
        context_length=config.tier1.context_length,
    )
    tier2 = OllamaAdapter(
        name="light",
        model=config.tier2.model,
        temperature=config.tier2.temperature,
        max_tokens=config.tier2.max_tokens,
        context_length=config.tier2.context_length,
    )

    router = ModelRouter(escalation_criteria=config.escalation, config=config)
    router.register_local(tier1)
    router.register_local(tier2)

    # Load tier 3 providers
    provider_registry = ProviderRegistry(daily_cap=config.daily_frontier_cap)
    load_providers_from_config(provider_registry, config.tier3_providers)
    for entry in provider_registry.list_available():
        router.register_frontier(entry.adapter)

    logger.info(
        "Router initialized from %s: tier1=%s, tier2=%s, %d frontier providers",
        config_path, tier1.model, tier2.model, len(provider_registry.list_available()),
    )
    return router


def make_model_call(mode: str) -> ModelCallable:
    """Parse a --model-call flag value and return the appropriate callable.

    Supported modes:
      - "stub"                → raises NotImplementedError (for testing)
      - "tier1"               → micro adapter (deepseek-r1:1.5b, ctx 2048)
      - "tier2"               → light adapter (deepseek-r1:1.5b, ctx 4096)
      - "ollama"              → OllamaAdapter with env/default config
      - "ollama:<model_name>" → OllamaAdapter with explicit model
    """
    if mode == "stub":
        return make_stub_model_call()

    if mode == "tier1":
        adapter = make_micro_adapter()
        logger.info("Using tier1 micro adapter: model=%s", adapter.model)
        return adapter.call

    if mode == "tier2":
        adapter = make_light_adapter()
        logger.info("Using tier2 light adapter: model=%s", adapter.model)
        return adapter.call

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

    if mode == "anthropic":
        adapter = AnthropicAdapter()
        logger.info("Using Anthropic adapter: model=%s", adapter.model)
        return adapter.call

    if mode.startswith("anthropic:"):
        model_name = mode.split(":", 1)[1]
        adapter = AnthropicAdapter(model=model_name)
        logger.info("Using Anthropic adapter: model=%s", adapter.model)
        return adapter.call

    raise ValueError(
        f"Unknown model-call mode: {mode!r}. "
        "Supported: 'stub', 'tier1', 'tier2', 'ollama', 'ollama:<model_name>', "
        "'anthropic', 'anthropic:<model_name>'"
    )
