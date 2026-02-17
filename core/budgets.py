"""Budget tracking for tokens, wall time, and dollar cost.

Supports per-node caps, degradation hints, and human review flags.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.errors import BudgetExceededError


@dataclass
class DegradationHint:
    """Guidance on how to degrade when budget is near exhaustion."""
    max_sources: int | None = None
    max_questions: int | None = None
    skip_deep_synthesis: bool = False
    reason: str = ""


@dataclass
class BudgetLedger:
    """Accumulates cost across a run with enforcement at multiple levels."""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    _start_time: float = field(default_factory=time.time)

    # Run-level caps (0 = unlimited)
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    max_wall_seconds: float = 0.0

    # Degradation thresholds (fraction of budget consumed before degradation kicks in)
    degrade_at_fraction: float = 0.8

    # Track whether degradation has been triggered
    degradation_active: bool = False
    _degradation_hint: DegradationHint = field(default_factory=DegradationHint)

    # Human review flag
    needs_human_review: bool = False
    _human_review_reasons: list[str] = field(default_factory=list)

    # Per-node tracking
    _node_costs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record(
        self,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        node_id: str = "",
    ) -> None:
        """Record usage from a single agent call."""
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd += cost_usd

        if node_id:
            node = self._node_costs.setdefault(node_id, {
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
            })
            node["tokens_in"] += tokens_in
            node["tokens_out"] += tokens_out
            node["cost_usd"] += cost_usd

    def check(self, node_budget: dict[str, Any] | None = None) -> None:
        """Raise BudgetExceededError if any cap is breached.

        Also updates degradation state when approaching limits.
        """
        total_tokens = self.tokens_in + self.tokens_out

        # Check run-level caps
        if self.max_tokens and total_tokens >= self.max_tokens:
            raise BudgetExceededError("tokens", self.max_tokens, total_tokens)
        if self.max_cost_usd and self.cost_usd >= self.max_cost_usd:
            raise BudgetExceededError("cost_usd", self.max_cost_usd, self.cost_usd)
        elapsed = time.time() - self._start_time
        if self.max_wall_seconds and elapsed >= self.max_wall_seconds:
            raise BudgetExceededError("wall_seconds", self.max_wall_seconds, elapsed)

        # Check per-node caps if provided
        if node_budget:
            node_max_tokens = node_budget.get("max_tokens", 0)
            node_max_cost = node_budget.get("max_cost", 0.0)
            if node_max_tokens and total_tokens >= node_max_tokens:
                raise BudgetExceededError("node_tokens", node_max_tokens, total_tokens)
            if node_max_cost and self.cost_usd >= node_max_cost:
                raise BudgetExceededError("node_cost", node_max_cost, self.cost_usd)

        # Update degradation state
        self._update_degradation(total_tokens, elapsed)

    def _update_degradation(self, total_tokens: int, elapsed: float) -> None:
        """Check if we should activate degradation mode."""
        fraction = self.degrade_at_fraction
        reasons: list[str] = []

        if self.max_tokens and total_tokens >= self.max_tokens * fraction:
            reasons.append(f"tokens at {total_tokens}/{self.max_tokens}")
        if self.max_cost_usd and self.cost_usd >= self.max_cost_usd * fraction:
            reasons.append(f"cost at ${self.cost_usd:.4f}/${self.max_cost_usd}")
        if self.max_wall_seconds and elapsed >= self.max_wall_seconds * fraction:
            reasons.append(f"time at {elapsed:.0f}s/{self.max_wall_seconds:.0f}s")

        if reasons:
            self.degradation_active = True
            self._degradation_hint = DegradationHint(
                max_sources=3,
                max_questions=5,
                skip_deep_synthesis=True,
                reason="; ".join(reasons),
            )

    def get_degradation_hint(self) -> DegradationHint | None:
        """Return degradation guidance if active, else None."""
        return self._degradation_hint if self.degradation_active else None

    def flag_human_review(self, reason: str) -> None:
        """Flag that this run needs human review."""
        self.needs_human_review = True
        self._human_review_reasons.append(reason)

    def get_human_review_reasons(self) -> list[str]:
        return list(self._human_review_reasons)

    def node_cost(self, node_id: str) -> dict[str, Any]:
        """Get cost breakdown for a specific node."""
        return dict(self._node_costs.get(node_id, {
            "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
        }))

    def to_dict(self) -> dict:
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_seconds": round(time.time() - self._start_time, 2),
            "degradation_active": self.degradation_active,
            "needs_human_review": self.needs_human_review,
        }
