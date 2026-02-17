"""Tests for structured logging, redaction, and metrics collection."""

import json
import logging

import pytest

from core.logging import (
    MetricsCollector,
    StructuredFormatter,
    get_metrics_collector,
    log_node_event,
    redact,
    reset_metrics_collector,
)


class TestRedaction:
    def test_redact_api_key(self):
        text = "Using key sk-abcdef1234567890abcdef to authenticate"
        assert "[REDACTED_API_KEY]" in redact(text)
        assert "sk-abcdef" not in redact(text)

    def test_redact_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = redact(text)
        assert "[REDACTED_TOKEN]" in result
        assert "eyJhbGciOi" not in result

    def test_no_redaction_needed(self):
        text = "Simple message with no secrets"
        assert redact(text) == text

    def test_redact_long_hex(self):
        text = "Hash: " + "a" * 50
        assert "[REDACTED_HASH]" in redact(text)


class TestStructuredFormatter:
    def test_formats_as_json(self):
        fmt = StructuredFormatter(redact_enabled=False)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test message", args=(), exc_info=None,
        )
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"

    def test_includes_structured_context(self):
        fmt = StructuredFormatter(redact_enabled=False)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Node event", args=(), exc_info=None,
        )
        record.run_id = "run-1"
        record.node_id = "node-a"
        record.agent_id = "ingestor"
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["run_id"] == "run-1"
        assert parsed["node_id"] == "node-a"
        assert parsed["agent_id"] == "ingestor"

    def test_redacts_when_enabled(self):
        fmt = StructuredFormatter(redact_enabled=True)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Using sk-abcdef1234567890abcdef for auth",
            args=(), exc_info=None,
        )
        output = fmt.format(record)
        assert "sk-abcdef" not in output
        assert "REDACTED" in output


class TestMetricsCollector:
    def setup_method(self):
        reset_metrics_collector()

    def test_record_run_duration(self):
        mc = MetricsCollector()
        mc.record_run_duration(5.0)
        mc.record_run_duration(10.0)
        d = mc.to_dict()
        assert d["run_count"] == 2
        assert d["avg_run_duration"] == 7.5

    def test_record_token_usage(self):
        mc = MetricsCollector()
        mc.record_token_usage(1000)
        mc.record_token_usage(2000)
        assert mc.to_dict()["total_tokens"] == 3000

    def test_frontier_usage_rate(self):
        mc = MetricsCollector()
        mc.record_model_call(escalated=False)
        mc.record_model_call(escalated=False)
        mc.record_model_call(escalated=True)
        rate = mc.frontier_usage_rate()
        assert abs(rate - 1/3) < 0.01

    def test_qa_failure_tracking(self):
        mc = MetricsCollector()
        mc.record_qa_failure("ingestor")
        mc.record_qa_failure("ingestor")
        mc.record_qa_failure("claim_extractor")
        d = mc.to_dict()
        assert d["qa_fail_rate_by_agent"]["ingestor"] == 2
        assert d["qa_fail_rate_by_agent"]["claim_extractor"] == 1

    def test_delta_magnitude(self):
        mc = MetricsCollector()
        mc.record_delta_magnitude(added=3, removed=1, changed=2)
        mc.record_delta_magnitude(added=0, removed=0, changed=1)
        d = mc.to_dict()
        assert d["avg_delta_magnitude"] == 3.5  # (6 + 1) / 2

    def test_empty_collector(self):
        mc = MetricsCollector()
        d = mc.to_dict()
        assert d["run_count"] == 0
        assert d["avg_run_duration"] == 0.0
        assert d["frontier_usage_rate"] == 0.0

    def test_singleton(self):
        mc1 = get_metrics_collector()
        mc2 = get_metrics_collector()
        assert mc1 is mc2

    def test_reset(self):
        mc1 = get_metrics_collector()
        reset_metrics_collector()
        mc2 = get_metrics_collector()
        assert mc1 is not mc2


class TestLogNodeEvent:
    def test_log_success_event(self, caplog):
        event = {
            "run_id": "r1",
            "node_id": "node_a",
            "agent_id": "ingestor",
            "status": "success",
            "attempt": 1,
            "cost": {"tokens_in": 100},
        }
        with caplog.at_level(logging.DEBUG):
            log_node_event(event)
        assert any("node_a" in r.message for r in caplog.records)

    def test_log_failed_event(self, caplog):
        event = {
            "run_id": "r1",
            "node_id": "node_a",
            "agent_id": "ingestor",
            "status": "failed",
            "attempt": 2,
            "cost": {},
        }
        with caplog.at_level(logging.DEBUG):
            log_node_event(event)
        assert any("failed" in r.message for r in caplog.records)
