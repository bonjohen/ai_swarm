"""DAO for routing_decisions telemetry."""

from __future__ import annotations

import sqlite3
from typing import Any


def insert_routing_decision(
    conn: sqlite3.Connection,
    *,
    decision_id: str,
    run_id: str | None = None,
    node_id: str | None = None,
    agent_id: str | None = None,
    request_tier: int,
    chosen_tier: int,
    provider: str | None = None,
    escalation_reason: str | None = None,
    confidence: float | None = None,
    complexity_score: float | None = None,
    quality_score: float | None = None,
    latency_ms: float | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: float | None = None,
    created_at: str,
) -> None:
    conn.execute(
        """INSERT INTO routing_decisions
           (decision_id, run_id, node_id, agent_id, request_tier, chosen_tier,
            provider, escalation_reason, confidence, complexity_score,
            quality_score, latency_ms, tokens_in, tokens_out, cost_usd, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            decision_id, run_id, node_id, agent_id, request_tier, chosen_tier,
            provider, escalation_reason, confidence, complexity_score,
            quality_score, latency_ms, tokens_in, tokens_out, cost_usd, created_at,
        ),
    )
    conn.commit()


def get_decisions_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    """List all routing decisions for a given run."""
    rows = conn.execute(
        "SELECT * FROM routing_decisions WHERE run_id = ? ORDER BY created_at",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_tier_distribution(
    conn: sqlite3.Connection, run_id: str | None = None
) -> list[dict[str, Any]]:
    """Count decisions per chosen_tier, optionally filtered by run_id."""
    if run_id is not None:
        rows = conn.execute(
            "SELECT chosen_tier, COUNT(*) as count FROM routing_decisions WHERE run_id = ? GROUP BY chosen_tier ORDER BY chosen_tier",
            (run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT chosen_tier, COUNT(*) as count FROM routing_decisions GROUP BY chosen_tier ORDER BY chosen_tier",
        ).fetchall()
    return [dict(r) for r in rows]


def get_cost_by_provider(
    conn: sqlite3.Connection, run_id: str | None = None
) -> list[dict[str, Any]]:
    """Sum cost_usd grouped by provider, optionally filtered by run_id."""
    if run_id is not None:
        rows = conn.execute(
            "SELECT provider, SUM(cost_usd) as total_cost FROM routing_decisions WHERE run_id = ? GROUP BY provider ORDER BY total_cost DESC",
            (run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT provider, SUM(cost_usd) as total_cost FROM routing_decisions GROUP BY provider ORDER BY total_cost DESC",
        ).fetchall()
    return [dict(r) for r in rows]
