"""Tests for model routing with escalation logic."""

import pytest
from agents.base_agent import AgentPolicy
from core.routing import (
    EscalationCriteria,
    ModelRouter,
    RoutingDecision,
    set_router,
    select_model,
)


class FakeAdapter:
    def __init__(self, name: str, response: str = "ok"):
        self.name = name
        self._response = response

    def call(self, system_prompt: str, user_message: str) -> str:
        return self._response


@pytest.fixture
def router():
    r = ModelRouter(escalation_criteria=EscalationCriteria(min_confidence=0.7))
    r.register_local(FakeAdapter("local"))
    r.register_frontier(FakeAdapter("frontier"))
    return r


def _policy(**overrides):
    defaults = dict(allowed_local_models=["local"], allowed_frontier_models=["frontier"])
    defaults.update(overrides)
    return AgentPolicy(**defaults)


class TestLocalFirst:
    def test_defaults_to_local(self, router):
        decision = router.select_model(_policy(), {})
        assert decision.model_name == "local"
        assert not decision.escalated

    def test_no_escalation_without_signals(self, router):
        decision = router.select_model(_policy(), {"some_key": "value"})
        assert not decision.escalated


class TestEscalation:
    def test_low_confidence_escalates(self, router):
        state = {"_last_confidence": 0.3}
        decision = router.select_model(_policy(), state)
        assert decision.escalated
        assert "low confidence" in decision.reason

    def test_missing_citations_escalates(self, router):
        state = {"_missing_citations_count": 5}
        decision = router.select_model(_policy(), state)
        assert decision.escalated
        assert "missing citations" in decision.reason

    def test_contradiction_ambiguity_escalates(self, router):
        state = {"_contradiction_ambiguity": 0.9}
        decision = router.select_model(_policy(), state)
        assert decision.escalated
        assert "contradiction ambiguity" in decision.reason

    def test_synthesis_complexity_escalates(self, router):
        state = {"_synthesis_complexity": 0.95}
        decision = router.select_model(_policy(), state)
        assert decision.escalated
        assert "synthesis complexity" in decision.reason

    def test_no_frontier_models_stays_local(self, router):
        policy = _policy(allowed_frontier_models=[])
        state = {"_last_confidence": 0.1}
        decision = router.select_model(policy, state)
        assert not decision.escalated  # no frontier to escalate to

    def test_multiple_reasons(self, router):
        state = {"_last_confidence": 0.3, "_missing_citations_count": 10}
        decision = router.select_model(_policy(), state)
        assert decision.escalated
        assert "low confidence" in decision.reason
        assert "missing citations" in decision.reason


class TestModelCallable:
    def test_get_local_callable(self, router):
        decision = RoutingDecision(model_name="local", reason="test", escalated=False)
        fn = router.get_model_callable(decision)
        assert fn("sys", "user") == "ok"

    def test_get_frontier_callable(self, router):
        decision = RoutingDecision(model_name="frontier", reason="test", escalated=True)
        fn = router.get_model_callable(decision)
        assert fn("sys", "user") == "ok"

    def test_missing_adapter_raises(self, router):
        decision = RoutingDecision(model_name="nonexistent", reason="test", escalated=False)
        with pytest.raises(RuntimeError, match="No adapter registered"):
            router.get_model_callable(decision)


class TestModuleLevelFunctions:
    def test_select_model_uses_default_router(self, router):
        set_router(router)
        decision = select_model(_policy(), {})
        assert decision.model_name == "local"
