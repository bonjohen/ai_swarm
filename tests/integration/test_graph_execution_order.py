"""Integration tests: verify multi-agent graph execution follows YAML-defined node order.

Tests cover all 4 graph loops (story, certification, dossier, lab) and verify:
1. Exact node execution order matches YAML chain
2. Each event's agent_id matches the YAML spec
3. State accumulates all declared outputs
4. on_fail routing follows graph definition
5. on_fail cycle limit prevents infinite loops
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from agents import registry
from agents.audience_compliance_agent import AudienceComplianceAgent
from agents.canon_updater_agent import CanonUpdaterAgent
from agents.claim_extractor_agent import ClaimExtractorAgent
from agents.contradiction_agent import ContradictionAgent
from agents.delta_agent import DeltaAgent
from agents.entity_resolver_agent import EntityResolverAgent
from agents.ingestor_agent import IngestorAgent
from agents.lesson_composer_agent import LessonComposerAgent
from agents.metric_extractor_agent import MetricExtractorAgent
from agents.narration_formatter_agent import NarrationFormatterAgent
from agents.normalizer_agent import NormalizerAgent
from agents.plot_architect_agent import PlotArchitectAgent
from agents.premise_architect_agent import PremiseArchitectAgent
from agents.publisher_agent import PUBLISH_ROOT, PublisherAgent
from agents.qa_validator_agent import QAValidatorAgent
from agents.question_generator_agent import QuestionGeneratorAgent
from agents.scene_writer_agent import SceneWriterAgent
from agents.story_memory_loader_agent import StoryMemoryLoaderAgent
from agents.synthesizer_agent import SynthesizerAgent
from core.orchestrator import execute_graph
from core.state import create_initial_state
from data.dao_characters import insert_character
from data.dao_story_worlds import insert_world
from data.dao_threads import insert_thread
from data.db import get_initialized_connection
from graphs.graph_types import Graph, load_graph

GRAPHS_DIR = Path(__file__).parent.parent.parent / "graphs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_expected_order(graph: Graph) -> list[str]:
    """Walk graph from entry following .next to build expected [node_name, ...] sequence."""
    order = []
    current = graph.entry
    visited = set()
    while current is not None:
        if current in visited:
            raise RuntimeError(f"Cycle detected at node '{current}'")
        visited.add(current)
        order.append(current)
        node = graph.get_node(current)
        if node.end:
            break
        current = node.next
    return order


def _build_agent_id_map(graph: Graph) -> dict[str, str]:
    """Map node_name -> YAML agent field for every node in the graph."""
    return {name: node.agent for name, node in graph.nodes.items()}


# ---------------------------------------------------------------------------
# Story graph mock responses (reused from test_story_graph.py)
# ---------------------------------------------------------------------------

_STORY_MOCK_RESPONSES = {
    "premise architect": json.dumps({
        "premise": "Aria discovers a glowing crystal shard.",
        "episode_title": "The Shard of Storms",
        "selected_threads": ["thread-crystal-storms"],
    }),
    "plot architect": json.dumps({
        "act_structure": [
            {"act": 1, "title": "Discovery", "summary": "Aria finds the shard"},
            {"act": 2, "title": "Journey", "summary": "Aria and Bram cross the bridge"},
            {"act": 3, "title": "Revelation", "summary": "The truth about storms"},
        ],
        "scene_plans": [
            {"scene_id": "s1", "act": 1, "pov_character": "Aria", "conflict": "Crystal appears", "objective": "Find shard", "stakes": "Miss clue", "emotional_arc": "curiosity"},
            {"scene_id": "s2", "act": 2, "pov_character": "Bram", "conflict": "Bridge unstable", "objective": "Cross safely", "stakes": "Fall", "emotional_arc": "fear"},
            {"scene_id": "s3", "act": 3, "pov_character": "Aria", "conflict": "Storm", "objective": "Reach peak", "stakes": "Islands break", "emotional_arc": "triumph"},
        ],
    }),
    "scene writer": json.dumps({
        "scenes": [
            {"scene_id": "s1", "text": "Aria spotted the crystal shard.", "word_count": 6},
            {"scene_id": "s2", "text": "Bram gripped the rope bridge.", "word_count": 6},
            {"scene_id": "s3", "text": "The storm calmed as light burst forth.", "word_count": 7},
        ],
        "episode_text": "Aria spotted the crystal shard.\n\nBram gripped the rope bridge.\n\nThe storm calmed as light burst forth.",
    }),
    "canon updater": json.dumps({
        "new_claims": [
            {"claim_id": "cl-storm-shard", "statement": "A crystal shard calms storms", "claim_type": "canon_fact", "entities": ["crystal-shard"], "citations": [{"doc_id": "eldoria-1-E001", "segment_id": "s1"}], "evidence_strength": 0.9, "confidence": 0.95},
        ],
        "updated_characters": [{"character_id": "char-aria", "changes": {"beliefs": ["crystal power"]}}],
        "new_threads": [],
        "resolved_threads": [],
        "new_entities": [{"entity_id": "crystal-shard", "type": "artifact", "name": "Storm Shard"}],
    }),
    "contradiction detection": json.dumps({
        "contradictions": [],
        "updated_claim_ids": [],
    }),
    "audience compliance": json.dumps({
        "compliance_status": "PASS",
        "compliance_violations": [],
    }),
    "narration formatter": json.dumps({
        "narration_script": "[NARRATOR] Welcome back to Eldoria.",
        "recap": "Previously on Eldoria: storms battered the islands.",
    }),
}


def _story_mock_model(system_prompt: str, user_message: str) -> str:
    for key, response in _STORY_MOCK_RESPONSES.items():
        if key in system_prompt.lower():
            return response
    return json.dumps({})


# ---------------------------------------------------------------------------
# Certification graph mock responses (reused from test_cert_graph.py)
# ---------------------------------------------------------------------------

_CERT_MOCK_RESPONSES = {
    "ingestion": json.dumps({
        "doc_ids": ["d1"],
        "segment_ids": ["s1", "s2"],
        "source_docs": [{"doc_id": "d1", "uri": "http://cert.example.com"}],
        "source_segments": [
            {"segment_id": "s1", "text": "Cloud provides scalable resources."},
            {"segment_id": "s2", "text": "Security includes encryption and IAM."},
        ],
    }),
    "entity resolution": json.dumps({
        "entities": [
            {"entity_id": "e-cloud", "type": "technology", "names": ["Cloud"]},
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
            {"segment_id": "s1", "text": "Cloud provides scalable resources."},
            {"segment_id": "s2", "text": "Security includes encryption and IAM."},
        ],
    }),
    "claim extraction": json.dumps({
        "claims": [
            {"claim_id": "c1", "statement": "Cloud provides scalable resources", "claim_type": "factual", "entities": ["e-cloud"], "citations": [{"doc_id": "d1", "segment_id": "s1"}], "evidence_strength": 0.9, "confidence": 0.95, "status": "active"},
            {"claim_id": "c2", "statement": "Security includes encryption and IAM", "claim_type": "factual", "entities": ["e-sec"], "citations": [{"doc_id": "d1", "segment_id": "s2"}], "evidence_strength": 0.85, "confidence": 0.9, "status": "active"},
        ],
    }),
    "lesson composition": json.dumps({
        "modules": [
            {"module_id": "mod-1", "objective_id": "obj-1", "level": "L1", "title": "Cloud Overview", "content_json": {"sections": ["Intro"], "claim_refs": ["c1"]}},
            {"module_id": "mod-2", "objective_id": "obj-2", "level": "L1", "title": "Security Overview", "content_json": {"sections": ["Encryption"], "claim_refs": ["c2"]}},
        ],
    }),
    "question generation": json.dumps({
        "questions": [
            {"question_id": "q1", "objective_id": "obj-1", "qtype": "multiple_choice", "content_json": {"question": "What does cloud provide?", "options": ["Scale", "Nothing"], "correct_answer": "Scale", "explanation": "Cloud = scale"}, "grounding_claim_ids": ["c1"]},
            {"question_id": "q1b", "objective_id": "obj-1", "qtype": "true_false", "content_json": {"question": "Cloud scales?", "options": ["True", "False"], "correct_answer": "True", "explanation": "Yes"}, "grounding_claim_ids": ["c1"]},
            {"question_id": "q2", "objective_id": "obj-2", "qtype": "true_false", "content_json": {"question": "IAM is security?", "options": ["True", "False"], "correct_answer": "True", "explanation": "Yes"}, "grounding_claim_ids": ["c2"]},
        ],
    }),
}


def _cert_mock_model(system_prompt: str, user_message: str) -> str:
    for key, response in _CERT_MOCK_RESPONSES.items():
        if key in system_prompt.lower():
            return response
    return json.dumps({})


# ---------------------------------------------------------------------------
# Dossier graph mock responses (reused from test_dossier_graph.py)
# ---------------------------------------------------------------------------

_DOSSIER_MOCK_RESPONSES = {
    "ingestion": json.dumps({
        "doc_ids": ["d1", "d2"],
        "segment_ids": ["s1", "s2"],
        "source_docs": [{"doc_id": "d1", "uri": "http://src1.com"}, {"doc_id": "d2", "uri": "http://src2.com"}],
        "source_segments": [
            {"segment_id": "s1", "text": "AI adoption grew 40% in 2025."},
            {"segment_id": "s2", "text": "Healthcare AI spending reached $5B."},
        ],
    }),
    "normalization": json.dumps({
        "normalized_segments": [
            {"segment_id": "s1", "text": "AI adoption grew 40% in 2025."},
            {"segment_id": "s2", "text": "Healthcare AI spending reached $5B."},
        ],
    }),
    "entity resolution": json.dumps({
        "entities": [
            {"entity_id": "e-ai", "type": "technology", "names": ["AI"]},
            {"entity_id": "e-health", "type": "domain", "names": ["Healthcare"]},
        ],
        "relationships": [],
    }),
    "claim extraction": json.dumps({
        "claims": [
            {"claim_id": "c1", "statement": "AI adoption grew 40%", "claim_type": "metric", "entities": ["e-ai"], "citations": [{"doc_id": "d1", "segment_id": "s1"}], "evidence_strength": 0.8, "confidence": 0.85, "status": "active"},
            {"claim_id": "c2", "statement": "Spending reached $5B", "claim_type": "metric", "entities": ["e-health"], "citations": [{"doc_id": "d2", "segment_id": "s2"}], "evidence_strength": 0.9, "confidence": 0.9, "status": "active"},
        ],
    }),
    "metric extraction": json.dumps({
        "metrics": [
            {"metric_id": "m1", "name": "AI adoption growth", "unit": "percent", "dimensions": {"sector": "healthcare"}},
        ],
        "metric_points": [
            {"point_id": "p1", "metric_id": "m1", "t": "2025", "value": 40.0, "doc_id": "d1", "segment_id": "s1", "confidence": 0.85},
        ],
    }),
    "contradiction detection": json.dumps({
        "contradictions": [],
        "updated_claim_ids": [],
    }),
    "synthesis": json.dumps({
        "summary": "AI adoption growing.",
        "key_findings": [{"finding": "Growth 40%", "claim_ids": ["c1"]}],
        "metrics_summary": "Growth confirmed",
        "changes_since_last": "First snapshot",
        "contradictions": [],
    }),
}


def _dossier_mock_model(system_prompt: str, user_message: str) -> str:
    for key, response in _DOSSIER_MOCK_RESPONSES.items():
        if key in system_prompt.lower():
            return response
    return json.dumps({})


# ---------------------------------------------------------------------------
# Lab graph mock responses (reused from test_lab_graph.py)
# ---------------------------------------------------------------------------

_LAB_MOCK_RESPONSES = {
    "ingestion": json.dumps({
        "doc_ids": ["d1"],
        "segment_ids": ["s1"],
        "source_docs": [{"doc_id": "d1", "uri": "suite-config"}],
        "source_segments": [{"segment_id": "s1", "text": "benchmark config"}],
        "tasks": [{"task_id": "t1", "category": "summarization"}],
        "models": [{"model_id": "deepseek-r1:1.5b"}],
        "hw_spec": {"gpu": "RTX 4090", "ram": "64GB"},
    }),
    "synthesis": json.dumps({
        "summary": "Model performed adequately.",
        "key_findings": [{"finding": "deepseek fast", "claim_ids": []}],
        "metrics_summary": "Average accuracy 78%",
        "changes_since_last": "First run",
        "contradictions": [],
        "results": [{"task_id": "t1", "model_id": "deepseek-r1:1.5b", "score": 0.75}],
        "scores": {"deepseek-r1:1.5b": 0.75},
        "routing_config": {"local_threshold": 0.7, "frontier_threshold": 0.9, "recommended": {"summarization": "deepseek-r1:1.5b"}},
    }),
    "metric extraction": json.dumps({
        "metrics": [
            {"metric_id": "m-acc", "name": "accuracy", "unit": "ratio", "dimensions": {"suite": "bench-1"}},
        ],
        "metric_points": [
            {"point_id": "p1", "metric_id": "m-acc", "t": "2026-02", "value": 0.78, "doc_id": "d1", "segment_id": "s1", "confidence": 0.9},
        ],
    }),
}


def _lab_mock_model(system_prompt: str, user_message: str) -> str:
    for key, response in _LAB_MOCK_RESPONSES.items():
        if key in system_prompt.lower():
            return response
    return json.dumps({})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def story_db():
    """In-memory DB with world, characters, and a thread for story tests."""
    conn = get_initialized_connection(":memory:")
    now = "2026-01-01T00:00:00Z"
    insert_world(
        conn, world_id="eldoria-1", name="Eldoria", genre="fantasy", tone="whimsical",
        setting={"geography": "Floating islands"}, thematic_constraints=["friendship"],
        audience_profile={"age_range": "8-12", "vocabulary_level": "intermediate"},
        created_at=now, updated_at=now,
    )
    insert_character(conn, character_id="char-aria", world_id="eldoria-1", name="Aria", role="protagonist", traits=["brave", "curious"])
    insert_character(conn, character_id="char-bram", world_id="eldoria-1", name="Bram", role="supporting", traits=["loyal", "cautious"])
    insert_thread(conn, thread_id="thread-crystal-storms", world_id="eldoria-1", title="The Crystal Storms", introduced_in_episode=0, thematic_tag="mystery", related_character_ids=["char-aria"])
    yield conn
    conn.close()


@pytest.fixture
def register_story_agents():
    registry.clear()
    registry.register(StoryMemoryLoaderAgent())
    registry.register(PremiseArchitectAgent())
    registry.register(PlotArchitectAgent())
    registry.register(SceneWriterAgent())
    registry.register(CanonUpdaterAgent())
    registry.register(AudienceComplianceAgent())
    registry.register(NarrationFormatterAgent())
    registry.register(ContradictionAgent())
    registry.register(QAValidatorAgent())
    registry.register(DeltaAgent())
    registry.register(PublisherAgent())
    yield
    registry.clear()
    out_dir = PUBLISH_ROOT / "story"
    if out_dir.exists():
        shutil.rmtree(out_dir)


@pytest.fixture
def register_cert_agents():
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
    out_dir = PUBLISH_ROOT / "cert"
    if out_dir.exists():
        shutil.rmtree(out_dir)


@pytest.fixture
def register_dossier_agents():
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


@pytest.fixture
def register_lab_agents():
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


# ---------------------------------------------------------------------------
# Story graph tests (11 nodes)
# ---------------------------------------------------------------------------

class TestStoryGraphExecutionOrder:

    def _run_story(self, story_db) -> Any:
        graph = load_graph(GRAPHS_DIR / "story_graph.yaml")
        state = create_initial_state(
            scope_type="story", scope_id="eldoria-1",
            run_id="order-story-1", graph_id="story_graph",
            extra={
                "world_id": "eldoria-1", "conn": story_db,
                "claims": [], "metrics": [], "doc_ids": [],
                "segment_ids": [], "violations": [],
            },
        )
        return execute_graph(graph, state, model_call=_story_mock_model), graph

    def test_story_graph_node_order(self, story_db, register_story_agents):
        result, graph = self._run_story(story_db)
        expected = _extract_expected_order(graph)
        actual = [e["node_id"] for e in result.events]
        assert actual == expected

    def test_story_graph_agent_ids_match(self, story_db, register_story_agents):
        result, graph = self._run_story(story_db)
        agent_map = _build_agent_id_map(graph)
        for event in result.events:
            node_id = event["node_id"]
            expected_agent = agent_map[node_id]
            assert event["agent_id"] == expected_agent, (
                f"Node '{node_id}': expected agent_id='{expected_agent}', "
                f"got '{event['agent_id']}'"
            )

    def test_story_graph_state_accumulation(self, story_db, register_story_agents):
        result, graph = self._run_story(story_db)
        assert result.status == "completed"
        for node_name, node in graph.nodes.items():
            for output_key in node.outputs:
                assert output_key in result.state, (
                    f"Node '{node_name}' declared output '{output_key}' "
                    f"not found in final state"
                )

    def test_story_graph_on_fail_routing(self, story_db, register_story_agents):
        """QA FAIL on first pass routes to scene_writing, then QA PASS on second."""
        graph = load_graph(GRAPHS_DIR / "story_graph.yaml")
        state = create_initial_state(
            scope_type="story", scope_id="eldoria-1",
            run_id="order-story-onfail", graph_id="story_graph",
            extra={
                "world_id": "eldoria-1", "conn": story_db,
                "claims": [], "metrics": [], "doc_ids": [],
                "segment_ids": [], "violations": [],
            },
        )

        # Patch QA to fail once then pass: inject a compliance violation on
        # first QA run, then clear it.
        qa_call_count = {"n": 0}
        original_run = QAValidatorAgent.run

        def patched_qa_run(self_agent, state, model_call=None):
            qa_call_count["n"] += 1
            if qa_call_count["n"] == 1:
                # Force audience compliance FAIL to trigger on_fail
                state["compliance_status"] = "FAIL"
                state["compliance_violations"] = [{"issue": "test violation"}]
            else:
                # Clear the violation for second pass
                state["compliance_status"] = "PASS"
                state["compliance_violations"] = []
            return original_run(self_agent, state, model_call=model_call)

        QAValidatorAgent.run = patched_qa_run
        try:
            result = execute_graph(graph, state, model_call=_story_mock_model)
        finally:
            QAValidatorAgent.run = original_run

        assert result.status == "completed"
        node_ids = [e["node_id"] for e in result.events]

        # First qa_validation should fail and route to scene_writing
        first_qa_idx = node_ids.index("qa_validation")
        assert result.events[first_qa_idx]["status"] == "failed"

        # After the failed qa_validation, the next node should be scene_writing (on_fail target)
        assert node_ids[first_qa_idx + 1] == "scene_writing"

        # Second qa_validation should pass
        second_qa_idx = node_ids.index("qa_validation", first_qa_idx + 1)
        assert result.events[second_qa_idx]["status"] == "success"

    def test_story_graph_on_fail_cycle_limit(self, story_db, register_story_agents):
        """Always-fail QA aborts after max_on_fail_cycles (3) re-routes."""
        graph = load_graph(GRAPHS_DIR / "story_graph.yaml")
        state = create_initial_state(
            scope_type="story", scope_id="eldoria-1",
            run_id="order-story-cyclelimit", graph_id="story_graph",
            extra={
                "world_id": "eldoria-1", "conn": story_db,
                "claims": [], "metrics": [], "doc_ids": [],
                "segment_ids": [], "violations": [],
            },
        )

        # Patch QA to always force a FAIL
        original_run = QAValidatorAgent.run

        def always_fail_qa(self_agent, state, model_call=None):
            state["compliance_status"] = "FAIL"
            state["compliance_violations"] = [{"issue": "permanent violation"}]
            return original_run(self_agent, state, model_call=model_call)

        QAValidatorAgent.run = always_fail_qa
        try:
            result = execute_graph(graph, state, model_call=_story_mock_model)
        finally:
            QAValidatorAgent.run = original_run

        assert result.status == "failed"

        # Count how many times qa_validation appears as failed
        qa_fail_events = [
            e for e in result.events
            if e["node_id"] == "qa_validation" and e["status"] == "failed"
        ]
        # max_on_fail_cycles = 3, so we get the initial fail + 3 more = 4 total qa_validation failures
        # Actually: first fail (cycle 1), route to scene_writing, back to qa (cycle 2 fail),
        # route to scene_writing, back to qa (cycle 3 fail), route to scene_writing,
        # back to qa (cycle 4 fail > max 3), abort.
        # The count check: on_fail_counts increments each time QA fails with on_fail.
        # It aborts when count > 3, so we get exactly 4 QA fail events.
        assert len(qa_fail_events) == 4


# ---------------------------------------------------------------------------
# Certification graph tests (9 nodes)
# ---------------------------------------------------------------------------

class TestCertGraphExecutionOrder:

    def _run_cert(self) -> Any:
        graph = load_graph(GRAPHS_DIR / "certification_graph.yaml")
        state = create_initial_state(
            scope_type="cert", scope_id="aws-101",
            run_id="order-cert-1", graph_id="certification_graph",
            extra={
                "sources": [{"uri": "http://cert.example.com", "source_type": "web"}],
                "previous_snapshot": None, "existing_claims": [], "metrics": [],
                "objectives": [
                    {"objective_id": "obj-1", "cert_id": "aws-101", "code": "1.1", "text": "Cloud Fundamentals", "weight": 1.0},
                    {"objective_id": "obj-2", "cert_id": "aws-101", "code": "1.2", "text": "Security Basics", "weight": 0.5},
                ],
            },
        )
        return execute_graph(graph, state, model_call=_cert_mock_model), graph

    def test_cert_graph_node_order(self, register_cert_agents):
        result, graph = self._run_cert()
        expected = _extract_expected_order(graph)
        actual = [e["node_id"] for e in result.events]
        assert actual == expected

    def test_cert_graph_agent_ids_match(self, register_cert_agents):
        result, graph = self._run_cert()
        agent_map = _build_agent_id_map(graph)
        for event in result.events:
            node_id = event["node_id"]
            expected_agent = agent_map[node_id]
            assert event["agent_id"] == expected_agent, (
                f"Node '{node_id}': expected agent_id='{expected_agent}', "
                f"got '{event['agent_id']}'"
            )

    def test_cert_graph_state_accumulation(self, register_cert_agents):
        result, graph = self._run_cert()
        assert result.status == "completed"
        for node_name, node in graph.nodes.items():
            for output_key in node.outputs:
                assert output_key in result.state, (
                    f"Node '{node_name}' declared output '{output_key}' "
                    f"not found in final state"
                )


# ---------------------------------------------------------------------------
# Dossier graph tests (9 nodes)
# ---------------------------------------------------------------------------

class TestDossierGraphExecutionOrder:

    def _run_dossier(self) -> Any:
        graph = load_graph(GRAPHS_DIR / "dossier_graph.yaml")
        state = create_initial_state(
            scope_type="topic", scope_id="healthcare-ai",
            run_id="order-dossier-1", graph_id="dossier_graph",
            extra={
                "sources": [{"uri": "http://src1.com", "source_type": "web"}],
                "previous_snapshot": None, "existing_claims": [],
            },
        )
        return execute_graph(graph, state, model_call=_dossier_mock_model), graph

    def test_dossier_graph_node_order(self, register_dossier_agents):
        result, graph = self._run_dossier()
        expected = _extract_expected_order(graph)
        actual = [e["node_id"] for e in result.events]
        assert actual == expected

    def test_dossier_graph_agent_ids_match(self, register_dossier_agents):
        result, graph = self._run_dossier()
        agent_map = _build_agent_id_map(graph)
        for event in result.events:
            node_id = event["node_id"]
            expected_agent = agent_map[node_id]
            assert event["agent_id"] == expected_agent, (
                f"Node '{node_id}': expected agent_id='{expected_agent}', "
                f"got '{event['agent_id']}'"
            )

    def test_dossier_graph_state_accumulation(self, register_dossier_agents):
        result, graph = self._run_dossier()
        assert result.status == "completed"
        for node_name, node in graph.nodes.items():
            for output_key in node.outputs:
                assert output_key in result.state, (
                    f"Node '{node_name}' declared output '{output_key}' "
                    f"not found in final state"
                )


# ---------------------------------------------------------------------------
# Lab graph tests (7 nodes)
# ---------------------------------------------------------------------------

class TestLabGraphExecutionOrder:

    def _run_lab(self) -> Any:
        graph = load_graph(GRAPHS_DIR / "lab_graph.yaml")
        state = create_initial_state(
            scope_type="lab", scope_id="bench-1",
            run_id="order-lab-1", graph_id="lab_graph",
            extra={
                "suite_config": {"suite_id": "bench-1", "tasks": ["t1"]},
                "previous_snapshot": None, "claims": [], "metrics": [],
                "tasks": [{"task_id": "t1", "category": "summarization"}],
                "models": [{"model_id": "deepseek-r1:1.5b"}],
                "hw_spec": {"gpu": "RTX 4090", "ram": "64GB"},
                "normalized_segments": [{"segment_id": "s1", "text": "benchmark results"}],
            },
        )
        return execute_graph(graph, state, model_call=_lab_mock_model), graph

    def test_lab_graph_node_order(self, register_lab_agents):
        result, graph = self._run_lab()
        expected = _extract_expected_order(graph)
        actual = [e["node_id"] for e in result.events]
        assert actual == expected

    def test_lab_graph_agent_ids_match(self, register_lab_agents):
        result, graph = self._run_lab()
        agent_map = _build_agent_id_map(graph)
        for event in result.events:
            node_id = event["node_id"]
            expected_agent = agent_map[node_id]
            assert event["agent_id"] == expected_agent, (
                f"Node '{node_id}': expected agent_id='{expected_agent}', "
                f"got '{event['agent_id']}'"
            )

    def test_lab_graph_state_accumulation(self, register_lab_agents):
        result, graph = self._run_lab()
        assert result.status == "completed"
        for node_name, node in graph.nodes.items():
            for output_key in node.outputs:
                assert output_key in result.state, (
                    f"Node '{node_name}' declared output '{output_key}' "
                    f"not found in final state"
                )


# ---------------------------------------------------------------------------
# Cross-graph structural validation
# ---------------------------------------------------------------------------

class TestAllGraphsStructural:
    """Structural tests applied to every graph YAML — no agent execution needed."""

    @pytest.fixture(params=[
        "story_graph.yaml",
        "certification_graph.yaml",
        "dossier_graph.yaml",
        "lab_graph.yaml",
    ])
    def graph(self, request) -> Graph:
        return load_graph(GRAPHS_DIR / request.param)

    def test_all_graphs_entry_node_exists(self, graph):
        assert graph.entry in graph.nodes, (
            f"Graph '{graph.id}': entry node '{graph.entry}' not in nodes dict"
        )

    def test_all_graphs_next_chain_complete(self, graph):
        """Following next from entry reaches end=true without dangling references."""
        visited = set()
        current = graph.entry
        last_visited = current
        while current is not None:
            assert current in graph.nodes, (
                f"Graph '{graph.id}': node '{current}' referenced in .next "
                f"but not defined in nodes"
            )
            assert current not in visited, (
                f"Graph '{graph.id}': cycle detected at node '{current}'"
            )
            visited.add(current)
            last_visited = current
            node = graph.get_node(current)
            if node.end:
                break
            assert node.next is not None, (
                f"Graph '{graph.id}': node '{current}' has end=false "
                f"but no .next defined"
            )
            current = node.next
        # Must have reached an end node
        last_node = graph.get_node(last_visited)
        assert last_node.end, (
            f"Graph '{graph.id}': chain from entry does not reach an end node"
        )

    def test_all_graphs_on_fail_targets_exist(self, graph):
        """Every on_fail target is a valid node in the graph."""
        for node_name, node in graph.nodes.items():
            if node.on_fail:
                assert node.on_fail in graph.nodes, (
                    f"Graph '{graph.id}': node '{node_name}' has "
                    f"on_fail='{node.on_fail}' which is not a valid node"
                )
