"""Model routing — local-first with escalation to frontier models.

v0: stub implementation. Provides the interface and always selects 'local'.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from agents.base_agent import AgentPolicy

logger = logging.getLogger(__name__)

# Type alias for a model callable: (system_prompt, user_message) -> response_text
ModelCallable = Callable[[str, str], str]


@dataclass
class RoutingDecision:
    model_name: str
    reason: str


def select_model(
    agent_policy: AgentPolicy,
    state: dict[str, Any],
) -> RoutingDecision:
    """Choose which model to use for an agent invocation.

    v0 stub: always returns 'local'. Full implementation in Phase 1
    will evaluate confidence, citation gaps, and contradiction ambiguity.
    """
    # TODO (Phase 1): evaluate escalation criteria
    #   - extraction confidence < agent_policy.confidence_threshold
    #   - missing citations detected repeatedly
    #   - contradiction ambiguity high
    #   - synthesis requires high fidelity
    model = agent_policy.allowed_local_models[0] if agent_policy.allowed_local_models else "local"
    decision = RoutingDecision(model_name=model, reason="default local-first policy")
    logger.info("Routing decision: %s (%s)", decision.model_name, decision.reason)
    return decision


def make_stub_model_call() -> ModelCallable:
    """Return a stub model callable for testing.

    Returns a callable that raises NotImplementedError — replace with
    real model adapters in Phase 1.
    """
    def _stub(system_prompt: str, user_message: str) -> str:
        raise NotImplementedError(
            "No model adapter configured. Provide a real model_call or use a test mock."
        )
    return _stub
