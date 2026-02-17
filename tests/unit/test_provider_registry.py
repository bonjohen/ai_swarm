"""Tests for core.provider_registry — ProviderRegistry and selection strategies."""

from __future__ import annotations

import pytest

from core.provider_registry import ProviderEntry, ProviderRegistry, TaskRequirements


class FakeAdapter:
    def __init__(self, name: str):
        self.name = name

    def call(self, system_prompt: str, user_message: str) -> str:
        return "ok"


def _entry(
    name: str,
    cost_in: float = 0.001,
    cost_out: float = 0.002,
    quality: float = 0.8,
    max_ctx: int = 4096,
    tags: list[str] | None = None,
    available: bool = True,
) -> ProviderEntry:
    return ProviderEntry(
        name=name,
        adapter=FakeAdapter(name),
        provider_type="test",
        cost_per_1k_input=cost_in,
        cost_per_1k_output=cost_out,
        quality_score=quality,
        max_context=max_ctx,
        tags=tags or [],
        available=available,
    )


class TestProviderRegistration:
    def test_register_and_get(self) -> None:
        reg = ProviderRegistry()
        entry = _entry("p1")
        reg.register(entry)
        assert reg.get("p1") is entry

    def test_get_missing(self) -> None:
        reg = ProviderRegistry()
        assert reg.get("nonexistent") is None

    def test_list_available(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("p1"))
        reg.register(_entry("p2", available=False))
        reg.register(_entry("p3"))
        available = reg.list_available()
        names = [p.name for p in available]
        assert "p1" in names
        assert "p3" in names
        assert "p2" not in names


class TestCheapestQualified:
    def test_selects_cheapest(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("expensive", cost_in=0.01, cost_out=0.02, quality=0.9))
        reg.register(_entry("cheap", cost_in=0.001, cost_out=0.002, quality=0.85))
        reg.register(_entry("mid", cost_in=0.005, cost_out=0.01, quality=0.88))

        result = reg.select_provider(TaskRequirements(min_quality=0.8), "cheapest_qualified")
        assert result is not None
        assert result.name == "cheap"

    def test_filters_by_min_quality(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("low_q", cost_in=0.001, cost_out=0.001, quality=0.3))
        reg.register(_entry("high_q", cost_in=0.01, cost_out=0.01, quality=0.9))

        result = reg.select_provider(TaskRequirements(min_quality=0.5), "cheapest_qualified")
        assert result is not None
        assert result.name == "high_q"


class TestHighestQuality:
    def test_selects_highest_quality(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("low", quality=0.7, cost_in=0.001, cost_out=0.001))
        reg.register(_entry("high", quality=0.95, cost_in=0.01, cost_out=0.02))
        reg.register(_entry("mid", quality=0.85, cost_in=0.005, cost_out=0.01))

        result = reg.select_provider(TaskRequirements(), "highest_quality")
        assert result is not None
        assert result.name == "high"

    def test_filters_by_max_cost(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("cheap", quality=0.8, cost_in=0.001, cost_out=0.001))
        reg.register(_entry("expensive", quality=0.95, cost_in=0.1, cost_out=0.2))

        result = reg.select_provider(TaskRequirements(max_cost_per_1k=0.01), "highest_quality")
        assert result is not None
        assert result.name == "cheap"


class TestPreferLocal:
    def test_prefers_local_over_cloud(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("cloud_best", quality=0.95, tags=["cloud"]))
        reg.register(_entry("local_good", quality=0.85, tags=["local"]))

        result = reg.select_provider(TaskRequirements(), "prefer_local")
        assert result is not None
        assert result.name == "local_good"

    def test_falls_back_to_cloud(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("cloud1", quality=0.9, tags=["cloud"]))
        reg.register(_entry("cloud2", quality=0.95, tags=["cloud"]))

        result = reg.select_provider(TaskRequirements(), "prefer_local")
        assert result is not None
        assert result.name == "cloud2"  # highest quality cloud


class TestNoMatch:
    def test_returns_none_when_no_providers(self) -> None:
        reg = ProviderRegistry()
        result = reg.select_provider(TaskRequirements())
        assert result is None

    def test_returns_none_when_no_match(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("low_q", quality=0.3))
        result = reg.select_provider(TaskRequirements(min_quality=0.9))
        assert result is None

    def test_returns_none_context_too_small(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("small", max_ctx=2048))
        result = reg.select_provider(TaskRequirements(min_context=8192))
        assert result is None


class TestAvailability:
    def test_unavailable_excluded(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("best", quality=0.95, available=False))
        reg.register(_entry("ok", quality=0.7, available=True))

        result = reg.select_provider(TaskRequirements(), "highest_quality")
        assert result is not None
        assert result.name == "ok"

    def test_unknown_strategy_raises(self) -> None:
        reg = ProviderRegistry()
        reg.register(_entry("p1"))
        with pytest.raises(ValueError, match="Unknown selection strategy"):
            reg.select_provider(TaskRequirements(), "nonexistent_strategy")
