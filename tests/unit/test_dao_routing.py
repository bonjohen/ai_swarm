"""Tests for data.dao_routing — routing_decisions telemetry."""

import pytest
from data.db import get_initialized_connection
from data.dao_routing import (
    insert_routing_decision,
    get_decisions_for_run,
    get_tier_distribution,
    get_cost_by_provider,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


class TestInsertAndGet:
    def test_round_trip(self, conn) -> None:
        insert_routing_decision(
            conn,
            decision_id="d1",
            run_id="r1",
            node_id="ingest",
            agent_id="ingestor",
            request_tier=1,
            chosen_tier=2,
            provider="local",
            escalation_reason="low confidence",
            confidence=0.5,
            complexity_score=0.3,
            quality_score=0.8,
            latency_ms=120.5,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            created_at="2026-01-01T00:00:00Z",
        )
        decisions = get_decisions_for_run(conn, "r1")
        assert len(decisions) == 1
        d = decisions[0]
        assert d["decision_id"] == "d1"
        assert d["request_tier"] == 1
        assert d["chosen_tier"] == 2
        assert d["provider"] == "local"
        assert d["escalation_reason"] == "low confidence"
        assert d["confidence"] == 0.5
        assert d["tokens_in"] == 100
        assert d["cost_usd"] == 0.001

    def test_multiple_decisions_ordered(self, conn) -> None:
        for i in range(3):
            insert_routing_decision(
                conn,
                decision_id=f"d{i}",
                run_id="r1",
                request_tier=1,
                chosen_tier=i + 1,
                created_at=f"2026-01-01T00:0{i}:00Z",
            )
        decisions = get_decisions_for_run(conn, "r1")
        assert len(decisions) == 3
        assert decisions[0]["decision_id"] == "d0"
        assert decisions[2]["decision_id"] == "d2"

    def test_empty_run(self, conn) -> None:
        decisions = get_decisions_for_run(conn, "nonexistent")
        assert decisions == []


class TestTierDistribution:
    def test_distribution(self, conn) -> None:
        insert_routing_decision(conn, decision_id="d1", run_id="r1", request_tier=1, chosen_tier=1, created_at="2026-01-01T00:00:00Z")
        insert_routing_decision(conn, decision_id="d2", run_id="r1", request_tier=1, chosen_tier=2, created_at="2026-01-01T00:01:00Z")
        insert_routing_decision(conn, decision_id="d3", run_id="r1", request_tier=1, chosen_tier=2, created_at="2026-01-01T00:02:00Z")
        insert_routing_decision(conn, decision_id="d4", run_id="r1", request_tier=2, chosen_tier=3, created_at="2026-01-01T00:03:00Z")

        dist = get_tier_distribution(conn, run_id="r1")
        tier_map = {d["chosen_tier"]: d["count"] for d in dist}
        assert tier_map[1] == 1
        assert tier_map[2] == 2
        assert tier_map[3] == 1

    def test_distribution_all_runs(self, conn) -> None:
        insert_routing_decision(conn, decision_id="d1", run_id="r1", request_tier=1, chosen_tier=1, created_at="2026-01-01T00:00:00Z")
        insert_routing_decision(conn, decision_id="d2", run_id="r2", request_tier=1, chosen_tier=1, created_at="2026-01-01T00:01:00Z")

        dist = get_tier_distribution(conn)
        assert len(dist) == 1
        assert dist[0]["count"] == 2


class TestCostByProvider:
    def test_cost_aggregation(self, conn) -> None:
        insert_routing_decision(conn, decision_id="d1", run_id="r1", request_tier=1, chosen_tier=2, provider="local", cost_usd=0.001, created_at="2026-01-01T00:00:00Z")
        insert_routing_decision(conn, decision_id="d2", run_id="r1", request_tier=1, chosen_tier=3, provider="anthropic", cost_usd=0.05, created_at="2026-01-01T00:01:00Z")
        insert_routing_decision(conn, decision_id="d3", run_id="r1", request_tier=2, chosen_tier=3, provider="anthropic", cost_usd=0.03, created_at="2026-01-01T00:02:00Z")

        costs = get_cost_by_provider(conn, run_id="r1")
        cost_map = {c["provider"]: c["total_cost"] for c in costs}
        assert cost_map["local"] == pytest.approx(0.001)
        assert cost_map["anthropic"] == pytest.approx(0.08)

    def test_cost_all_runs(self, conn) -> None:
        insert_routing_decision(conn, decision_id="d1", run_id="r1", request_tier=1, chosen_tier=1, provider="local", cost_usd=0.01, created_at="2026-01-01T00:00:00Z")
        insert_routing_decision(conn, decision_id="d2", run_id="r2", request_tier=1, chosen_tier=1, provider="local", cost_usd=0.02, created_at="2026-01-01T00:01:00Z")

        costs = get_cost_by_provider(conn)
        assert len(costs) == 1
        assert costs[0]["total_cost"] == pytest.approx(0.03)
