"""Structured logging and observability for the AI Swarm platform.

Provides JSON-structured logging per node execution, log redaction, and
observable metrics collection.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Redaction patterns
# ---------------------------------------------------------------------------

_REDACTION_PATTERNS = [
    # API keys (common patterns)
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})"), "[REDACTED_API_KEY]"),
    (re.compile(r"(key-[a-zA-Z0-9]{20,})"), "[REDACTED_API_KEY]"),
    # Bearer tokens
    (re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{20,})"), "Bearer [REDACTED_TOKEN]"),
    # Generic long hex/base64 strings that look like secrets
    (re.compile(r"([a-fA-F0-9]{40,})"), "[REDACTED_HASH]"),
]


def redact(text: str) -> str:
    """Redact sensitive patterns from a string."""
    for pattern, replacement in _REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Structured log formatter
# ---------------------------------------------------------------------------

class StructuredFormatter(logging.Formatter):
    """JSON log formatter with optional redaction."""

    def __init__(self, redact_enabled: bool = True):
        super().__init__()
        self.redact_enabled = redact_enabled

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add structured context if present
        if hasattr(record, "run_id"):
            log_entry["run_id"] = record.run_id
        if hasattr(record, "scope_id"):
            log_entry["scope_id"] = record.scope_id
        if hasattr(record, "node_id"):
            log_entry["node_id"] = record.node_id
        if hasattr(record, "agent_id"):
            log_entry["agent_id"] = record.agent_id
        if hasattr(record, "model_used"):
            log_entry["model_used"] = record.model_used
        if hasattr(record, "cost"):
            log_entry["cost"] = record.cost

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])

        text = json.dumps(log_entry, default=str)
        if self.redact_enabled:
            text = redact(text)
        return text


def setup_structured_logging(
    level: int = logging.INFO,
    redact_enabled: bool = True,
) -> logging.Handler:
    """Configure the root logger to use structured JSON output."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter(redact_enabled=redact_enabled))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    return handler


# ---------------------------------------------------------------------------
# Node execution logger
# ---------------------------------------------------------------------------

def log_node_event(event: dict[str, Any], logger_name: str = "core.orchestrator") -> None:
    """Emit a structured log entry for a node execution event."""
    log = logging.getLogger(logger_name)
    extra = {
        "run_id": event.get("run_id", ""),
        "node_id": event.get("node_id", ""),
        "agent_id": event.get("agent_id", ""),
        "cost": event.get("cost", {}),
    }
    record = log.makeRecord(
        name=logger_name,
        level=logging.INFO if event.get("status") == "success" else logging.WARNING,
        fn="",
        lno=0,
        msg=f"Node '{event.get('node_id')}' {event.get('status')} (attempt {event.get('attempt', 1)})",
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    log.handle(record)


# ---------------------------------------------------------------------------
# Observable metrics collector
# ---------------------------------------------------------------------------

@dataclass
class MetricsCollector:
    """Collects observable metrics from graph runs."""
    _run_durations: list[float] = field(default_factory=list)
    _token_usage: list[int] = field(default_factory=list)
    _frontier_calls: int = 0
    _local_calls: int = 0
    _qa_failures: dict[str, int] = field(default_factory=dict)
    _delta_magnitudes: list[float] = field(default_factory=list)
    # Router metrics (R5.1)
    _tier_distribution: dict[int, int] = field(default_factory=dict)
    _escalation_counts: dict[str, int] = field(default_factory=dict)  # "from_tier:to_tier" -> count
    _provider_distribution: dict[str, int] = field(default_factory=dict)
    _cost_by_provider: dict[str, float] = field(default_factory=dict)
    _latencies_by_tier: dict[int, list[float]] = field(default_factory=dict)
    _quality_by_tier: dict[int, list[float]] = field(default_factory=dict)

    def record_run_duration(self, seconds: float) -> None:
        self._run_durations.append(seconds)

    def record_token_usage(self, tokens: int) -> None:
        self._token_usage.append(tokens)

    def record_model_call(self, escalated: bool) -> None:
        if escalated:
            self._frontier_calls += 1
        else:
            self._local_calls += 1

    def record_qa_failure(self, agent_id: str) -> None:
        self._qa_failures[agent_id] = self._qa_failures.get(agent_id, 0) + 1

    def record_delta_magnitude(self, added: int, removed: int, changed: int) -> None:
        self._delta_magnitudes.append(added + removed + changed)

    def record_routing_decision(
        self,
        *,
        chosen_tier: int,
        provider: str | None = None,
        escalated: bool = False,
        request_tier: int | None = None,
        latency_ms: float | None = None,
        quality_score: float | None = None,
        cost_usd: float | None = None,
    ) -> None:
        """Record a routing decision for aggregate metrics."""
        self._tier_distribution[chosen_tier] = self._tier_distribution.get(chosen_tier, 0) + 1
        if escalated and request_tier is not None:
            key = f"{request_tier}:{chosen_tier}"
            self._escalation_counts[key] = self._escalation_counts.get(key, 0) + 1
        if provider:
            self._provider_distribution[provider] = self._provider_distribution.get(provider, 0) + 1
            if cost_usd is not None:
                self._cost_by_provider[provider] = self._cost_by_provider.get(provider, 0.0) + cost_usd
        if latency_ms is not None:
            self._latencies_by_tier.setdefault(chosen_tier, []).append(latency_ms)
        if quality_score is not None:
            self._quality_by_tier.setdefault(chosen_tier, []).append(quality_score)

    def frontier_usage_rate(self) -> float:
        total = self._frontier_calls + self._local_calls
        return self._frontier_calls / total if total > 0 else 0.0

    def escalation_rate(self) -> float:
        """Fraction of routing decisions that were escalated."""
        total = sum(self._tier_distribution.values())
        escalated = sum(self._escalation_counts.values())
        return escalated / total if total > 0 else 0.0

    def avg_latency_by_tier(self) -> dict[int, float]:
        return {
            tier: round(sum(lats) / len(lats), 2)
            for tier, lats in self._latencies_by_tier.items()
            if lats
        }

    def avg_quality_by_tier(self) -> dict[int, float]:
        return {
            tier: round(sum(scores) / len(scores), 4)
            for tier, scores in self._quality_by_tier.items()
            if scores
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_count": len(self._run_durations),
            "avg_run_duration": (
                round(sum(self._run_durations) / len(self._run_durations), 2)
                if self._run_durations else 0.0
            ),
            "total_tokens": sum(self._token_usage),
            "frontier_usage_rate": round(self.frontier_usage_rate(), 4),
            "frontier_calls": self._frontier_calls,
            "local_calls": self._local_calls,
            "qa_fail_rate_by_agent": dict(self._qa_failures),
            "avg_delta_magnitude": (
                round(sum(self._delta_magnitudes) / len(self._delta_magnitudes), 2)
                if self._delta_magnitudes else 0.0
            ),
            "tier_distribution": dict(self._tier_distribution),
            "escalation_rate": round(self.escalation_rate(), 4),
            "escalation_counts": dict(self._escalation_counts),
            "provider_distribution": dict(self._provider_distribution),
            "cost_by_provider": {k: round(v, 6) for k, v in self._cost_by_provider.items()},
            "avg_latency_by_tier": self.avg_latency_by_tier(),
            "avg_quality_by_tier": self.avg_quality_by_tier(),
        }


# Module-level singleton
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def reset_metrics_collector() -> None:
    global _metrics_collector
    _metrics_collector = None
