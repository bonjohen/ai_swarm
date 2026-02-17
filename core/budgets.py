"""Budget tracking for tokens, wall time, and dollar cost.

v0: tracking structure with stub enforcement. Full enforcement in Phase 4.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.errors import BudgetExceededError


@dataclass
class BudgetLedger:
    """Accumulates cost across a run."""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    _start_time: float = field(default_factory=time.time)

    # caps (0 = unlimited)
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    max_wall_seconds: float = 0.0

    def record(
        self,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record usage from a single agent call."""
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd += cost_usd

    def check(self) -> None:
        """Raise BudgetExceededError if any cap is breached."""
        total_tokens = self.tokens_in + self.tokens_out
        if self.max_tokens and total_tokens >= self.max_tokens:
            raise BudgetExceededError("tokens", self.max_tokens, total_tokens)
        if self.max_cost_usd and self.cost_usd >= self.max_cost_usd:
            raise BudgetExceededError("cost_usd", self.max_cost_usd, self.cost_usd)
        elapsed = time.time() - self._start_time
        if self.max_wall_seconds and elapsed >= self.max_wall_seconds:
            raise BudgetExceededError("wall_seconds", self.max_wall_seconds, elapsed)

    def to_dict(self) -> dict:
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_seconds": round(time.time() - self._start_time, 2),
        }
