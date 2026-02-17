"""Graph node data structures and YAML graph loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 1.0


@dataclass
class GraphNode:
    name: str
    agent: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    next: str | None = None
    on_fail: str | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    budget: dict[str, Any] | None = None
    end: bool = False


@dataclass
class Graph:
    id: str
    entry: str
    nodes: dict[str, GraphNode]

    def get_node(self, name: str) -> GraphNode:
        if name not in self.nodes:
            raise KeyError(f"Node not found in graph '{self.id}': {name}")
        return self.nodes[name]


def load_graph(path: Path | str) -> Graph:
    """Load a graph definition from a YAML file."""
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f)

    graph_id = raw.get("id", path.stem)
    entry = raw["entry"]
    nodes: dict[str, GraphNode] = {}

    for name, node_def in raw["nodes"].items():
        retry_def = node_def.get("retry", {})
        retry = RetryPolicy(
            max_attempts=retry_def.get("max_attempts", 1),
            backoff_seconds=retry_def.get("backoff_seconds", 1.0),
        )
        nodes[name] = GraphNode(
            name=name,
            agent=node_def["agent"],
            inputs=node_def.get("inputs", []),
            outputs=node_def.get("outputs", []),
            next=node_def.get("next"),
            on_fail=node_def.get("on_fail"),
            retry=retry,
            budget=node_def.get("budget"),
            end=node_def.get("end", False),
        )

    return Graph(id=graph_id, entry=entry, nodes=nodes)
