"""Tests for state checkpointing and resume."""

import json
import shutil
from pathlib import Path

import pytest

from agents import registry
from agents.base_agent import AgentPolicy, BaseAgent
from core.orchestrator import (
    CHECKPOINT_DIR,
    _save_checkpoint,
    execute_graph,
    load_checkpoint,
)
from core.state import create_initial_state
from graphs.graph_types import Graph, GraphNode


class StubAgent(BaseAgent):
    AGENT_ID = "stub"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "Stub"
    USER_TEMPLATE = "{x}"

    from pydantic import BaseModel
    class _In(BaseModel):
        x: str = ""
    class _Out(BaseModel):
        y: str = ""
    INPUT_SCHEMA = _In
    OUTPUT_SCHEMA = _Out
    POLICY = AgentPolicy(allowed_local_models=["local"])

    def __init__(self, agent_id: str = "stub", output: dict | None = None):
        self._agent_id = agent_id
        self._output = output or {"y": "done"}

    @property
    def AGENT_ID(self):
        return self._agent_id

    def parse(self, response):
        return self._output

    def validate(self, output):
        pass

    def run(self, state, model_call=None):
        result = dict(self._output)
        self.validate(result)
        return result


@pytest.fixture(autouse=True)
def cleanup():
    registry.clear()
    yield
    registry.clear()
    if CHECKPOINT_DIR.exists():
        shutil.rmtree(CHECKPOINT_DIR)


def _make_graph():
    return Graph(
        id="test_graph",
        entry="a",
        nodes={
            "a": GraphNode(name="a", agent="agent_a", outputs=["a_out"], next="b"),
            "b": GraphNode(name="b", agent="agent_b", outputs=["b_out"], next="c"),
            "c": GraphNode(name="c", agent="agent_c", outputs=["c_out"], end=True),
        },
    )


def test_checkpoint_saves_after_each_node():
    registry.register(StubAgent("agent_a", {"a_out": "A"}))
    registry.register(StubAgent("agent_b", {"b_out": "B"}))
    registry.register(StubAgent("agent_c", {"c_out": "C"}))

    state = create_initial_state(
        scope_type="test", scope_id="t1", run_id="cp-test-1", graph_id="test_graph",
    )

    result = execute_graph(_make_graph(), state, checkpoint=True)
    assert result.status == "completed"

    # Checkpoints should exist
    cp_dir = CHECKPOINT_DIR / "cp-test-1"
    assert cp_dir.exists()
    assert (cp_dir / "a.json").exists()
    assert (cp_dir / "b.json").exists()
    assert (cp_dir / "c.json").exists()


def test_load_checkpoint_returns_latest():
    registry.register(StubAgent("agent_a", {"a_out": "A"}))
    registry.register(StubAgent("agent_b", {"b_out": "B"}))
    registry.register(StubAgent("agent_c", {"c_out": "C"}))

    state = create_initial_state(
        scope_type="test", scope_id="t1", run_id="cp-test-2", graph_id="test_graph",
    )
    execute_graph(_make_graph(), state, checkpoint=True)

    loaded = load_checkpoint("cp-test-2")
    assert loaded is not None
    node_name, loaded_state = loaded
    assert node_name == "c"
    assert loaded_state["c_out"] == "C"


def test_load_checkpoint_nonexistent():
    assert load_checkpoint("nonexistent-run") is None


def test_resume_from_node():
    registry.register(StubAgent("agent_a", {"a_out": "A"}))
    registry.register(StubAgent("agent_b", {"b_out": "B"}))
    registry.register(StubAgent("agent_c", {"c_out": "C"}))

    state = create_initial_state(
        scope_type="test", scope_id="t1", run_id="resume-1", graph_id="test_graph",
    )
    # Pre-populate state as if node 'a' already ran
    state["a_out"] = "A"

    result = execute_graph(_make_graph(), state, resume_from="a")
    assert result.status == "completed"
    # Should have only executed b and c (skipped a)
    assert len(result.events) == 2
    node_ids = [e["node_id"] for e in result.events]
    assert "a" not in node_ids
    assert "b" in node_ids
    assert "c" in node_ids
