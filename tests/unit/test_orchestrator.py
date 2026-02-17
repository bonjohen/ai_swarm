"""Tests for core.orchestrator — graph execution with mock agents."""

import json

import pytest
from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent
from agents import registry
from core.orchestrator import execute_graph, RunResult
from core.errors import GraphError
from core.state import create_initial_state
from graphs.graph_types import Graph, GraphNode, RetryPolicy


# --- Test agents ---

class EmptyModel(BaseModel):
    pass


class AgentA(BaseAgent):
    AGENT_ID = "agent_a"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "Agent A"
    USER_TEMPLATE = "Run A on {scope_id}"
    INPUT_SCHEMA = EmptyModel
    OUTPUT_SCHEMA = EmptyModel
    POLICY = AgentPolicy(allowed_local_models=["local"])

    def parse(self, response: str) -> dict:
        return {"a_output": json.loads(response).get("value", "done")}

    def validate(self, output: dict) -> None:
        pass


class AgentB(BaseAgent):
    AGENT_ID = "agent_b"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "Agent B"
    USER_TEMPLATE = "Run B on {scope_id}"
    INPUT_SCHEMA = EmptyModel
    OUTPUT_SCHEMA = EmptyModel
    POLICY = AgentPolicy(allowed_local_models=["local"])

    def parse(self, response: str) -> dict:
        return {"b_output": json.loads(response).get("value", "done")}

    def validate(self, output: dict) -> None:
        pass


class FailingAgent(BaseAgent):
    AGENT_ID = "failing_agent"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "I fail"
    USER_TEMPLATE = "{scope_id}"
    INPUT_SCHEMA = EmptyModel
    OUTPUT_SCHEMA = EmptyModel
    POLICY = AgentPolicy(allowed_local_models=["local"])

    def parse(self, response: str) -> dict:
        return {}

    def validate(self, output: dict) -> None:
        raise ValueError("intentional failure")


@pytest.fixture(autouse=True)
def setup_registry():
    registry.clear()
    registry.register(AgentA())
    registry.register(AgentB())
    registry.register(FailingAgent())
    yield
    registry.clear()


def _mock_model(system_prompt: str, user_message: str) -> str:
    return json.dumps({"value": "processed"})


def _make_two_node_graph() -> Graph:
    return Graph(
        id="test_2node",
        entry="step1",
        nodes={
            "step1": GraphNode(name="step1", agent="agent_a", next="step2"),
            "step2": GraphNode(name="step2", agent="agent_b", end=True),
        },
    )


# --- Tests ---

def test_two_node_graph_success():
    state = create_initial_state(
        scope_type="cert", scope_id="c1", run_id="r1", graph_id="test_2node"
    )
    graph = _make_two_node_graph()
    result = execute_graph(graph, state, model_call=_mock_model)

    assert isinstance(result, RunResult)
    assert result.status == "completed"
    assert result.state["a_output"] == "processed"
    assert result.state["b_output"] == "processed"
    assert len(result.events) == 2
    assert all(e["status"] == "success" for e in result.events)


def test_missing_state_keys_raises():
    with pytest.raises(GraphError, match="missing required keys"):
        execute_graph(_make_two_node_graph(), {}, model_call=_mock_model)


def test_node_failure_aborts_when_no_on_fail():
    graph = Graph(
        id="fail_graph",
        entry="fail_node",
        nodes={
            "fail_node": GraphNode(name="fail_node", agent="failing_agent"),
        },
    )
    state = create_initial_state(
        scope_type="cert", scope_id="c1", run_id="r1", graph_id="fail_graph"
    )
    result = execute_graph(graph, state, model_call=_mock_model)
    assert result.status == "failed"
    assert result.events[0]["status"] == "failed"


def test_node_failure_routes_to_on_fail():
    graph = Graph(
        id="on_fail_graph",
        entry="fail_node",
        nodes={
            "fail_node": GraphNode(name="fail_node", agent="failing_agent", on_fail="recovery"),
            "recovery": GraphNode(name="recovery", agent="agent_a", end=True),
        },
    )
    state = create_initial_state(
        scope_type="cert", scope_id="c1", run_id="r1", graph_id="on_fail_graph"
    )
    result = execute_graph(graph, state, model_call=_mock_model)
    assert result.status == "completed"
    assert result.events[0]["status"] == "failed"
    assert result.events[1]["status"] == "success"


def test_retry_policy():
    graph = Graph(
        id="retry_graph",
        entry="retry_node",
        nodes={
            "retry_node": GraphNode(
                name="retry_node",
                agent="failing_agent",
                retry=RetryPolicy(max_attempts=3, backoff_seconds=0),
            ),
        },
    )
    state = create_initial_state(
        scope_type="cert", scope_id="c1", run_id="r1", graph_id="retry_graph"
    )
    result = execute_graph(graph, state, model_call=_mock_model)
    assert result.status == "failed"
    # Should have attempted 3 times
    assert result.events[0]["attempt"] == 3


def test_missing_input_keys():
    graph = Graph(
        id="input_check",
        entry="needs_input",
        nodes={
            "needs_input": GraphNode(
                name="needs_input", agent="agent_a", inputs=["nonexistent_key"]
            ),
        },
    )
    state = create_initial_state(
        scope_type="cert", scope_id="c1", run_id="r1", graph_id="input_check"
    )
    result = execute_graph(graph, state, model_call=_mock_model)
    assert result.status == "failed"
    assert "missing state keys" in result.events[0].get("error", "")


def test_on_event_callback():
    events_captured = []
    state = create_initial_state(
        scope_type="cert", scope_id="c1", run_id="r1", graph_id="test"
    )
    execute_graph(
        _make_two_node_graph(), state,
        model_call=_mock_model,
        on_event=lambda e: events_captured.append(e),
    )
    assert len(events_captured) == 2
