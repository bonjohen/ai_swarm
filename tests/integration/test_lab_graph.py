"""Integration test: lab graph end-to-end (1 suite, 2 tasks)."""

import json
import shutil
from pathlib import Path

import pytest

from agents import registry
from agents.ingestor_agent import IngestorAgent
from agents.metric_extractor_agent import MetricExtractorAgent
from agents.delta_agent import DeltaAgent
from agents.synthesizer_agent import SynthesizerAgent
from agents.publisher_agent import PublisherAgent, PUBLISH_ROOT
from core.orchestrator import execute_graph
from core.state import create_initial_state
from graphs.graph_types import load_graph

GRAPH_PATH = Path(__file__).parent.parent.parent / "graphs" / "lab_graph.yaml"

_MOCK_RESPONSES = {
    "ingestion": json.dumps({
        "doc_ids": ["d1"],
        "segment_ids": ["s1"],
        "source_docs": [{"doc_id": "d1", "uri": "suite-config"}],
        "source_segments": [{"segment_id": "s1", "text": "benchmark suite config"}],
        "tasks": [
            {"task_id": "t1", "category": "summarization"},
            {"task_id": "t2", "category": "reasoning"},
        ],
        "models": [{"model_id": "deepseek-r1:1.5b"}, {"model_id": "qwen2.5:7b"}],
        "hw_spec": {"gpu": "RTX 4090", "ram": "64GB"},
    }),
    "synthesis": json.dumps({
        "summary": "Both models performed adequately on the benchmark suite.",
        "key_findings": [
            {"finding": "deepseek-r1 faster but less accurate", "claim_ids": []},
            {"finding": "qwen2.5 better on reasoning tasks", "claim_ids": []},
        ],
        "metrics_summary": "Average accuracy 78%, latency under 2s",
        "changes_since_last": "First benchmark run",
        "contradictions": [],
        "results": [
            {"task_id": "t1", "model_id": "deepseek-r1:1.5b", "score": 0.75},
            {"task_id": "t2", "model_id": "qwen2.5:7b", "score": 0.82},
        ],
        "scores": {"deepseek-r1:1.5b": 0.75, "qwen2.5:7b": 0.82},
        "routing_config": {
            "local_threshold": 0.7,
            "frontier_threshold": 0.9,
            "recommended": {"summarization": "qwen2.5:7b", "reasoning": "qwen2.5:7b"},
        },
    }),
    "metric extraction": json.dumps({
        "metrics": [
            {"metric_id": "m-acc", "name": "accuracy", "unit": "ratio", "dimensions": {"suite": "bench-1"}},
            {"metric_id": "m-lat", "name": "latency", "unit": "seconds", "dimensions": {"suite": "bench-1"}},
        ],
        "metric_points": [
            {"point_id": "p1", "metric_id": "m-acc", "t": "2026-02", "value": 0.78, "doc_id": "d1", "segment_id": "s1", "confidence": 0.9},
            {"point_id": "p2", "metric_id": "m-lat", "t": "2026-02", "value": 1.5, "doc_id": "d1", "segment_id": "s1", "confidence": 0.95},
        ],
    }),
}


def _mock_model(system_prompt: str, user_message: str) -> str:
    for key, response in _MOCK_RESPONSES.items():
        if key in system_prompt.lower():
            return response
    return json.dumps({})


@pytest.fixture(autouse=True)
def setup_and_cleanup():
    registry.clear()
    registry.register(IngestorAgent())
    registry.register(MetricExtractorAgent())
    registry.register(DeltaAgent())
    registry.register(SynthesizerAgent())
    registry.register(PublisherAgent())
    yield
    registry.clear()
    out_dir = PUBLISH_ROOT / "lab"
    if out_dir.exists():
        shutil.rmtree(out_dir)


def test_lab_graph_end_to_end():
    graph = load_graph(GRAPH_PATH)

    state = create_initial_state(
        scope_type="lab", scope_id="bench-1",
        run_id="lab-integration-1", graph_id="lab_graph",
        extra={
            "suite_config": {"suite_id": "bench-1", "tasks": ["t1", "t2"]},
            "previous_snapshot": None,
            "claims": [],
            "metrics": [],
            "tasks": [
                {"task_id": "t1", "category": "summarization"},
                {"task_id": "t2", "category": "reasoning"},
            ],
            "models": [{"model_id": "deepseek-r1:1.5b"}, {"model_id": "qwen2.5:7b"}],
            "hw_spec": {"gpu": "RTX 4090", "ram": "64GB"},
            "normalized_segments": [{"segment_id": "s1", "text": "benchmark results"}],
        },
    )

    result = execute_graph(graph, state, model_call=_mock_model)

    assert result.status == "completed"
    assert len(result.events) == 7  # all 7 nodes

    # Metrics extracted
    assert len(result.state["metrics"]) == 2
    assert len(result.state["metric_points"]) == 2

    # Synthesis produced
    assert "summary" in result.state["synthesis"]

    # Snapshot + delta
    assert result.state["snapshot_id"]
    assert result.state["delta_json"]

    # Publish
    publish_dir = Path(result.state["publish_dir"])
    assert (publish_dir / "manifest.json").exists()
    assert (publish_dir / "artifacts.json").exists()
