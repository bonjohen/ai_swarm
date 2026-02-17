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

    def frontier_usage_rate(self) -> float:
        total = self._frontier_calls + self._local_calls
        return self._frontier_calls / total if total > 0 else 0.0

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
