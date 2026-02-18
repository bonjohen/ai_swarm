"""Analyze routing_decisions and suggest threshold adjustments.

Usage: python -m scripts.tune_router [--db ai_swarm.db] [--run-id <id>]

Identifies:
  - Over-escalation: high-confidence requests sent to higher tiers
  - Under-escalation: low-quality results from lower tiers
  - Cost optimization: expensive provider used when cheap one would suffice
  - Recommended threshold and weight changes
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from data.db import get_initialized_connection

logger = logging.getLogger(__name__)


def _fetch_decisions(db_path: str, run_id: str | None = None) -> list[dict[str, Any]]:
    """Fetch routing decisions from DB."""
    conn = get_initialized_connection(db_path)
    conn.row_factory = _dict_factory
    if run_id:
        rows = conn.execute(
            "SELECT * FROM routing_decisions WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM routing_decisions ORDER BY created_at",
        ).fetchall()
    conn.close()
    return rows


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def analyze_over_escalation(
    decisions: list[dict[str, Any]],
    confidence_threshold: float = 0.75,
) -> list[dict[str, Any]]:
    """Find decisions where high-confidence requests were escalated unnecessarily."""
    issues = []
    for d in decisions:
        conf = d.get("confidence")
        if conf is None:
            continue
        if conf >= confidence_threshold and d["chosen_tier"] > d["request_tier"]:
            issues.append({
                "decision_id": d["decision_id"],
                "agent_id": d.get("agent_id"),
                "confidence": conf,
                "request_tier": d["request_tier"],
                "chosen_tier": d["chosen_tier"],
                "reason": d.get("escalation_reason", ""),
                "suggestion": f"Confidence {conf:.2f} >= {confidence_threshold} — "
                              f"could have stayed at tier {d['request_tier']}",
            })
    return issues


def analyze_under_escalation(
    decisions: list[dict[str, Any]],
    quality_threshold: float = 0.70,
) -> list[dict[str, Any]]:
    """Find decisions where low-quality results came from lower tiers."""
    issues = []
    for d in decisions:
        quality = d.get("quality_score")
        if quality is None:
            continue
        if quality < quality_threshold and d["chosen_tier"] <= d["request_tier"]:
            issues.append({
                "decision_id": d["decision_id"],
                "agent_id": d.get("agent_id"),
                "quality_score": quality,
                "chosen_tier": d["chosen_tier"],
                "suggestion": f"Quality {quality:.2f} < {quality_threshold} — "
                              f"consider escalating from tier {d['chosen_tier']}",
            })
    return issues


def analyze_cost_optimization(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Identify cost optimization opportunities."""
    provider_costs: dict[str, float] = {}
    provider_counts: dict[str, int] = {}
    provider_latencies: dict[str, list[float]] = {}

    for d in decisions:
        provider = d.get("provider") or "unknown"
        cost = d.get("cost_usd") or 0.0
        latency = d.get("latency_ms")

        provider_costs[provider] = provider_costs.get(provider, 0.0) + cost
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if latency is not None:
            provider_latencies.setdefault(provider, []).append(latency)

    avg_cost_per_call = {
        p: round(provider_costs[p] / provider_counts[p], 6) if provider_counts[p] else 0.0
        for p in provider_costs
    }
    avg_latency = {
        p: round(sum(lats) / len(lats), 1) if lats else 0.0
        for p, lats in provider_latencies.items()
    }

    return {
        "total_cost_by_provider": {k: round(v, 6) for k, v in provider_costs.items()},
        "call_count_by_provider": provider_counts,
        "avg_cost_per_call": avg_cost_per_call,
        "avg_latency_ms": avg_latency,
    }


def suggest_thresholds(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute recommended threshold adjustments from decision data."""
    confidences = [d["confidence"] for d in decisions if d.get("confidence") is not None]
    qualities = [d["quality_score"] for d in decisions if d.get("quality_score") is not None]

    suggestions: dict[str, Any] = {}

    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        # If average confidence is high, we can raise the threshold
        # If low, we should lower it to reduce unnecessary escalation
        suggested = round(min(0.9, max(0.5, avg_conf - 0.05)), 2)
        suggestions["confidence_threshold"] = {
            "current_avg": round(avg_conf, 4),
            "suggested": suggested,
            "reasoning": f"Average confidence is {avg_conf:.2f}; "
                         f"suggested threshold {suggested}",
        }

    if qualities:
        avg_qual = sum(qualities) / len(qualities)
        suggested = round(min(0.9, max(0.4, avg_qual - 0.10)), 2)
        suggestions["quality_threshold"] = {
            "current_avg": round(avg_qual, 4),
            "suggested": suggested,
            "reasoning": f"Average quality is {avg_qual:.2f}; "
                         f"suggested threshold {suggested}",
        }

    # Tier distribution
    tier_counts: dict[int, int] = {}
    for d in decisions:
        t = d["chosen_tier"]
        tier_counts[t] = tier_counts.get(t, 0) + 1
    total = sum(tier_counts.values())
    if total > 0:
        suggestions["tier_distribution"] = {
            tier: f"{count} ({count/total*100:.1f}%)"
            for tier, count in sorted(tier_counts.items())
        }

    return suggestions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze routing decisions and suggest tuning")
    parser.add_argument("--db", default="ai_swarm.db", help="SQLite database path")
    parser.add_argument("--run-id", default=None, help="Filter to a specific run")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    decisions = _fetch_decisions(args.db, args.run_id)
    if not decisions:
        print("No routing decisions found.")
        return 0

    print(f"Analyzing {len(decisions)} routing decisions...\n")

    over = analyze_over_escalation(decisions)
    under = analyze_under_escalation(decisions)
    costs = analyze_cost_optimization(decisions)
    thresholds = suggest_thresholds(decisions)

    if args.json:
        output = {
            "total_decisions": len(decisions),
            "over_escalation": over,
            "under_escalation": under,
            "cost_analysis": costs,
            "threshold_suggestions": thresholds,
        }
        print(json.dumps(output, indent=2, default=str))
        return 0

    # Human-readable output
    print("=== Over-Escalation ===")
    if over:
        for issue in over:
            print(f"  [{issue['agent_id']}] {issue['suggestion']}")
    else:
        print("  None detected.")

    print("\n=== Under-Escalation ===")
    if under:
        for issue in under:
            print(f"  [{issue['agent_id']}] {issue['suggestion']}")
    else:
        print("  None detected.")

    print("\n=== Cost Analysis ===")
    for provider, cost in costs["total_cost_by_provider"].items():
        count = costs["call_count_by_provider"][provider]
        avg = costs["avg_cost_per_call"][provider]
        lat = costs["avg_latency_ms"].get(provider, "N/A")
        print(f"  {provider}: ${cost:.6f} total, {count} calls, ${avg:.6f}/call, {lat}ms avg latency")

    print("\n=== Threshold Suggestions ===")
    for key, info in thresholds.items():
        if isinstance(info, dict) and "suggested" in info:
            print(f"  {key}: {info['reasoning']}")
        elif isinstance(info, dict):
            print(f"  {key}: {info}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
