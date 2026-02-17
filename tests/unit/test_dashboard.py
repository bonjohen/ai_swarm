"""Tests for the metrics dashboard handler."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from scripts.dashboard import DashboardHandler


class MockRequest:
    """Minimal socket-like object for handler construction."""
    def makefile(self, *args, **kwargs):
        return BytesIO()


def _make_handler(path: str) -> tuple[DashboardHandler, BytesIO]:
    """Create a DashboardHandler with a mocked request for testing."""
    wfile = BytesIO()
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.path = path
    handler.requestline = f"GET {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = "GET"
    handler.headers = {}
    handler.wfile = wfile
    handler._headers_buffer = []

    # Patch send_response and friends
    sent = {"code": None, "headers": {}}
    def mock_send_response(code, message=None):
        sent["code"] = code
    def mock_send_header(key, value):
        sent["headers"][key] = value
    def mock_end_headers():
        pass
    def mock_send_error(code, message=None):
        sent["code"] = code

    handler.send_response = mock_send_response
    handler.send_header = mock_send_header
    handler.end_headers = mock_end_headers
    handler.send_error = mock_send_error

    return handler, wfile, sent


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        handler, wfile, sent = _make_handler("/health")
        handler.do_GET()
        assert sent["code"] == 200
        body = json.loads(wfile.getvalue().decode("utf-8"))
        assert body["status"] == "ok"


class TestMetricsEndpoint:
    def test_metrics_returns_collector_data(self):
        handler, wfile, sent = _make_handler("/metrics")
        handler.do_GET()
        assert sent["code"] == 200
        body = json.loads(wfile.getvalue().decode("utf-8"))
        assert "run_count" in body
        assert "total_tokens" in body


class TestRunsEndpoint:
    def test_runs_returns_list(self):
        handler, wfile, sent = _make_handler("/runs")
        # Mock the _recent_runs to avoid DB dependency
        handler._recent_runs = lambda limit=50: [{"run_id": "r1", "status": "completed"}]
        handler.do_GET()
        assert sent["code"] == 200
        body = json.loads(wfile.getvalue().decode("utf-8"))
        assert isinstance(body, list)
        assert body[0]["run_id"] == "r1"


class TestNotFound:
    def test_unknown_path(self):
        handler, wfile, sent = _make_handler("/unknown")
        handler.do_GET()
        assert sent["code"] == 404
