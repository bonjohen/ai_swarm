"""Integration test: ingestor → normalizer → entity_resolver → claim_extractor chain."""

import json

import pytest
from pydantic import BaseModel

from agents import registry
from agents.base_agent import AgentPolicy, BaseAgent
from agents.ingestor_agent import IngestorAgent
from agents.normalizer_agent import NormalizerAgent
from agents.entity_resolver_agent import EntityResolverAgent
from agents.claim_extractor_agent import ClaimExtractorAgent
from agents.qa_validator_agent import QAValidatorAgent
from agents.delta_agent import DeltaAgent
from core.orchestrator import execute_graph
from core.state import create_initial_state
from graphs.graph_types import Graph, GraphNode


# --- Mock model responses for each agent step ---

_MOCK_RESPONSES = {
    "ingestion": json.dumps({
        "doc_ids": ["doc-1"],
        "segment_ids": ["seg-1", "seg-2"],
        "source_docs": [{"doc_id": "doc-1", "uri": "http://test.com"}],
        "source_segments": [
            {"segment_id": "seg-1", "text": "AWS offers scalable cloud computing."},
            {"segment_id": "seg-2", "text": "Azure is a competitor to AWS."},
        ],
    }),
    "normalization": json.dumps({
        "normalized_segments": [
            {"segment_id": "seg-1", "text": "AWS offers scalable cloud computing."},
            {"segment_id": "seg-2", "text": "Azure is a competitor to AWS."},
        ],
    }),
    "entity resolution": json.dumps({
        "entities": [
            {"entity_id": "e-aws", "type": "product", "names": ["AWS", "Amazon Web Services"]},
            {"entity_id": "e-azure", "type": "product", "names": ["Azure", "Microsoft Azure"]},
        ],
        "relationships": [
            {"rel_id": "r-1", "type": "competes_with", "from_id": "e-aws", "to_id": "e-azure", "confidence": 0.9},
        ],
    }),
    "claim extraction": json.dumps({
        "claims": [
            {
                "claim_id": "claim-1",
                "statement": "AWS offers scalable cloud computing",
                "claim_type": "factual",
                "entities": ["e-aws"],
                "citations": [{"doc_id": "doc-1", "segment_id": "seg-1"}],
                "evidence_strength": 0.9,
                "confidence": 0.95,
                "status": "active",
            },
            {
                "claim_id": "claim-2",
                "statement": "Azure is a competitor to AWS",
                "claim_type": "factual",
                "entities": ["e-aws", "e-azure"],
                "citations": [{"doc_id": "doc-1", "segment_id": "seg-2"}],
                "evidence_strength": 0.85,
                "confidence": 0.9,
                "status": "active",
            },
        ],
    }),
}


def _mock_model(system_prompt: str, user_message: str) -> str:
    """Route to correct mock response based on which agent is calling."""
    for agent_key, response in _MOCK_RESPONSES.items():
        if agent_key in system_prompt.lower():
            return response
    # Fallback: return empty
    return json.dumps({})


@pytest.fixture(autouse=True)
def setup_agents():
    registry.clear()
    registry.register(IngestorAgent())
    registry.register(NormalizerAgent())
    registry.register(EntityResolverAgent())
    registry.register(ClaimExtractorAgent())
    registry.register(QAValidatorAgent())
    registry.register(DeltaAgent())
    yield
    registry.clear()


def test_spine_chain_integration():
    """Run the full spine chain and verify state accumulates correctly."""
    graph = Graph(
        id="spine_test",
        entry="ingest",
        nodes={
            "ingest": GraphNode(name="ingest", agent="ingestor", next="normalize"),
            "normalize": GraphNode(
                name="normalize", agent="normalizer",
                inputs=["doc_ids", "segment_ids"], next="resolve",
            ),
            "resolve": GraphNode(
                name="resolve", agent="entity_resolver",
                inputs=["normalized_segments"], next="extract",
            ),
            "extract": GraphNode(
                name="extract", agent="claim_extractor",
                inputs=["normalized_segments", "entities"], next="qa",
            ),
            "qa": GraphNode(name="qa", agent="qa_validator", next="delta"),
            "delta": GraphNode(name="delta", agent="delta", end=True),
        },
    )

    state = create_initial_state(
        scope_type="cert", scope_id="aws-cert",
        run_id="integration-run-1", graph_id="spine_test",
        extra={"sources": [{"uri": "http://test.com", "source_type": "web"}]},
    )

    result = execute_graph(graph, state, model_call=_mock_model)

    assert result.status == "completed"
    assert len(result.events) == 6

    # Verify accumulated state
    assert "doc_ids" in result.state
    assert "normalized_segments" in result.state
    assert "entities" in result.state
    assert "claims" in result.state
    assert "snapshot_id" in result.state
    assert "delta_json" in result.state

    # QA should have passed
    assert result.state.get("gate_status") == "PASS"

    # Delta should show 2 added claims
    assert len(result.state["delta_json"]["added_claims"]) == 2
