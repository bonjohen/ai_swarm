"""Integration test: certification graph end-to-end (1 cert, 2 objectives)."""

import json
import shutil
from pathlib import Path

import pytest

from agents import registry
from agents.ingestor_agent import IngestorAgent
from agents.normalizer_agent import NormalizerAgent
from agents.entity_resolver_agent import EntityResolverAgent
from agents.claim_extractor_agent import ClaimExtractorAgent
from agents.lesson_composer_agent import LessonComposerAgent
from agents.question_generator_agent import QuestionGeneratorAgent
from agents.qa_validator_agent import QAValidatorAgent
from agents.delta_agent import DeltaAgent
from agents.publisher_agent import PublisherAgent, PUBLISH_ROOT
from core.orchestrator import execute_graph
from core.state import create_initial_state
from graphs.graph_types import load_graph

GRAPH_PATH = Path(__file__).parent.parent.parent / "graphs" / "certification_graph.yaml"

_MOCK_RESPONSES = {
    "ingestion": json.dumps({
        "doc_ids": ["d1"],
        "segment_ids": ["s1", "s2"],
        "source_docs": [{"doc_id": "d1", "uri": "http://cert.example.com"}],
        "source_segments": [
            {"segment_id": "s1", "text": "Cloud computing provides scalable resources."},
            {"segment_id": "s2", "text": "Security best practices include encryption and IAM."},
        ],
    }),
    "entity resolution": json.dumps({
        "entities": [
            {"entity_id": "e-cloud", "type": "technology", "names": ["Cloud Computing"]},
            {"entity_id": "e-sec", "type": "domain", "names": ["Security"]},
        ],
        "relationships": [],
        "objectives": [
            {"objective_id": "obj-1", "cert_id": "aws-101", "code": "1.1", "text": "Cloud Fundamentals", "weight": 1.0},
            {"objective_id": "obj-2", "cert_id": "aws-101", "code": "1.2", "text": "Security Basics", "weight": 0.5},
        ],
    }),
    "normalization": json.dumps({
        "normalized_segments": [
            {"segment_id": "s1", "text": "Cloud computing provides scalable resources."},
            {"segment_id": "s2", "text": "Security best practices include encryption and IAM."},
        ],
    }),
    "claim extraction": json.dumps({
        "claims": [
            {"claim_id": "c1", "statement": "Cloud computing provides scalable resources",
             "claim_type": "factual", "entities": ["e-cloud"],
             "citations": [{"doc_id": "d1", "segment_id": "s1"}],
             "evidence_strength": 0.9, "confidence": 0.95, "status": "active"},
            {"claim_id": "c2", "statement": "Security best practices include encryption and IAM",
             "claim_type": "factual", "entities": ["e-sec"],
             "citations": [{"doc_id": "d1", "segment_id": "s2"}],
             "evidence_strength": 0.85, "confidence": 0.9, "status": "active"},
        ],
    }),
    "lesson composition": json.dumps({
        "modules": [
            {"module_id": "mod-1", "objective_id": "obj-1", "level": "L1",
             "title": "Cloud Fundamentals Overview",
             "content_json": {"sections": ["Intro to cloud"], "claim_refs": ["c1"]}},
            {"module_id": "mod-2", "objective_id": "obj-2", "level": "L1",
             "title": "Security Basics Overview",
             "content_json": {"sections": ["Encryption basics"], "claim_refs": ["c2"]}},
        ],
    }),
    "question generation": json.dumps({
        "questions": [
            {"question_id": "q1", "objective_id": "obj-1", "qtype": "multiple_choice",
             "content_json": {"question": "What does cloud provide?", "options": ["Scale", "Nothing"],
                              "correct_answer": "Scale", "explanation": "Cloud = scale"},
             "grounding_claim_ids": ["c1"]},
            {"question_id": "q2", "objective_id": "obj-2", "qtype": "true_false",
             "content_json": {"question": "IAM is a security best practice?", "options": ["True", "False"],
                              "correct_answer": "True", "explanation": "Yes."},
             "grounding_claim_ids": ["c2"]},
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
    registry.register(NormalizerAgent())
    registry.register(EntityResolverAgent())
    registry.register(ClaimExtractorAgent())
    registry.register(LessonComposerAgent())
    registry.register(QuestionGeneratorAgent())
    registry.register(QAValidatorAgent())
    registry.register(DeltaAgent())
    registry.register(PublisherAgent())
    yield
    registry.clear()
    # Clean up publish output
    out_dir = PUBLISH_ROOT / "cert"
    if out_dir.exists():
        shutil.rmtree(out_dir)


def test_certification_graph_end_to_end():
    graph = load_graph(GRAPH_PATH)

    state = create_initial_state(
        scope_type="cert", scope_id="aws-101",
        run_id="cert-integration-1", graph_id="certification_graph",
        extra={
            "sources": [{"uri": "http://cert.example.com", "source_type": "web"}],
            "previous_snapshot": None,
            "existing_claims": [],
            "metrics": [],
            "objectives": [
                {"objective_id": "obj-1", "cert_id": "aws-101", "code": "1.1", "text": "Cloud Fundamentals", "weight": 1.0},
                {"objective_id": "obj-2", "cert_id": "aws-101", "code": "1.2", "text": "Security Basics", "weight": 0.5},
            ],
        },
    )

    result = execute_graph(graph, state, model_call=_mock_model)

    assert result.status == "completed"
    assert len(result.events) == 9  # all 9 nodes

    # Verify all expected state keys
    assert len(result.state["doc_ids"]) == 1
    assert len(result.state["claims"]) == 2
    assert len(result.state["modules"]) == 2
    assert len(result.state["questions"]) == 2
    assert result.state["gate_status"] == "PASS"
    assert result.state["snapshot_id"]
    assert result.state["delta_json"]["added_claims"] == ["c1", "c2"]

    # Verify publish output
    assert result.state["publish_dir"]
    publish_dir = Path(result.state["publish_dir"])
    assert (publish_dir / "manifest.json").exists()
    assert (publish_dir / "artifacts.json").exists()
