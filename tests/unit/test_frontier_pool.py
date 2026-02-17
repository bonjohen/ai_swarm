"""Tests for Phase R4: Tier 3 frontier pool, cap enforcement, provider fallback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.command_registry import CommandRegistry, register_defaults
from core.errors import RoutingFailure
from core.provider_registry import (
    ProviderEntry,
    ProviderRegistry,
    TaskRequirements,
    load_providers_from_config,
)
from core.routing import ProviderConfig, RouterConfig, TierConfig, EscalationCriteria, load_router_config
from core.tiered_dispatch import TieredDispatcher


def _make_entry(name: str, cost: float = 0.01, quality: float = 0.8,
                tags: list[str] | None = None, available: bool = True) -> ProviderEntry:
    return ProviderEntry(
        name=name,
        adapter=MagicMock(),
        provider_type="mock",
        cost_per_1k_input=cost,
        cost_per_1k_output=cost,
        quality_score=quality,
        max_context=8192,
        tags=tags or [],
        available=available,
    )


class TestProviderFallback:
    def test_fallback_when_first_unavailable(self):
        """If first-choice provider is unavailable, falls back to next."""
        reg = ProviderRegistry()
        reg.register(_make_entry("best", cost=0.001, quality=0.95, available=False))
        reg.register(_make_entry("backup", cost=0.01, quality=0.85))

        result = reg.select_provider_with_fallback(TaskRequirements())
        assert result is not None
        assert result.name == "backup"

    def test_all_unavailable_returns_none(self):
        reg = ProviderRegistry()
        reg.register(_make_entry("a", available=False))
        reg.register(_make_entry("b", available=False))

        result = reg.select_provider_with_fallback(TaskRequirements())
        assert result is None

    def test_mark_unavailable_then_available(self):
        reg = ProviderRegistry()
        reg.register(_make_entry("test"))
        assert reg.get("test").available

        reg.mark_unavailable("test")
        assert not reg.get("test").available

        reg.mark_available("test")
        assert reg.get("test").available


class TestDailyFrontierCap:
    def test_cap_not_exceeded_initially(self):
        reg = ProviderRegistry(daily_cap=3)
        assert not reg.is_cap_exceeded()
        assert reg.daily_calls_today() == 0

    def test_cap_enforcement_allows_then_denies(self):
        reg = ProviderRegistry(daily_cap=2)
        reg.register(_make_entry("provider"))

        # First two calls: allowed
        reg.record_call("provider")
        assert not reg.is_cap_exceeded()
        reg.record_call("provider")
        assert reg.is_cap_exceeded()

        # select_provider_with_fallback returns None when cap exceeded
        result = reg.select_provider_with_fallback(TaskRequirements())
        assert result is None

    def test_cap_tracks_per_day(self):
        reg = ProviderRegistry(daily_cap=5)
        reg.record_call("a")
        reg.record_call("a")
        assert reg.daily_calls_today() == 2


class TestFullEscalationChain:
    def _make_tier1_response(self, **overrides):
        defaults = {
            "intent": "complex_analysis",
            "requires_reasoning": True,
            "complexity_score": 0.8,
            "confidence": 0.4,
            "recommended_tier": 3,
            "action": "analyze",
            "target": "",
        }
        defaults.update(overrides)
        return json.dumps(defaults)

    def _make_tier2_response(self, **overrides):
        defaults = {
            "reasoning": "Needs frontier model",
            "action": "analyze",
            "target": "",
            "quality_score": 0.3,
            "reasoning_depth": 4,
            "escalate": True,
        }
        defaults.update(overrides)
        return json.dumps(defaults)

    def test_tier1_to_tier2_to_needs_escalation(self):
        """Full chain: Tier 1 → Tier 2 → needs_escalation (no Tier 3 configured)."""
        reg = CommandRegistry()
        register_defaults(reg)

        d = TieredDispatcher(
            command_registry=reg,
            tier1_model_call=lambda s, u: self._make_tier1_response(),
            tier2_model_call=lambda s, u: self._make_tier2_response(),
        )
        result = d.dispatch("very complex multi-document synthesis")
        assert result.tier == -1
        assert result.action == "needs_escalation"

    def test_tier1_resolves_simple(self):
        """Simple request resolved by Tier 1."""
        reg = CommandRegistry()
        register_defaults(reg)

        simple_resp = self._make_tier1_response(
            confidence=0.9,
            complexity_score=0.1,
            recommended_tier=1,
        )
        d = TieredDispatcher(
            command_registry=reg,
            tier1_model_call=lambda s, u: simple_resp,
        )
        result = d.dispatch("list available certifications")
        assert result.tier == 1

    def test_tier2_resolves_medium(self):
        """Medium request: Tier 1 escalates, Tier 2 handles."""
        reg = CommandRegistry()
        register_defaults(reg)

        tier1_resp = self._make_tier1_response(
            confidence=0.5,
            recommended_tier=2,
        )
        tier2_resp = self._make_tier2_response(
            quality_score=0.85,
            escalate=False,
        )
        d = TieredDispatcher(
            command_registry=reg,
            tier1_model_call=lambda s, u: tier1_resp,
            tier2_model_call=lambda s, u: tier2_resp,
        )
        result = d.dispatch("explain the claim extraction pipeline")
        assert result.tier == 2
        assert result.confidence == 0.85


class TestProviderFailover:
    def test_first_provider_fails_try_next(self):
        """When first provider is marked unavailable, selects next."""
        reg = ProviderRegistry()
        reg.register(_make_entry("primary", quality=0.95, cost=0.01, tags=["local"]))
        reg.register(_make_entry("secondary", quality=0.85, cost=0.02, tags=["cloud"]))

        # Simulate primary failure
        reg.mark_unavailable("primary")
        result = reg.select_provider_with_fallback(
            TaskRequirements(), strategy="prefer_local",
        )
        assert result is not None
        assert result.name == "secondary"

    def test_all_providers_fail(self):
        """All providers unavailable returns None."""
        reg = ProviderRegistry()
        reg.register(_make_entry("a"))
        reg.register(_make_entry("b"))
        reg.mark_unavailable("a")
        reg.mark_unavailable("b")

        result = reg.select_provider_with_fallback(TaskRequirements())
        assert result is None


class TestRoutingFailureError:
    def test_routing_failure_structure(self):
        exc = RoutingFailure(tier=3, message="all providers failed",
                             tried_providers=["a", "b"])
        assert exc.tier == 3
        assert exc.tried_providers == ["a", "b"]
        assert "tier 3" in str(exc)

    def test_routing_failure_caught_in_orchestrator(self):
        """RoutingFailure is a SwarmError and can be caught."""
        from core.errors import SwarmError
        exc = RoutingFailure(tier=3, message="test")
        assert isinstance(exc, SwarmError)


class TestLoadProvidersFromConfig:
    def test_loads_from_router_config(self):
        """load_providers_from_config creates entries from ProviderConfig list."""
        configs = [
            ProviderConfig(
                name="test_dgx",
                provider_type="dgx",
                model="llama3:70b",
                host="http://localhost:11434",
                cost_per_1k_input=0.001,
                cost_per_1k_output=0.002,
                quality_score=0.85,
                max_context=8192,
                tags=["local", "dgx"],
            ),
            ProviderConfig(
                name="test_anthropic",
                provider_type="anthropic",
                model="claude-sonnet-4-5-20250929",
                cost_per_1k_input=0.003,
                cost_per_1k_output=0.015,
                quality_score=0.95,
                max_context=200000,
                tags=["cloud"],
            ),
        ]
        reg = ProviderRegistry()
        load_providers_from_config(reg, configs)

        assert reg.get("test_dgx") is not None
        assert reg.get("test_anthropic") is not None
        assert reg.get("test_dgx").quality_score == 0.85
        assert len(reg.list_available()) == 2


class TestIntegrationGraphWithTiers:
    def test_graph_run_with_mock_models(self):
        """Integration: full cert graph node with routing via router."""
        from core.orchestrator import execute_graph
        from core.routing import ModelRouter
        from graphs.graph_types import Graph, GraphNode, RetryPolicy
        from agents import registry
        from agents.ingestor_agent import IngestorAgent

        # Set up router with a mock adapter that returns valid JSON
        mock_adapter = MagicMock()
        mock_adapter.name = "local"
        mock_adapter.call.side_effect = lambda s, u: json.dumps(
            {"doc_ids": ["d1"], "segment_ids": ["s1"]}
        )
        router = ModelRouter()
        router.register_local(mock_adapter)

        node = GraphNode(
            name="test_node",
            agent="ingestor",
            inputs=["sources"],
            outputs=["doc_ids"],
            next=None,
            end=True,
            retry=RetryPolicy(),
        )
        graph = Graph(id="test", entry="test_node", nodes={"test_node": node})

        def mock_call(sys_prompt, user_msg):
            return json.dumps({"doc_ids": ["d1"], "segment_ids": ["s1"]})

        state = {
            "run_id": "int-test",
            "scope_type": "cert",
            "scope_id": "az-104",
            "graph_id": "test",
            "sources": [],
        }

        registry.register(IngestorAgent())
        try:
            # With model_call (backward compat)
            result = execute_graph(graph, state.copy(), model_call=mock_call)
            assert result.status == "completed"

            # With router
            result2 = execute_graph(graph, state.copy(), model_call=mock_call, router=router)
            assert result2.status == "completed"
        finally:
            registry.clear()
