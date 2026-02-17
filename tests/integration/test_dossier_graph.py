"""Integration test: dossier graph end-to-end (1 topic, 3 sources)."""

import json
import shutil
from pathlib import Path

import pytest

from agents import registry
from agents.ingestor_agent import IngestorAgent
from agents.normalizer_agent import NormalizerAgent
from agents.entity_resolver_agent import EntityResolverAgent
from agents.claim_extractor_agent import ClaimExtractorAgent
from agents.metric_extractor_agent import MetricExtractorAgent
from agents.contradiction_agent import ContradictionAgent
from agents.delta_agent import DeltaAgent
from agents.synthesizer_agent import SynthesizerAgent
from agents.publisher_agent import PublisherAgent, PUBLISH_ROOT
from core.orchestrator import execute_graph
from core.state import create_initial_state
from graphs.graph_types import load_graph

GRAPH_PATH = Path(__file__).parent.parent.parent / "graphs" / "dossier_graph.yaml"

_MOCK_RESPONSES = {
    "ingestion": json.dumps({
        "doc_ids": ["d1", "d2", "d3"],
        "segment_ids": ["s1", "s2", "s3"],
        "source_docs": [
            {"doc_id": "d1", "uri": "http://src1.com"},
            {"doc_id": "d2", "uri": "http://src2.com"},
            {"doc_id": "d3", "uri": "http://src3.com"},
        ],
        "source_segments": [
            {"segment_id": "s1", "text": "AI adoption in healthcare grew 40% in 2025."},
            {"segment_id": "s2", "text": "Healthcare AI spending reached $5B."},
            {"segment_id": "s3", "text": "Some studies show AI adoption grew only 25% in 2025."},
        ],
    }),
    "normalization": json.dumps({
        "normalized_segments": [
            {"segment_id": "s1", "text": "AI adoption in healthcare grew 40% in 2025."},
            {"segment_id": "s2", "text": "Healthcare AI spending reached $5B."},
            {"segment_id": "s3", "text": "Some studies show AI adoption grew only 25% in 2025."},
        ],
    }),
    "entity resolution": json.dumps({
        "entities": [
            {"entity_id": "e-ai", "type": "technology", "names": ["AI", "Artificial Intelligence"]},
            {"entity_id": "e-health", "type": "domain", "names": ["Healthcare"]},
        ],
        "relationships": [
            {"rel_id": "r1", "type": "applied_in", "from_id": "e-ai", "to_id": "e-health", "confidence": 0.9},
        ],
    }),
    "claim extraction": json.dumps({
        "claims": [
            {"claim_id": "c1", "statement": "AI adoption in healthcare grew 40% in 2025",
             "claim_type": "metric", "entities": ["e-ai", "e-health"],
             "citations": [{"doc_id": "d1", "segment_id": "s1"}],
             "evidence_strength": 0.8, "confidence": 0.85, "status": "active"},
            {"claim_id": "c2", "statement": "Healthcare AI spending reached $5B",
             "claim_type": "metric", "entities": ["e-ai", "e-health"],
             "citations": [{"doc_id": "d2", "segment_id": "s2"}],
             "evidence_strength": 0.9, "confidence": 0.9, "status": "active"},
            {"claim_id": "c3", "statement": "AI adoption grew only 25% in 2025",
             "claim_type": "metric", "entities": ["e-ai"],
             "citations": [{"doc_id": "d3", "segment_id": "s3"}],
             "evidence_strength": 0.7, "confidence": 0.75, "status": "active"},
        ],
    }),
    "metric extraction": json.dumps({
        "metrics": [
            {"metric_id": "m1", "name": "AI adoption growth", "unit": "percent", "dimensions": {"sector": "healthcare"}},
            {"metric_id": "m2", "name": "AI spending", "unit": "USD_billion", "dimensions": {"sector": "healthcare"}},
        ],
        "metric_points": [
            {"point_id": "p1", "metric_id": "m1", "t": "2025", "value": 40.0, "doc_id": "d1", "segment_id": "s1", "confidence": 0.85},
            {"point_id": "p2", "metric_id": "m2", "t": "2025", "value": 5.0, "doc_id": "d2", "segment_id": "s2", "confidence": 0.9},
        ],
    }),
    "contradiction detection": json.dumps({
        "contradictions": [
            {"claim_a_id": "c1", "claim_b_id": "c3",
             "reason": "Conflicting growth figures: 40% vs 25%", "severity": "medium"},
        ],
        "updated_claim_ids": ["c1", "c3"],
    }),
    "synthesis": json.dumps({
        "summary": "AI adoption in healthcare is growing but exact figures are disputed.",
        "key_findings": [
            {"finding": "Growth between 25-40%", "claim_ids": ["c1", "c3"]},
            {"finding": "Spending reached $5B", "claim_ids": ["c2"]},
        ],
        "metrics_summary": "Growth rate disputed, spending confirmed at $5B",
        "changes_since_last": "First snapshot — all data is new",
        "contradictions": [{"claims": ["c1", "c3"], "issue": "growth rate discrepancy"}],
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
    registry.register(NormalizerAgent())
    registry.register(EntityResolverAgent())
    registry.register(ClaimExtractorAgent())
    registry.register(MetricExtractorAgent())
    registry.register(ContradictionAgent())
    registry.register(DeltaAgent())
    registry.register(SynthesizerAgent())
    registry.register(PublisherAgent())
    yield
    registry.clear()
    out_dir = PUBLISH_ROOT / "topic"
    if out_dir.exists():
        shutil.rmtree(out_dir)


def test_dossier_graph_end_to_end():
    graph = load_graph(GRAPH_PATH)

    state = create_initial_state(
        scope_type="topic", scope_id="healthcare-ai",
        run_id="dossier-integration-1", graph_id="dossier_graph",
        extra={
            "sources": [
                {"uri": "http://src1.com", "source_type": "web"},
                {"uri": "http://src2.com", "source_type": "web"},
                {"uri": "http://src3.com", "source_type": "web"},
            ],
            "previous_snapshot": None,
            "existing_claims": [],
        },
    )

    result = execute_graph(graph, state, model_call=_mock_model)

    assert result.status == "completed"
    assert len(result.events) == 9  # all 9 nodes

    # Claims and contradictions
    assert len(result.state["claims"]) == 3
    assert len(result.state["contradictions"]) == 1
    assert "c1" in result.state["updated_claim_ids"]

    # Metrics
    assert len(result.state["metrics"]) == 2
    assert len(result.state["metric_points"]) == 2

    # Synthesis
    assert "summary" in result.state["synthesis"]
    assert len(result.state["synthesis"]["key_findings"]) == 2

    # Snapshot + delta
    assert result.state["snapshot_id"]
    assert len(result.state["delta_json"]["added_claims"]) == 3

    # Publish
    publish_dir = Path(result.state["publish_dir"])
    assert (publish_dir / "manifest.json").exists()
