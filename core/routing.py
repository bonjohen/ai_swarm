"""Model routing — local-first with escalation to frontier models."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from agents.base_agent import AgentPolicy

logger = logging.getLogger(__name__)

# Type alias for a model callable: (system_prompt, user_message) -> response_text
ModelCallable = Callable[[str, str], str]


@dataclass
class RoutingDecision:
    model_name: str
    reason: str
    escalated: bool = False


class ModelAdapter(Protocol):
    """Interface for model adapters (local and frontier)."""
    name: str

    def call(self, system_prompt: str, user_message: str) -> str: ...


@dataclass
class EscalationCriteria:
    """Thresholds that trigger escalation from local to frontier."""
    min_confidence: float = 0.7
    max_missing_citations: int = 2
    max_contradiction_ambiguity: float = 0.5
    synthesis_complexity_threshold: float = 0.8


@dataclass
class TierConfig:
    """Configuration for a single inference tier."""

    model: str
    context_length: int
    max_tokens: int
    temperature: float
    concurrency: int = 1


@dataclass
class ProviderConfig:
    """Configuration for a Tier 3 frontier provider."""

    name: str
    provider_type: str  # "ollama", "anthropic", "openai", "dgx"
    model: str
    host: str | None = None
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    quality_score: float = 0.5
    max_context: int = 4096
    tags: list[str] = field(default_factory=list)


@dataclass
class RouterConfig:
    """Full router configuration loaded from YAML."""

    tier1: TierConfig
    tier2: TierConfig
    tier3_providers: list[ProviderConfig]
    escalation: EscalationCriteria
    provider_selection_strategy: str = "prefer_local"
    daily_frontier_cap: int = 100


def load_router_config(path: str | Path) -> RouterConfig:
    """Load router configuration from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    tier1 = TierConfig(**raw["tier1"])
    tier2 = TierConfig(**raw["tier2"])

    providers = []
    for p in raw.get("tier3_providers", []):
        providers.append(ProviderConfig(**p))

    esc_raw = raw.get("escalation", {})
    escalation = EscalationCriteria(**esc_raw)

    return RouterConfig(
        tier1=tier1,
        tier2=tier2,
        tier3_providers=providers,
        escalation=escalation,
        provider_selection_strategy=raw.get("provider_selection_strategy", "prefer_local"),
        daily_frontier_cap=raw.get("daily_frontier_cap", 100),
    )


@dataclass
class ModelRouter:
    """Routes agent calls to local or frontier models based on policy and state."""
    local_adapters: dict[str, ModelAdapter] = field(default_factory=dict)
    frontier_adapters: dict[str, ModelAdapter] = field(default_factory=dict)
    escalation_criteria: EscalationCriteria = field(default_factory=EscalationCriteria)
    config: RouterConfig | None = None

    def register_local(self, adapter: ModelAdapter) -> None:
        self.local_adapters[adapter.name] = adapter

    def register_frontier(self, adapter: ModelAdapter) -> None:
        self.frontier_adapters[adapter.name] = adapter

    def select_model(
        self,
        agent_policy: AgentPolicy,
        state: dict[str, Any],
    ) -> RoutingDecision:
        """Choose which model to use, evaluating escalation criteria."""
        escalation_reasons = self._evaluate_escalation(agent_policy, state)

        if escalation_reasons and agent_policy.allowed_frontier_models:
            model = agent_policy.allowed_frontier_models[0]
            reason = f"escalated: {'; '.join(escalation_reasons)}"
            decision = RoutingDecision(model_name=model, reason=reason, escalated=True)
        else:
            model = agent_policy.allowed_local_models[0] if agent_policy.allowed_local_models else "local"
            reason = "local-first policy"
            decision = RoutingDecision(model_name=model, reason=reason)

        logger.info("Routing: %s (escalated=%s, reason=%s)", decision.model_name, decision.escalated, decision.reason)
        return decision

    def get_model_callable(self, decision: RoutingDecision) -> ModelCallable:
        """Return the callable for the selected model."""
        if decision.escalated:
            adapter = self.frontier_adapters.get(decision.model_name)
        else:
            adapter = self.local_adapters.get(decision.model_name)

        if adapter is None:
            raise RuntimeError(f"No adapter registered for model: {decision.model_name}")
        return adapter.call

    def _evaluate_escalation(
        self, policy: AgentPolicy, state: dict[str, Any]
    ) -> list[str]:
        """Check if escalation criteria are met. Returns list of reasons (empty = no escalation)."""
        reasons: list[str] = []
        criteria = self.escalation_criteria

        # Low confidence from prior extraction
        last_confidence = state.get("_last_confidence")
        if last_confidence is not None and last_confidence < criteria.min_confidence:
            reasons.append(f"low confidence ({last_confidence:.2f} < {criteria.min_confidence})")

        # Missing citations detected
        missing_citations_count = state.get("_missing_citations_count", 0)
        if missing_citations_count > criteria.max_missing_citations:
            reasons.append(f"missing citations ({missing_citations_count} > {criteria.max_missing_citations})")

        # Contradiction ambiguity
        contradiction_ambiguity = state.get("_contradiction_ambiguity")
        if contradiction_ambiguity is not None and contradiction_ambiguity > criteria.max_contradiction_ambiguity:
            reasons.append(f"contradiction ambiguity ({contradiction_ambiguity:.2f})")

        # Synthesis complexity
        synthesis_complexity = state.get("_synthesis_complexity")
        if synthesis_complexity is not None and synthesis_complexity > criteria.synthesis_complexity_threshold:
            reasons.append(f"synthesis complexity ({synthesis_complexity:.2f})")

        return reasons


# --- Module-level convenience functions ---

_default_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    """Get or create the default router."""
    global _default_router
    if _default_router is None:
        _default_router = ModelRouter()
    return _default_router


def set_router(router: ModelRouter) -> None:
    """Replace the default router (useful for testing)."""
    global _default_router
    _default_router = router


def select_model(
    agent_policy: AgentPolicy,
    state: dict[str, Any],
) -> RoutingDecision:
    """Choose which model to use via the default router."""
    return get_router().select_model(agent_policy, state)


def make_stub_model_call() -> ModelCallable:
    """Return a stub model callable for testing."""
    def _stub(system_prompt: str, user_message: str) -> str:
        raise NotImplementedError(
            "No model adapter configured. Provide a real model_call or use a test mock."
        )
    return _stub
