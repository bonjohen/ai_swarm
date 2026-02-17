"""Policy definitions and enforcement for graph execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunPolicy:
    """Top-level policy applied to an entire run."""
    max_tokens_per_run: int = 500_000
    max_cost_per_run: float = 10.0  # USD
    max_wall_time_seconds: float = 3600.0
    default_model: str = "local"


@dataclass
class NodePolicy:
    """Policy overrides at the node level."""
    max_tokens: int | None = None
    max_cost: float | None = None
    allowed_models: list[str] = field(default_factory=list)


def merge_budget_override(
    run_policy: RunPolicy, node_budget: dict[str, Any] | None
) -> NodePolicy:
    """Derive a NodePolicy from the run-level policy and optional node-level overrides."""
    if node_budget is None:
        return NodePolicy(
            max_tokens=run_policy.max_tokens_per_run,
            max_cost=run_policy.max_cost_per_run,
        )
    return NodePolicy(
        max_tokens=node_budget.get("max_tokens", run_policy.max_tokens_per_run),
        max_cost=node_budget.get("max_cost", run_policy.max_cost_per_run),
        allowed_models=node_budget.get("allowed_models", []),
    )
