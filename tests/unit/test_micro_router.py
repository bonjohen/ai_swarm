"""Tests for the micro router agent and Tier 1 dispatch (Phase R2)."""

from __future__ import annotations

import json

import pytest

from agents.micro_router_agent import MicroRouterAgent
from core.command_registry import CommandRegistry, register_defaults
from core.routing import compute_routing_score, DEFAULT_ROUTING_WEIGHTS, DEFAULT_ROUTING_THRESHOLD
from core.tiered_dispatch import TieredDispatcher


# --- Helpers ---

def _make_tier1_response(
    intent: str = "run_cert",
    requires_reasoning: bool = False,
    complexity_score: float = 0.1,
    confidence: float = 0.9,
    recommended_tier: int = 1,
    action: str = "execute_graph",
    target: str = "run_cert.py",
) -> str:
    """Build a JSON response string mimicking Tier 1 output."""
    return json.dumps({
        "intent": intent,
        "requires_reasoning": requires_reasoning,
        "complexity_score": complexity_score,
        "confidence": confidence,
        "recommended_tier": recommended_tier,
        "action": action,
        "target": target,
    })


def _mock_model_call(response: str):
    """Return a model callable that always returns *response*."""
    def _call(system_prompt: str, user_message: str) -> str:
        return response
    return _call


def _failing_model_call(system_prompt: str, user_message: str) -> str:
    """Model callable that returns invalid JSON."""
    return "NOT VALID JSON AT ALL"


# --- MicroRouterAgent parse/validate ---

class TestMicroRouterAgentParse:
    def test_parse_valid_response(self):
        agent = MicroRouterAgent()
        raw = _make_tier1_response()
        delta = agent.parse(raw)
        assert delta["intent"] == "run_cert"
        assert delta["confidence"] == 0.9
        assert delta["recommended_tier"] == 1
        assert delta["action"] == "execute_graph"

    def test_validate_valid(self):
        agent = MicroRouterAgent()
        delta = agent.parse(_make_tier1_response())
        agent.validate(delta)  # should not raise

    def test_validate_confidence_out_of_range(self):
        agent = MicroRouterAgent()
        delta = agent.parse(_make_tier1_response(confidence=1.5))
        with pytest.raises(ValueError, match="confidence"):
            agent.validate(delta)

    def test_validate_complexity_out_of_range(self):
        agent = MicroRouterAgent()
        delta = agent.parse(_make_tier1_response(complexity_score=-0.1))
        with pytest.raises(ValueError, match="complexity_score"):
            agent.validate(delta)

    def test_validate_invalid_tier(self):
        agent = MicroRouterAgent()
        delta = agent.parse(_make_tier1_response(recommended_tier=5))
        with pytest.raises(ValueError, match="recommended_tier"):
            agent.validate(delta)

    def test_validate_empty_intent(self):
        agent = MicroRouterAgent()
        delta = agent.parse(_make_tier1_response(intent=""))
        with pytest.raises(ValueError, match="intent"):
            agent.validate(delta)


# --- Tier 1 classification in TieredDispatcher ---

class TestTier1Classification:
    def _dispatcher(self, response: str) -> TieredDispatcher:
        reg = CommandRegistry()
        register_defaults(reg)
        return TieredDispatcher(
            command_registry=reg,
            tier1_model_call=_mock_model_call(response),
        )

    def test_simple_command_no_escalation(self):
        """Tier 1 with high confidence and tier=1 resolves directly."""
        resp = _make_tier1_response(confidence=0.9, recommended_tier=1)
        d = self._dispatcher(resp)
        result = d.dispatch("run the certification for az-104")
        assert result.tier == 1
        assert result.action == "execute_graph"
        assert result.confidence == 0.9

    def test_escalation_on_low_confidence(self):
        """Low confidence triggers escalation (returns needs_escalation)."""
        resp = _make_tier1_response(confidence=0.3, recommended_tier=1)
        d = self._dispatcher(resp)
        result = d.dispatch("something ambiguous")
        # Should escalate — tier 1 not confident
        assert result.tier == -1
        assert result.action == "needs_escalation"

    def test_escalation_on_high_complexity(self):
        """High complexity + low confidence → escalation via routing score."""
        resp = _make_tier1_response(
            complexity_score=0.9,
            confidence=0.5,
            recommended_tier=1,
        )
        d = self._dispatcher(resp)
        result = d.dispatch("complex multi-document synthesis")
        assert result.tier == -1  # escalated

    def test_escalation_on_recommended_tier_2(self):
        """When Tier 1 itself recommends tier=2, it escalates."""
        resp = _make_tier1_response(confidence=0.95, recommended_tier=2)
        d = self._dispatcher(resp)
        result = d.dispatch("explain the architecture in detail")
        assert result.tier == -1

    def test_tier0_takes_priority_over_tier1(self):
        """Slash commands are handled by Tier 0, not Tier 1."""
        resp = _make_tier1_response()  # would match Tier 1
        d = self._dispatcher(resp)
        result = d.dispatch("/cert az-104")
        assert result.tier == 0  # Tier 0 wins

    def test_validation_failure_escalates_after_retries(self):
        """Invalid model output → retries exhausted → escalation."""
        reg = CommandRegistry()
        register_defaults(reg)
        d = TieredDispatcher(
            command_registry=reg,
            tier1_model_call=_failing_model_call,
        )
        result = d.dispatch("something that needs routing")
        assert result.tier == -1
        assert result.action == "needs_escalation"


# --- Composite routing score ---

class TestCompositeRoutingScore:
    def test_default_weights(self):
        # complexity=0.5, confidence=0.8, hallucination_risk=0.0
        score = compute_routing_score(0.5, 0.8, 0.0)
        # (0.5 * 0.4) + (0.2 * 0.3) + (0.0 * 0.3) = 0.20 + 0.06 + 0 = 0.26
        assert abs(score - 0.26) < 1e-9

    def test_high_complexity_high_score(self):
        score = compute_routing_score(1.0, 0.0, 1.0)
        # (1.0 * 0.4) + (1.0 * 0.3) + (1.0 * 0.3) = 1.0
        assert abs(score - 1.0) < 1e-9

    def test_low_complexity_high_confidence(self):
        score = compute_routing_score(0.0, 1.0, 0.0)
        assert abs(score - 0.0) < 1e-9

    def test_custom_weights(self):
        score = compute_routing_score(0.5, 0.5, 0.5, weights=(0.5, 0.25, 0.25))
        # (0.5 * 0.5) + (0.5 * 0.25) + (0.5 * 0.25) = 0.25 + 0.125 + 0.125 = 0.5
        assert abs(score - 0.5) < 1e-9

    def test_threshold_constant(self):
        assert DEFAULT_ROUTING_THRESHOLD == 0.5
