"""Tests for the command registry and tiered dispatcher (Phase R1)."""

from __future__ import annotations

import json

import pytest

from core.command_registry import CommandMatch, CommandPattern, CommandRegistry, register_defaults
from core.tiered_dispatch import DispatchResult, TieredDispatcher


class TestCommandPattern:
    def test_pattern_compiles(self):
        cp = CommandPattern(
            pattern=r"^/cert\s+(?P<cert_id>\S+)$",
            action="execute_graph",
            target="run_cert.py",
            description="Run cert",
        )
        assert cp._compiled is not None


class TestCommandRegistry:
    def _registry(self) -> CommandRegistry:
        reg = CommandRegistry()
        register_defaults(reg)
        return reg

    def test_cert_match(self):
        reg = self._registry()
        m = reg.match("/cert az-104")
        assert m is not None
        assert m.action == "execute_graph"
        assert m.target == "run_cert.py"
        assert m.args == {"cert_id": "az-104"}
        assert m.confidence == 1.0

    def test_dossier_match(self):
        reg = self._registry()
        m = reg.match("/dossier climate-change")
        assert m is not None
        assert m.action == "execute_graph"
        assert m.target == "run_dossier.py"
        assert m.args == {"topic_id": "climate-change"}

    def test_story_match(self):
        reg = self._registry()
        m = reg.match("/story world-42")
        assert m is not None
        assert m.action == "execute_graph"
        assert m.target == "run_story.py"
        assert m.args == {"world_id": "world-42"}

    def test_lab_match(self):
        reg = self._registry()
        m = reg.match("/lab suite-1")
        assert m is not None
        assert m.action == "execute_graph"
        assert m.target == "run_lab.py"
        assert m.args == {"suite_id": "suite-1"}

    def test_status_match(self):
        reg = self._registry()
        m = reg.match("/status")
        assert m is not None
        assert m.action == "show_status"
        assert m.args == {}

    def test_help_match(self):
        reg = self._registry()
        m = reg.match("/help")
        assert m is not None
        assert m.action == "show_help"

    def test_no_match_returns_none(self):
        reg = self._registry()
        m = reg.match("explain the architecture")
        assert m is None

    def test_whitespace_stripped(self):
        reg = self._registry()
        m = reg.match("  /status  ")
        assert m is not None
        assert m.action == "show_status"

    def test_slash_command_arg_parsing(self):
        """Extracts named groups from slash commands."""
        reg = self._registry()
        m = reg.match("/cert az-104")
        assert m is not None
        assert m.args["cert_id"] == "az-104"

        m = reg.match("/lab my-benchmark-suite")
        assert m is not None
        assert m.args["suite_id"] == "my-benchmark-suite"


class TestJSONPayload:
    def _registry(self) -> CommandRegistry:
        reg = CommandRegistry()
        register_defaults(reg)
        return reg

    def test_json_command_routes(self):
        reg = self._registry()
        payload = json.dumps({"command": "/cert az-900"})
        m = reg.match(payload)
        assert m is not None
        assert m.action == "execute_graph"
        assert m.target == "run_cert.py"
        assert m.args["cert_id"] == "az-900"

    def test_json_extra_keys_merged(self):
        reg = self._registry()
        payload = json.dumps({"command": "/lab suite-2", "priority": "high"})
        m = reg.match(payload)
        assert m is not None
        assert m.args["suite_id"] == "suite-2"
        assert m.args["priority"] == "high"

    def test_json_unknown_command(self):
        reg = self._registry()
        payload = json.dumps({"command": "/unknown-action"})
        m = reg.match(payload)
        assert m is not None
        assert m.action == "unknown_command"

    def test_json_no_command_key(self):
        reg = self._registry()
        payload = json.dumps({"query": "something"})
        m = reg.match(payload)
        assert m is None

    def test_invalid_json_ignored(self):
        reg = self._registry()
        m = reg.match("{not valid json")
        assert m is None


class TestTieredDispatcher:
    def _dispatcher(self) -> TieredDispatcher:
        reg = CommandRegistry()
        register_defaults(reg)
        return TieredDispatcher(command_registry=reg)

    def test_tier0_match_returns_tier_0(self):
        d = self._dispatcher()
        result = d.dispatch("/cert az-104")
        assert result.tier == 0
        assert result.action == "execute_graph"
        assert result.target == "run_cert.py"
        assert result.args["cert_id"] == "az-104"
        assert result.confidence == 1.0

    def test_dispatch_result_structure(self):
        d = self._dispatcher()
        result = d.dispatch("/status")
        assert isinstance(result, DispatchResult)
        assert result.tier == 0
        assert result.action == "show_status"
        assert result.provider is None
        assert result.model_response is None

    def test_unknown_input_needs_escalation(self):
        d = self._dispatcher()
        result = d.dispatch("explain the certification architecture")
        assert result.tier == -1
        assert result.action == "needs_escalation"
        assert result.confidence == 0.0

    def test_json_payload_dispatch(self):
        d = self._dispatcher()
        payload = json.dumps({"command": "/dossier topic-1"})
        result = d.dispatch(payload)
        assert result.tier == 0
        assert result.action == "execute_graph"
        assert result.target == "run_dossier.py"
