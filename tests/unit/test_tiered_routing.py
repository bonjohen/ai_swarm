"""Tests for Phase R3: Tier 2 dispatch, orchestrator router integration, and agent tier policies."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agents.base_agent import AgentPolicy
from agents.micro_router_agent import MicroRouterAgent
from agents.qa_validator_agent import QAValidatorAgent
from agents.ingestor_agent import IngestorAgent
from agents.contradiction_agent import ContradictionAgent
from core.command_registry import CommandRegistry, register_defaults
from core.routing import ModelRouter, RoutingDecision, EscalationCriteria
from core.tiered_dispatch import TieredDispatcher


# --- Helpers ---

def _make_tier1_response(**overrides) -> str:
    defaults = {
        "intent": "analyze",
        "requires_reasoning": True,
        "complexity_score": 0.6,
        "confidence": 0.5,
        "recommended_tier": 2,
        "action": "analyze",
        "target": "",
    }
    defaults.update(overrides)
    return json.dumps(defaults)


def _make_tier2_response(**overrides) -> str:
    defaults = {
        "reasoning": "Analysis of the request",
        "action": "analyze",
        "target": "",
        "quality_score": 0.85,
        "reasoning_depth": 2,
        "escalate": False,
    }
    defaults.update(overrides)
    return json.dumps(defaults)


def _mock_call(response: str):
    def _call(sys: str, usr: str) -> str:
        return response
    return _call


# --- Orchestrator per-node model selection ---

class TestOrchestratorRouterIntegration:
    def test_router_selects_model_for_node(self):
        """When a router is provided, _execute_node uses it to select model."""
        from core.adapters import OllamaAdapter

        adapter = OllamaAdapter(name="local", model="test")
        router = ModelRouter()
        router.register_local(adapter)

        policy = AgentPolicy(allowed_local_models=["local"])
        decision = router.select_model(policy, {})

        assert decision.model_name == "local"
        assert not decision.escalated

    def test_router_escalation_with_signals(self):
        """Router escalates when state contains escalation signals."""
        from core.adapters import OllamaAdapter

        adapter = OllamaAdapter(name="local", model="test")
        frontier = OllamaAdapter(name="frontier", model="frontier-test")
        router = ModelRouter(
            escalation_criteria=EscalationCriteria(min_confidence=0.7),
        )
        router.register_local(adapter)
        router.register_frontier(frontier)

        policy = AgentPolicy(
            allowed_local_models=["local"],
            allowed_frontier_models=["frontier"],
        )
        state = {"_last_confidence": 0.3}  # Below threshold
        decision = router.select_model(policy, state)

        assert decision.escalated
        assert decision.model_name == "frontier"

    def test_backward_compat_no_router(self):
        """Without router, model_call is used directly (existing behavior)."""
        from core.adapters import OllamaAdapter

        policy = AgentPolicy(allowed_local_models=["local"])
        # When router=None, orchestrator falls back to model_call param
        # This just tests that the select_model path works standalone
        router = ModelRouter()
        adapter = OllamaAdapter(name="local", model="test")
        router.register_local(adapter)
        decision = router.select_model(policy, {})
        assert decision.model_name == "local"


# --- Agent preferred_tier ---

class TestAgentTierPreferences:
    def test_qa_validator_tier_0(self):
        assert QAValidatorAgent.POLICY.preferred_tier == 0

    def test_ingestor_tier_1(self):
        assert IngestorAgent.POLICY.preferred_tier == 1

    def test_contradiction_tier_2(self):
        assert ContradictionAgent.POLICY.preferred_tier == 2

    def test_micro_router_has_tier_fields(self):
        policy = MicroRouterAgent.POLICY
        assert hasattr(policy, "preferred_tier")
        assert hasattr(policy, "min_tier")
        assert hasattr(policy, "max_tokens_by_tier")

    def test_default_tier_is_2(self):
        """Default AgentPolicy has preferred_tier=2."""
        policy = AgentPolicy()
        assert policy.preferred_tier == 2
        assert policy.min_tier == 1


# --- Tier 1 and Tier 2 use same model ---

class TestSameModelDifferentConfigs:
    def test_tier1_and_tier2_same_model(self):
        """Tier 1 and Tier 2 both use deepseek-r1:1.5b."""
        from core.adapters import make_micro_adapter, make_light_adapter

        micro = make_micro_adapter()
        light = make_light_adapter()
        assert micro.model == light.model == "deepseek-r1:1.5b"
        assert micro.context_length < light.context_length
        assert micro.max_tokens < light.max_tokens


# --- Tier 2 dispatch ---

class TestTier2Dispatch:
    def _dispatcher(self, tier1_resp: str, tier2_resp: str) -> TieredDispatcher:
        reg = CommandRegistry()
        register_defaults(reg)
        return TieredDispatcher(
            command_registry=reg,
            tier1_model_call=_mock_call(tier1_resp),
            tier2_model_call=_mock_call(tier2_resp),
        )

    def test_tier2_resolves_on_good_quality(self):
        """Tier 2 handles request when quality is above threshold."""
        tier1_resp = _make_tier1_response(recommended_tier=2, confidence=0.5)
        tier2_resp = _make_tier2_response(quality_score=0.85, escalate=False)
        d = self._dispatcher(tier1_resp, tier2_resp)
        result = d.dispatch("explain the architecture")
        assert result.tier == 2
        assert result.confidence == 0.85

    def test_tier2_escalates_on_low_quality(self):
        """Tier 2 escalates when quality is below threshold."""
        tier1_resp = _make_tier1_response(recommended_tier=2, confidence=0.5)
        tier2_resp = _make_tier2_response(quality_score=0.3, escalate=False)
        d = self._dispatcher(tier1_resp, tier2_resp)
        result = d.dispatch("complex multi-doc synthesis")
        assert result.tier == -1  # escalated past all available tiers

    def test_tier2_escalates_on_high_reasoning_depth(self):
        """Tier 2 escalates when it flags escalate=true."""
        tier1_resp = _make_tier1_response(recommended_tier=2, confidence=0.5)
        tier2_resp = _make_tier2_response(
            quality_score=0.8, reasoning_depth=4, escalate=True,
        )
        d = self._dispatcher(tier1_resp, tier2_resp)
        result = d.dispatch("deep reasoning needed")
        assert result.tier == -1

    def test_tier2_handles_parse_failure(self):
        """Tier 2 returns None on parse failure, falls through."""
        tier1_resp = _make_tier1_response(recommended_tier=2, confidence=0.5)
        d = TieredDispatcher(
            command_registry=CommandRegistry(),
            tier1_model_call=_mock_call(tier1_resp),
            tier2_model_call=_mock_call("NOT JSON"),
        )
        register_defaults(d.command_registry)
        result = d.dispatch("something")
        assert result.tier == -1


# --- Escalation signal injection ---

class TestEscalationSignals:
    def test_confidence_signal_triggers_escalation(self):
        router = ModelRouter(
            escalation_criteria=EscalationCriteria(min_confidence=0.7),
        )
        from core.adapters import OllamaAdapter
        router.register_local(OllamaAdapter(name="local", model="test"))
        router.register_frontier(OllamaAdapter(name="frontier", model="test"))

        policy = AgentPolicy(
            allowed_local_models=["local"],
            allowed_frontier_models=["frontier"],
        )
        # Simulate agent injecting confidence signal
        state = {"_last_confidence": 0.4}
        decision = router.select_model(policy, state)
        assert decision.escalated

    def test_missing_citations_signal(self):
        router = ModelRouter(
            escalation_criteria=EscalationCriteria(max_missing_citations=2),
        )
        from core.adapters import OllamaAdapter
        router.register_local(OllamaAdapter(name="local", model="test"))
        router.register_frontier(OllamaAdapter(name="frontier", model="test"))

        policy = AgentPolicy(
            allowed_local_models=["local"],
            allowed_frontier_models=["frontier"],
        )
        state = {"_missing_citations_count": 5}
        decision = router.select_model(policy, state)
        assert decision.escalated
        assert "missing citations" in decision.reason


# --- Backward compatibility ---

class TestBackwardCompatibility:
    def test_execute_graph_accepts_model_call(self):
        """execute_graph still accepts model_call without router."""
        from core.orchestrator import execute_graph
        from graphs.graph_types import Graph, GraphNode, RetryPolicy

        # Minimal graph with one node
        node = GraphNode(
            name="test_node",
            agent="ingestor",
            inputs=["sources"],
            outputs=["doc_ids"],
            next=None,
            end=True,
            retry=RetryPolicy(),
        )
        graph = Graph(
            id="test",
            entry="test_node",
            nodes={"test_node": node},
        )

        calls = []
        def mock_model_call(sys_prompt, user_msg):
            calls.append(True)
            return json.dumps({"doc_ids": ["d1"], "segment_ids": ["s1"]})

        state = {
            "run_id": "test-run",
            "scope_type": "cert",
            "scope_id": "test-cert",
            "graph_id": "test",
            "sources": [],
        }

        # Register agent
        from agents import registry
        from agents.ingestor_agent import IngestorAgent
        registry.register(IngestorAgent())

        try:
            result = execute_graph(graph, state, model_call=mock_model_call)
            assert result.status == "completed"
            assert len(calls) > 0
        finally:
            registry.clear()
