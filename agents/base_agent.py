"""Base agent class — all agents inherit from this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class AgentPolicy(BaseModel):
    """Routing + budget + constraint policy for an agent."""
    allowed_local_models: list[str] = []
    allowed_frontier_models: list[str] = []
    max_tokens: int = 4096
    confidence_threshold: float = 0.7
    required_citations: bool = False


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

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """Execute the agent: build prompt, call model, parse, validate.

        model_call: a callable(system_prompt, user_message) -> str.
        Returns delta_state to be merged into run state.
        """
        system_prompt, user_message = self.build_prompt(state)
        if model_call is None:
            raise RuntimeError("model_call must be provided")
        raw_response = model_call(system_prompt, user_message)
        delta_state = self.parse(raw_response)
        self.validate(delta_state)
        return delta_state
