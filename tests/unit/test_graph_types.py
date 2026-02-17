"""Tests for graphs.graph_types."""

import tempfile
from pathlib import Path

import pytest

from graphs.graph_types import Graph, GraphNode, RetryPolicy, load_graph


def test_graph_node_defaults():
    node = GraphNode(name="n1", agent="test_agent")
    assert node.inputs == []
    assert node.outputs == []
    assert node.next is None
    assert node.on_fail is None
    assert node.retry.max_attempts == 1
    assert node.end is False


def test_graph_get_node():
    nodes = {"a": GraphNode(name="a", agent="ag1"), "b": GraphNode(name="b", agent="ag2")}
    g = Graph(id="test", entry="a", nodes=nodes)
    assert g.get_node("a").agent == "ag1"


def test_graph_get_node_missing_raises():
    g = Graph(id="test", entry="a", nodes={"a": GraphNode(name="a", agent="ag1")})
    with pytest.raises(KeyError, match="Node not found"):
        g.get_node("nonexistent")


def test_load_graph_from_yaml():
    yaml_content = """\
id: test_graph
entry: step1
nodes:
  step1:
    agent: agent_a
    inputs: [source_docs]
    outputs: [entities]
    next: step2
    retry:
      max_attempts: 3
      backoff_seconds: 2.0
  step2:
    agent: agent_b
    inputs: [entities]
    outputs: [claims]
    end: true
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        path = Path(f.name)

    graph = load_graph(path)
    path.unlink()

    assert graph.id == "test_graph"
    assert graph.entry == "step1"
    assert len(graph.nodes) == 2

    n1 = graph.get_node("step1")
    assert n1.agent == "agent_a"
    assert n1.inputs == ["source_docs"]
    assert n1.outputs == ["entities"]
    assert n1.next == "step2"
    assert n1.retry.max_attempts == 3
    assert n1.retry.backoff_seconds == 2.0

    n2 = graph.get_node("step2")
    assert n2.end is True
    assert n2.next is None


def test_load_graph_defaults_id_from_filename():
    yaml_content = """\
entry: only
nodes:
  only:
    agent: single
    end: true
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, prefix="my_graph_") as f:
        f.write(yaml_content)
        f.flush()
        path = Path(f.name)

    graph = load_graph(path)
    path.unlink()

    assert graph.id == path.stem  # derived from filename
