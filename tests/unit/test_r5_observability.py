"""Tests for Phase R5: Observability and Tuning."""

import json
import os
import sqlite3
import tempfile

import pytest

from core.logging import MetricsCollector, reset_metrics_collector, get_metrics_collector
from core.routing import ModelRouter, EscalationCriteria, load_router_config
from data.db import get_initialized_connection
from data.dao_routing import (
    insert_routing_decision,
    get_decisions_for_run,
    get_tier_distribution,
    get_cost_by_provider,
)
from scripts.tune_router import (
    analyze_over_escalation,
    analyze_under_escalation,
    analyze_cost_optimization,
    suggest_thresholds,
)


# ---------------------------------------------------------------------------
# R5.1: MetricsCollector router metrics
# ---------------------------------------------------------------------------


class TestMetricsCollectorRouter:
    def setup_method(self):
        reset_metrics_collector()

    def test_record_routing_decision_tier_distribution(self):
        mc = MetricsCollector()
        mc.record_routing_decision(chosen_tier=0)
        mc.record_routing_decision(chosen_tier=0)
        mc.record_routing_decision(chosen_tier=2)
        mc.record_routing_decision(chosen_tier=3, escalated=True, request_tier=2)

        d = mc.to_dict()
        assert d["tier_distribution"] == {0: 2, 2: 1, 3: 1}

    def test_record_routing_decision_escalation(self):
        mc = MetricsCollector()
        mc.record_routing_decision(chosen_tier=2, escalated=True, request_tier=1)
        mc.record_routing_decision(chosen_tier=3, escalated=True, request_tier=2)
        mc.record_routing_decision(chosen_tier=1)

        assert mc.escalation_rate() == pytest.approx(2 / 3, abs=0.01)
        d = mc.to_dict()
        assert d["escalation_counts"] == {"1:2": 1, "2:3": 1}

    def test_record_routing_decision_provider(self):
        mc = MetricsCollector()
        mc.record_routing_decision(chosen_tier=3, provider="haiku", cost_usd=0.001)
        mc.record_routing_decision(chosen_tier=3, provider="haiku", cost_usd=0.002)
        mc.record_routing_decision(chosen_tier=2, provider="local")

        d = mc.to_dict()
        assert d["provider_distribution"] == {"haiku": 2, "local": 1}
        assert d["cost_by_provider"]["haiku"] == pytest.approx(0.003, abs=1e-6)

    def test_record_routing_decision_latency(self):
        mc = MetricsCollector()
        mc.record_routing_decision(chosen_tier=0, latency_ms=5.0)
        mc.record_routing_decision(chosen_tier=0, latency_ms=15.0)
        mc.record_routing_decision(chosen_tier=2, latency_ms=200.0)

        lats = mc.avg_latency_by_tier()
        assert lats[0] == 10.0
        assert lats[2] == 200.0

    def test_record_routing_decision_quality(self):
        mc = MetricsCollector()
        mc.record_routing_decision(chosen_tier=1, quality_score=0.8)
        mc.record_routing_decision(chosen_tier=1, quality_score=0.6)
        mc.record_routing_decision(chosen_tier=2, quality_score=0.9)

        q = mc.avg_quality_by_tier()
        assert q[1] == pytest.approx(0.7, abs=0.01)
        assert q[2] == 0.9

    def test_empty_router_metrics(self):
        mc = MetricsCollector()
        d = mc.to_dict()
        assert d["tier_distribution"] == {}
        assert d["escalation_rate"] == 0.0
        assert d["escalation_counts"] == {}
        assert d["provider_distribution"] == {}
        assert d["cost_by_provider"] == {}
        assert d["avg_latency_by_tier"] == {}
        assert d["avg_quality_by_tier"] == {}

    def test_to_dict_includes_all_router_fields(self):
        mc = MetricsCollector()
        mc.record_routing_decision(
            chosen_tier=3, provider="haiku",
            escalated=True, request_tier=2,
            latency_ms=150.0, quality_score=0.85, cost_usd=0.001,
        )
        d = mc.to_dict()
        # All new keys must be present
        for key in [
            "tier_distribution", "escalation_rate", "escalation_counts",
            "provider_distribution", "cost_by_provider",
            "avg_latency_by_tier", "avg_quality_by_tier",
        ]:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# R5.1: Routing decision persistence (DB)
# ---------------------------------------------------------------------------


class TestRoutingDecisionDB:
    @pytest.fixture
    def conn(self):
        c = get_initialized_connection(":memory:")
        yield c
        c.close()

    def test_insert_and_fetch(self, conn):
        insert_routing_decision(
            conn,
            decision_id="d1",
            run_id="run-1",
            node_id="scene_writing",
            agent_id="scene_writer",
            request_tier=2,
            chosen_tier=3,
            provider="haiku",
            escalation_reason="creative agent",
            confidence=0.9,
            latency_ms=150.0,
            tokens_in=1000,
            tokens_out=500,
            cost_usd=0.001,
            created_at="2026-01-01T00:00:00Z",
        )
        decisions = get_decisions_for_run(conn, "run-1")
        assert len(decisions) == 1
        d = decisions[0]
        assert d["agent_id"] == "scene_writer"
        assert d["chosen_tier"] == 3
        assert d["provider"] == "haiku"

    def test_tier_distribution(self, conn):
        for i, tier in enumerate([0, 0, 2, 3, 3, 3]):
            insert_routing_decision(
                conn,
                decision_id=f"d{i}",
                run_id="run-1",
                request_tier=0,
                chosen_tier=tier,
                created_at="2026-01-01T00:00:00Z",
            )
        dist = get_tier_distribution(conn, "run-1")
        dist_map = {d["chosen_tier"]: d["count"] for d in dist}
        assert dist_map == {0: 2, 2: 1, 3: 3}

    def test_cost_by_provider(self, conn):
        insert_routing_decision(
            conn, decision_id="d1", run_id="run-1",
            request_tier=2, chosen_tier=3, provider="haiku",
            cost_usd=0.001, created_at="2026-01-01T00:00:00Z",
        )
        insert_routing_decision(
            conn, decision_id="d2", run_id="run-1",
            request_tier=2, chosen_tier=3, provider="haiku",
            cost_usd=0.002, created_at="2026-01-01T00:00:00Z",
        )
        insert_routing_decision(
            conn, decision_id="d3", run_id="run-1",
            request_tier=2, chosen_tier=2, provider="local",
            cost_usd=0.0, created_at="2026-01-01T00:00:00Z",
        )
        costs = get_cost_by_provider(conn, "run-1")
        cost_map = {c["provider"]: c["total_cost"] for c in costs}
        assert cost_map["haiku"] == pytest.approx(0.003, abs=1e-6)

    def test_empty_run(self, conn):
        decisions = get_decisions_for_run(conn, "nonexistent")
        assert decisions == []


# ---------------------------------------------------------------------------
# R5.3: Threshold tuning analysis
# ---------------------------------------------------------------------------


class TestTuneRouter:
    @pytest.fixture
    def decisions(self):
        return [
            {
                "decision_id": "d1", "agent_id": "scene_writer",
                "confidence": 0.9, "quality_score": 0.85,
                "request_tier": 2, "chosen_tier": 3,
                "provider": "haiku", "cost_usd": 0.001,
                "latency_ms": 150.0, "escalation_reason": "creative",
            },
            {
                "decision_id": "d2", "agent_id": "canon_updater",
                "confidence": 0.8, "quality_score": 0.7,
                "request_tier": 2, "chosen_tier": 2,
                "provider": "local", "cost_usd": 0.0,
                "latency_ms": 50.0, "escalation_reason": None,
            },
            {
                "decision_id": "d3", "agent_id": "premise_architect",
                "confidence": 0.6, "quality_score": 0.5,
                "request_tier": 2, "chosen_tier": 3,
                "provider": "haiku", "cost_usd": 0.002,
                "latency_ms": 200.0, "escalation_reason": "low confidence",
            },
        ]

    def test_over_escalation(self, decisions):
        issues = analyze_over_escalation(decisions, confidence_threshold=0.75)
        # d1 has confidence 0.9 >= 0.75 and was escalated (tier 2 -> 3)
        assert len(issues) == 1
        assert issues[0]["agent_id"] == "scene_writer"

    def test_under_escalation(self, decisions):
        issues = analyze_under_escalation(decisions, quality_threshold=0.70)
        # d3 has quality 0.5 < 0.70 but was escalated, so not under-escalation
        # d2 has quality 0.7 which is not < 0.70
        # No under-escalation with these thresholds
        # Actually d3: chosen_tier=3 > request_tier=2, so it IS escalated. Not under.
        assert len(issues) == 0

    def test_under_escalation_detected(self):
        decisions = [
            {
                "decision_id": "d1", "agent_id": "contradiction",
                "confidence": 0.5, "quality_score": 0.3,
                "request_tier": 2, "chosen_tier": 2,
                "provider": "local", "cost_usd": 0.0,
                "latency_ms": 80.0, "escalation_reason": None,
            },
        ]
        issues = analyze_under_escalation(decisions, quality_threshold=0.70)
        assert len(issues) == 1
        assert issues[0]["agent_id"] == "contradiction"

    def test_cost_optimization(self, decisions):
        costs = analyze_cost_optimization(decisions)
        assert costs["total_cost_by_provider"]["haiku"] == pytest.approx(0.003, abs=1e-6)
        assert costs["call_count_by_provider"]["haiku"] == 2
        assert costs["call_count_by_provider"]["local"] == 1
        assert costs["avg_latency_ms"]["haiku"] == pytest.approx(175.0, abs=0.1)
        assert costs["avg_latency_ms"]["local"] == pytest.approx(50.0, abs=0.1)

    def test_suggest_thresholds(self, decisions):
        suggestions = suggest_thresholds(decisions)
        assert "confidence_threshold" in suggestions
        assert "quality_threshold" in suggestions
        assert "tier_distribution" in suggestions
        # Check tier distribution
        assert "3" in suggestions["tier_distribution"] or 3 in suggestions["tier_distribution"]

    def test_suggest_thresholds_empty(self):
        suggestions = suggest_thresholds([])
        # No confidence or quality data — no suggestions for those
        assert "confidence_threshold" not in suggestions
        assert "quality_threshold" not in suggestions


# ---------------------------------------------------------------------------
# R5.3/R5.4: Config hot-reload
# ---------------------------------------------------------------------------

_ROUTER_CONFIG_TEMPLATE = """\
tier1:
  model: "deepseek-r1:1.5b"
  context_length: 2048
  max_tokens: 128
  temperature: 0.0
  concurrency: 8
  timeout: {tier1_timeout}

tier2:
  model: "deepseek-r1:1.5b"
  context_length: 4096
  max_tokens: 1024
  temperature: 0.2
  concurrency: {tier2_concurrency}
  timeout: {tier2_timeout}

tier3_providers: []

escalation:
  min_confidence: {min_confidence}
  max_missing_citations: 2
  max_contradiction_ambiguity: 0.5
  synthesis_complexity_threshold: 0.8

provider_selection_strategy: "prefer_local"
daily_frontier_cap: 100
"""


class TestModelRouterReload:
    def test_reload_updates_escalation_criteria(self):
        router = ModelRouter(
            escalation_criteria=EscalationCriteria(min_confidence=0.5),
        )
        assert router.escalation_criteria.min_confidence == 0.5

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(_ROUTER_CONFIG_TEMPLATE.format(
                min_confidence=0.9,
                tier1_timeout=5.0,
                tier2_timeout=30.0,
                tier2_concurrency=4,
            ))
            f.flush()
            path = f.name

        try:
            router.reload_config(path)
            assert router.escalation_criteria.min_confidence == 0.9
            assert router.config is not None
            assert router.config.tier1.model == "deepseek-r1:1.5b"
        finally:
            os.unlink(path)

    def test_reload_preserves_adapters(self):
        from unittest.mock import MagicMock

        adapter = MagicMock()
        adapter.name = "local"
        router = ModelRouter()
        router.register_local(adapter)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(_ROUTER_CONFIG_TEMPLATE.format(
                min_confidence=0.8,
                tier1_timeout=5.0,
                tier2_timeout=30.0,
                tier2_concurrency=4,
            ))
            f.flush()
            path = f.name

        try:
            router.reload_config(path)
            # Adapter still registered
            assert "local" in router.local_adapters
        finally:
            os.unlink(path)


class TestDispatcherReload:
    def test_reload_updates_thresholds(self):
        from core.command_registry import CommandRegistry
        from core.tiered_dispatch import TieredDispatcher

        d = TieredDispatcher(
            command_registry=CommandRegistry(),
            confidence_threshold=0.75,
        )
        assert d.confidence_threshold == 0.75
        assert d.tier1_timeout == 5.0

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(_ROUTER_CONFIG_TEMPLATE.format(
                min_confidence=0.6,
                tier1_timeout=10.0,
                tier2_timeout=60.0,
                tier2_concurrency=2,
            ))
            f.flush()
            path = f.name

        try:
            d.reload_config(path)
            assert d.confidence_threshold == 0.6
            assert d.tier1_timeout == 10.0
            assert d.tier2_timeout == 60.0
        finally:
            os.unlink(path)

    def test_reload_updates_attached_router(self):
        from core.command_registry import CommandRegistry
        from core.tiered_dispatch import TieredDispatcher

        router = ModelRouter(
            escalation_criteria=EscalationCriteria(min_confidence=0.5),
        )
        d = TieredDispatcher(
            command_registry=CommandRegistry(),
            model_router=router,
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(_ROUTER_CONFIG_TEMPLATE.format(
                min_confidence=0.85,
                tier1_timeout=5.0,
                tier2_timeout=30.0,
                tier2_concurrency=4,
            ))
            f.flush()
            path = f.name

        try:
            d.reload_config(path)
            # Router's escalation criteria should also be updated
            assert router.escalation_criteria.min_confidence == 0.85
        finally:
            os.unlink(path)


class TestMakeRouterFromConfig:
    def test_creates_router_with_tiers(self):
        from core.adapters import make_router_from_config

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(_ROUTER_CONFIG_TEMPLATE.format(
                min_confidence=0.75,
                tier1_timeout=5.0,
                tier2_timeout=30.0,
                tier2_concurrency=4,
            ))
            f.flush()
            path = f.name

        try:
            router = make_router_from_config(path)
            assert "micro" in router.local_adapters
            assert "light" in router.local_adapters
            assert router.config is not None
            assert router.escalation_criteria.min_confidence == 0.75
        finally:
            os.unlink(path)
