"""Base agent class — all agents inherit from this."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


def extract_json(text: str) -> str:
    """Extract JSON from an LLM response that may contain markdown fences or prose.

    Handles:
    - Clean JSON (returned as-is after strip)
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Preamble/postamble text around a JSON object or array
    """
    stripped = text.strip()

    # 1. Strip markdown code fences
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 2. Find outermost { ... } or [ ... ] (whichever appears first)
    pairs = [("{", "}"), ("[", "]")]
    brace_pos = stripped.find("{")
    bracket_pos = stripped.find("[")
    if bracket_pos != -1 and (brace_pos == -1 or bracket_pos < brace_pos):
        pairs = [("[", "]"), ("{", "}")]
    for open_ch, close_ch in pairs:
        start = stripped.find(open_ch)
        if start == -1:
            continue
        end = stripped.rfind(close_ch)
        if end > start:
            return stripped[start:end + 1]

    # 3. Fall through — return stripped text and let json.loads give the error
    return stripped


class AgentPolicy(BaseModel):
    """Routing + budget + constraint policy for an agent."""
    allowed_local_models: list[str] = []
    allowed_frontier_models: list[str] = []
    max_tokens: int = 4096
    confidence_threshold: float = 0.7
    required_citations: bool = False
    preferred_tier: int = 2
    min_tier: int = 1
    max_tokens_by_tier: dict[int, int] = {}


class BaseAgent(ABC):
    """Abstract base for all swarm agents.

    Subclasses must define the class-level attributes and implement
    parse() and validate().
    """

    # --- required class attributes (set by subclass) ---
    AGENT_ID: str
    VERSION: str
    SYSTEM_PROMPT: str
    USER_TEMPLATE: str  # Python format-string using state keys
    INPUT_SCHEMA: type[BaseModel]
    OUTPUT_SCHEMA: type[BaseModel]
    POLICY: AgentPolicy

    # --- runtime contract ---

    def build_prompt(self, state: dict[str, Any]) -> tuple[str, str]:
        """Return (system_prompt, user_message) from current state."""
        safe = {k: (str(v) if not isinstance(v, str) else v) for k, v in state.items()}
        return self.SYSTEM_PROMPT, self.USER_TEMPLATE.format_map(
            type("_SafeDict", (dict,), {"__missing__": lambda s, k: f"{{{k}}}"})(**safe)
        )

    @abstractmethod
    def parse(self, response: str) -> dict[str, Any]:
        """Parse raw model response into a delta_state dict."""
        ...

    @abstractmethod
    def validate(self, output: dict[str, Any]) -> None:
        """Validate parsed output. Raise on failure."""
        ...

    MAX_REPAIR_ATTEMPTS: int = 2

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """Execute the agent: build prompt, call model, parse, validate.

        On validation failure, sends the error back to the model as a repair
        prompt and retries up to MAX_REPAIR_ATTEMPTS times.

        model_call: a callable(system_prompt, user_message) -> str.
        Returns delta_state to be merged into run state.
        """
        _log = logging.getLogger(__name__)
        system_prompt, user_message = self.build_prompt(state)
        if model_call is None:
            raise RuntimeError("model_call must be provided")
        last_error: Exception | None = None
        raw_response = model_call(system_prompt, user_message)

        for attempt in range(1 + self.MAX_REPAIR_ATTEMPTS):
            try:
                delta_state = self.parse(extract_json(raw_response))
                self.validate(delta_state)
                return delta_state
            except (ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt >= self.MAX_REPAIR_ATTEMPTS:
                    break
                _log.warning(
                    "Agent %s parse/validate failed (attempt %d/%d): %s — sending repair prompt",
                    self.AGENT_ID, attempt + 1, self.MAX_REPAIR_ATTEMPTS + 1, exc,
                )
                repair_prompt = (
                    f"Your previous JSON response had an error:\n{exc}\n\n"
                    f"Original request:\n{user_message}\n\n"
                    "Please fix the error and return valid JSON only."
                )
                raw_response = model_call(system_prompt, repair_prompt)

        raise last_error  # type: ignore[misc]
