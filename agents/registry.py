"""Agent registry — register and look up agents by AGENT_ID."""

from __future__ import annotations

from agents.base_agent import BaseAgent

_REGISTRY: dict[str, BaseAgent] = {}


def register(agent: BaseAgent) -> BaseAgent:
    """Register an agent instance. Overwrites if same AGENT_ID exists."""
    _REGISTRY[agent.AGENT_ID] = agent
    return agent


def get_agent(agent_id: str) -> BaseAgent:
    """Look up a registered agent by its AGENT_ID."""
    if agent_id not in _REGISTRY:
        raise KeyError(f"Agent not registered: {agent_id}")
    return _REGISTRY[agent_id]


def list_agents() -> list[str]:
    """Return all registered AGENT_IDs."""
    return list(_REGISTRY.keys())


def clear() -> None:
    """Remove all registered agents (useful for testing)."""
    _REGISTRY.clear()
