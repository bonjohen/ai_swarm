"""Provider registry — cost/quality-based selection of model providers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProviderEntry:
    """A registered model provider with cost and quality metadata."""

    name: str
    adapter: Any  # ModelAdapter protocol
    provider_type: str  # "ollama", "anthropic", "openai", "dgx"
    cost_per_1k_input: float
    cost_per_1k_output: float
    quality_score: float  # 0-1 benchmark rating
    max_context: int
    tags: list[str] = field(default_factory=list)
    available: bool = True


@dataclass
class TaskRequirements:
    """Filter criteria for provider selection."""

    min_quality: float = 0.0
    max_cost_per_1k: float = float("inf")
    min_context: int = 0
    preferred_tags: list[str] = field(default_factory=list)


class ProviderRegistry:
    """Registry of model providers with strategy-based selection."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderEntry] = {}

    def register(self, entry: ProviderEntry) -> None:
        """Register a provider entry."""
        self._providers[entry.name] = entry
        logger.info("Registered provider: %s (type=%s, quality=%.2f)", entry.name, entry.provider_type, entry.quality_score)

    def get(self, name: str) -> ProviderEntry | None:
        """Get a provider by name."""
        return self._providers.get(name)

    def list_available(self) -> list[ProviderEntry]:
        """List all available providers."""
        return [p for p in self._providers.values() if p.available]

    def select_provider(
        self,
        requirements: TaskRequirements,
        strategy: str = "cheapest_qualified",
    ) -> ProviderEntry | None:
        """Select a provider based on requirements and strategy.

        Strategies:
          - cheapest_qualified: filter by min_quality + min_context, sort by cost asc
          - highest_quality: filter by max_cost + min_context, sort by quality desc
          - prefer_local: partition into local/cloud, pick best local first, then cloud
        """
        candidates = self._filter(requirements)
        if not candidates:
            return None

        if strategy == "cheapest_qualified":
            return self._cheapest_qualified(candidates)
        elif strategy == "highest_quality":
            return self._highest_quality(candidates)
        elif strategy == "prefer_local":
            return self._prefer_local(candidates)
        else:
            raise ValueError(f"Unknown selection strategy: {strategy!r}")

    def _filter(self, req: TaskRequirements) -> list[ProviderEntry]:
        """Filter providers by availability and basic requirements."""
        result = []
        for p in self._providers.values():
            if not p.available:
                continue
            if p.quality_score < req.min_quality:
                continue
            if p.max_context < req.min_context:
                continue
            avg_cost = (p.cost_per_1k_input + p.cost_per_1k_output) / 2
            if avg_cost > req.max_cost_per_1k:
                continue
            result.append(p)
        return result

    def _cheapest_qualified(self, candidates: list[ProviderEntry]) -> ProviderEntry:
        """Sort by average cost ascending, return cheapest."""
        return min(candidates, key=lambda p: (p.cost_per_1k_input + p.cost_per_1k_output) / 2)

    def _highest_quality(self, candidates: list[ProviderEntry]) -> ProviderEntry:
        """Sort by quality descending, return highest."""
        return max(candidates, key=lambda p: p.quality_score)

    def _prefer_local(self, candidates: list[ProviderEntry]) -> ProviderEntry:
        """Prefer local providers over cloud, then pick by quality."""
        local = [p for p in candidates if "local" in p.tags]
        cloud = [p for p in candidates if "local" not in p.tags]
        if local:
            return max(local, key=lambda p: p.quality_score)
        return max(cloud, key=lambda p: p.quality_score)
