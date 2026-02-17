"""Provider registry — cost/quality-based selection of model providers."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
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

    def __init__(self, *, daily_cap: int = 100) -> None:
        self._providers: dict[str, ProviderEntry] = {}
        self.daily_cap = daily_cap
        self._daily_calls: dict[str, int] = defaultdict(int)  # date_str -> count
        self._provider_calls: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

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

    # --- Frontier cap enforcement ---

    def _today(self) -> str:
        return date.today().isoformat()

    def record_call(self, provider_name: str) -> None:
        """Record a frontier call for cap tracking."""
        today = self._today()
        self._daily_calls[today] += 1
        self._provider_calls[today][provider_name] += 1

    def daily_calls_today(self) -> int:
        """Total frontier calls today."""
        return self._daily_calls.get(self._today(), 0)

    def is_cap_exceeded(self) -> bool:
        """Check if daily aggregate frontier cap is exceeded."""
        return self.daily_calls_today() >= self.daily_cap

    def select_provider_with_fallback(
        self,
        requirements: TaskRequirements,
        strategy: str = "cheapest_qualified",
    ) -> ProviderEntry | None:
        """Select a provider, falling back to next if first fails cap check.

        Skips providers that are marked unavailable.
        Returns None if no providers available or cap exceeded.
        """
        if self.is_cap_exceeded():
            logger.warning("Daily frontier cap (%d) exceeded", self.daily_cap)
            return None

        candidates = self._filter(requirements)
        if not candidates:
            return None

        # Sort by strategy preference, then try each in order
        if strategy == "cheapest_qualified":
            sorted_candidates = sorted(candidates, key=lambda p: (p.cost_per_1k_input + p.cost_per_1k_output) / 2)
        elif strategy == "highest_quality":
            sorted_candidates = sorted(candidates, key=lambda p: p.quality_score, reverse=True)
        elif strategy == "prefer_local":
            local = sorted([p for p in candidates if "local" in p.tags], key=lambda p: p.quality_score, reverse=True)
            cloud = sorted([p for p in candidates if "local" not in p.tags], key=lambda p: p.quality_score, reverse=True)
            sorted_candidates = local + cloud
        else:
            sorted_candidates = candidates

        for provider in sorted_candidates:
            if provider.available:
                return provider

        return None

    def mark_unavailable(self, name: str) -> None:
        """Mark a provider as temporarily unavailable."""
        if name in self._providers:
            self._providers[name].available = False
            logger.warning("Provider '%s' marked unavailable", name)

    def mark_available(self, name: str) -> None:
        """Mark a provider as available again."""
        if name in self._providers:
            self._providers[name].available = True


def load_providers_from_config(
    registry: ProviderRegistry,
    provider_configs: list[Any],
) -> None:
    """Load providers from router_config.yaml tier3_providers into a registry.

    Each config is a ProviderConfig (from core.routing) with fields:
    name, provider_type, model, host, cost_per_1k_input, cost_per_1k_output,
    quality_score, max_context, tags.
    """
    from core.adapters import AnthropicAdapter, DGXSparkAdapter, OllamaAdapter, OpenAIAdapter

    for pc in provider_configs:
        if pc.provider_type == "dgx":
            adapter = DGXSparkAdapter(
                name=pc.name,
                model=pc.model,
                host=pc.host or "http://localhost:11434",
            )
        elif pc.provider_type == "anthropic":
            adapter = AnthropicAdapter(name=pc.name, model=pc.model)
        elif pc.provider_type == "openai":
            adapter = OpenAIAdapter(name=pc.name, model=pc.model)
        elif pc.provider_type == "ollama":
            adapter = OllamaAdapter(name=pc.name, model=pc.model)
        else:
            logger.warning("Unknown provider_type '%s' for '%s', skipping", pc.provider_type, pc.name)
            continue

        entry = ProviderEntry(
            name=pc.name,
            adapter=adapter,
            provider_type=pc.provider_type,
            cost_per_1k_input=pc.cost_per_1k_input,
            cost_per_1k_output=pc.cost_per_1k_output,
            quality_score=pc.quality_score,
            max_context=pc.max_context,
            tags=pc.tags,
        )
        registry.register(entry)
