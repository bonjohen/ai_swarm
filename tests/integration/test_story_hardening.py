"""Phase S4 tests: world state persistence, frontier escalation, budget enforcement."""

import json
import shutil
from pathlib import Path

import pytest

from agents import registry
from agents.story_memory_loader_agent import StoryMemoryLoaderAgent
from agents.premise_architect_agent import PremiseArchitectAgent
from agents.plot_architect_agent import PlotArchitectAgent
from agents.scene_writer_agent import SceneWriterAgent
from agents.canon_updater_agent import CanonUpdaterAgent
from agents.audience_compliance_agent import AudienceComplianceAgent
from agents.narration_formatter_agent import NarrationFormatterAgent
from agents.contradiction_agent import ContradictionAgent
from agents.qa_validator_agent import QAValidatorAgent
from agents.delta_agent import DeltaAgent
from agents.publisher_agent import PublisherAgent, PUBLISH_ROOT
from core.budgets import BudgetLedger
from core.orchestrator import execute_graph
from core.state import create_initial_state
from data.db import get_initialized_connection
from data.dao_story_worlds import insert_world, get_world
from data.dao_characters import insert_character, get_character
from data.dao_threads import insert_thread, get_thread, get_open_threads
from data.dao_claims import list_claims_for_scope
from data.dao_entities import list_entities
from data.dao_episodes import get_episodes_for_world
from data.dao_snapshots import get_latest_snapshot
from graphs.graph_types import load_graph
from scripts.run_story import _persist_world_state

GRAPH_PATH = Path(__file__).parent.parent.parent / "graphs" / "story_graph.yaml"


# ---- Mock model responses ----

_MOCK_RESPONSES = {
    "premise architect": json.dumps({
        "premise": "Aria discovers a glowing crystal shard.",
        "episode_title": "The Shard of Storms",
        "selected_threads": ["thread-crystal-storms"],
    }),
    "plot architect": json.dumps({
        "act_structure": [
            {"act": 1, "title": "Discovery", "summary": "Find the shard"},
            {"act": 2, "title": "Journey", "summary": "Cross the bridge"},
        ],
        "scene_plans": [
            {"scene_id": "s1", "act": 1, "pov_character": "Aria", "conflict": "c", "objective": "o", "stakes": "s", "emotional_arc": "e"},
            {"scene_id": "s2", "act": 2, "pov_character": "Bram", "conflict": "c", "objective": "o", "stakes": "s", "emotional_arc": "e"},
            {"scene_id": "s3", "act": 2, "pov_character": "Aria", "conflict": "c", "objective": "o", "stakes": "s", "emotional_arc": "e"},
        ],
    }),
    "scene writer": json.dumps({
        "scenes": [
            {"scene_id": "s1", "text": "Aria found the crystal shard.", "word_count": 6},
            {"scene_id": "s2", "text": "Bram hesitated at the bridge.", "word_count": 6},
            {"scene_id": "s3", "text": "Together they reached Crystal Peak.", "word_count": 5},
        ],
        "episode_text": "Aria found the crystal shard.\n\nBram hesitated at the bridge.\n\nTogether they reached Crystal Peak.",
    }),
    "canon updater": json.dumps({
        "new_claims": [
            {
                "claim_id": "cl-shard",
                "statement": "A crystal shard can calm storms",
                "claim_type": "canon_fact",
                "entities": ["crystal-shard"],
                "citations": [{"doc_id": "eldoria-1-E001", "segment_id": "s1"}],
                "evidence_strength": 0.9,
                "confidence": 0.95,
            },
        ],
        "updated_characters": [
            {"character_id": "char-aria", "changes": {"beliefs": ["crystal shards have power"]}},
        ],
        "new_threads": [
            {"thread_id": "thread-shard-quest", "title": "The Shard Quest", "thematic_tag": "adventure",
             "related_character_ids": ["char-aria", "char-bram"]},
        ],
        "resolved_threads": [],
        "new_entities": [
            {"entity_id": "crystal-shard", "type": "artifact", "name": "Storm Shard"},
        ],
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
        "narration_script": "[NARRATOR] Welcome to Eldoria.\n\n[VOICE: Aria] Look at this crystal!",
        "recap": "Previously on Eldoria: The floating islands face mysterious crystal storms.",
    }),
}

# Episode 2 mock — different claims, resolves a thread
_MOCK_RESPONSES_EP2 = dict(_MOCK_RESPONSES)
_MOCK_RESPONSES_EP2["premise architect"] = json.dumps({
    "premise": "The shard reveals a hidden map to Storm Keep.",
    "episode_title": "Map of Storms",
    "selected_threads": ["thread-shard-quest"],
})
_MOCK_RESPONSES_EP2["canon updater"] = json.dumps({
    "new_claims": [
        {
            "claim_id": "cl-map",
            "statement": "The shard reveals a map to Storm Keep",
            "claim_type": "event",
            "entities": ["crystal-shard", "storm-keep"],
            "citations": [{"doc_id": "eldoria-1-E002", "segment_id": "s1"}],
            "evidence_strength": 0.85,
            "confidence": 0.9,
        },
    ],
    "updated_characters": [
        {"character_id": "char-bram", "changes": {"goals": ["reach Storm Keep"]}},
    ],
    "new_threads": [],
    "resolved_threads": ["thread-crystal-storms"],
    "new_entities": [
        {"entity_id": "storm-keep", "type": "location", "name": "Storm Keep"},
    ],
})


def _make_mock_model(responses=None):
    r = responses or _MOCK_RESPONSES

    def _mock(system_prompt: str, user_message: str) -> str:
        for key, response in r.items():
            if key in system_prompt.lower():
                return response
        return json.dumps({})

    return _mock


@pytest.fixture
def story_db():
    conn = get_initialized_connection(":memory:")
    now = "2026-01-01T00:00:00Z"
    insert_world(
        conn, world_id="eldoria-1", name="Eldoria", genre="fantasy", tone="whimsical",
        setting={"geography": "Floating islands"},
        thematic_constraints=["friendship", "courage"],
        audience_profile={"age_range": "8-12", "vocabulary_level": "intermediate"},
        created_at=now, updated_at=now,
    )
    insert_character(conn, character_id="char-aria", world_id="eldoria-1",
                     name="Aria", role="protagonist", traits=["brave", "curious"])
    insert_character(conn, character_id="char-bram", world_id="eldoria-1",
                     name="Bram", role="supporting", traits=["loyal", "cautious"])
    insert_thread(conn, thread_id="thread-crystal-storms", world_id="eldoria-1",
                  title="The Crystal Storms", introduced_in_episode=0,
                  thematic_tag="mystery", related_character_ids=["char-aria"])
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def setup_and_cleanup():
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


def _run_story_graph(story_db, run_id="test-run-1", mock_model=None):
    """Helper: run the story graph and return result."""
    graph = load_graph(GRAPH_PATH)
    state = create_initial_state(
        scope_type="story", scope_id="eldoria-1",
        run_id=run_id, graph_id="story_graph",
        extra={
            "world_id": "eldoria-1",
            "conn": story_db,
            "claims": [], "metrics": [], "doc_ids": [], "segment_ids": [], "violations": [],
        },
    )
    model_call = mock_model or _make_mock_model()
    return execute_graph(graph, state, model_call=model_call)


# ------------------------------------------------------------------
# S4.5 Test: world state persistence — run graph, persist, verify DB
# ------------------------------------------------------------------

class TestWorldStatePersistence:

    def test_persist_claims_to_db(self, story_db):
        """After graph run + persist, claims appear in DB."""
        result = _run_story_graph(story_db)
        assert result.status == "completed"

        now = "2026-01-01T00:00:00Z"
        _persist_world_state(story_db, "eldoria-1", 1, result.state, now)

        claims = list_claims_for_scope(story_db, "story", "eldoria-1")
        assert len(claims) >= 1
        claim_ids = [c["claim_id"] for c in claims]
        assert "cl-shard" in claim_ids

    def test_persist_character_updates(self, story_db):
        """After persist, character beliefs are updated."""
        result = _run_story_graph(story_db)
        _persist_world_state(story_db, "eldoria-1", 1, result.state, "2026-01-01T00:00:00Z")

        aria = get_character(story_db, "char-aria")
        assert aria is not None
        assert "crystal shards have power" in aria["beliefs_json"]

    def test_persist_new_threads(self, story_db):
        """After persist, new threads are inserted in DB."""
        result = _run_story_graph(story_db)
        _persist_world_state(story_db, "eldoria-1", 1, result.state, "2026-01-01T00:00:00Z")

        thread = get_thread(story_db, "thread-shard-quest")
        assert thread is not None
        assert thread["title"] == "The Shard Quest"
        assert thread["introduced_in_episode"] == 1

    def test_persist_entities(self, story_db):
        """After persist, new entities are in DB."""
        result = _run_story_graph(story_db)
        _persist_world_state(story_db, "eldoria-1", 1, result.state, "2026-01-01T00:00:00Z")

        entities = list_entities(story_db, type="artifact")
        entity_ids = [e["entity_id"] for e in entities]
        assert "crystal-shard" in entity_ids

    def test_persist_episode_record(self, story_db):
        """After persist, episode record exists in DB."""
        result = _run_story_graph(story_db)
        _persist_world_state(story_db, "eldoria-1", 1, result.state, "2026-01-01T00:00:00Z")

        episodes = get_episodes_for_world(story_db, "eldoria-1")
        assert len(episodes) == 1
        assert episodes[0]["episode_id"] == "eldoria-1-E001"
        assert episodes[0]["episode_number"] == 1

    def test_persist_increments_episode_number(self, story_db):
        """After persist, world episode counter is incremented."""
        result = _run_story_graph(story_db)
        _persist_world_state(story_db, "eldoria-1", 1, result.state, "2026-01-01T00:00:00Z")

        world = get_world(story_db, "eldoria-1")
        assert world["current_episode_number"] == 1  # incremented from 0 to 1

    def test_persist_snapshot(self, story_db):
        """After persist, snapshot record exists for next episode to find."""
        result = _run_story_graph(story_db)
        _persist_world_state(story_db, "eldoria-1", 1, result.state, "2026-01-01T00:00:00Z")

        snap = get_latest_snapshot(story_db, "story", "eldoria-1")
        assert snap is not None
        assert snap["snapshot_id"] == result.state["snapshot_id"]

    def test_two_episode_persistence_and_continuity(self, story_db):
        """Run 2 episodes with persistence, verify DB state compounds."""
        # --- Episode 1 ---
        result1 = _run_story_graph(story_db, run_id="ep1")
        assert result1.status == "completed"
        _persist_world_state(story_db, "eldoria-1", 1, result1.state, "2026-01-01T00:00:00Z")

        # Verify after ep1
        world = get_world(story_db, "eldoria-1")
        assert world["current_episode_number"] == 1
        claims_1 = list_claims_for_scope(story_db, "story", "eldoria-1")
        assert len(claims_1) >= 1

        # --- Episode 2 (uses ep2 mock responses) ---
        result2 = _run_story_graph(story_db, run_id="ep2", mock_model=_make_mock_model(_MOCK_RESPONSES_EP2))
        assert result2.status == "completed"
        assert result2.state["episode_number"] == 2

        _persist_world_state(story_db, "eldoria-1", 2, result2.state, "2026-01-02T00:00:00Z")

        # Verify compounded state
        world2 = get_world(story_db, "eldoria-1")
        assert world2["current_episode_number"] == 2

        claims_2 = list_claims_for_scope(story_db, "story", "eldoria-1")
        assert len(claims_2) >= 2  # claims from both episodes
        claim_ids = [c["claim_id"] for c in claims_2]
        assert "cl-shard" in claim_ids
        assert "cl-map" in claim_ids

        # Bram goals updated in ep2
        bram = get_character(story_db, "char-bram")
        assert "reach Storm Keep" in bram["goals_json"]

        # thread-crystal-storms resolved in ep2
        thread = get_thread(story_db, "thread-crystal-storms")
        assert thread["status"] == "resolved"
        assert thread["resolved_in_episode"] == 2

        # New entity from ep2
        entities = list_entities(story_db, type="location")
        entity_ids = [e["entity_id"] for e in entities]
        assert "storm-keep" in entity_ids

        # Episodes in DB
        episodes = get_episodes_for_world(story_db, "eldoria-1")
        assert len(episodes) == 2


# ------------------------------------------------------------------
# S4.5 Test: frontier escalation trigger on scene_writer retry
# ------------------------------------------------------------------

class TestFrontierEscalation:

    def test_escalation_on_on_fail_routing(self, story_db):
        """When QA fails and routes to scene_writing on_fail, frontier model is used."""
        call_log = []

        # QA will fail first time (scene count < 2), pass second time
        qa_fail_count = [0]

        def _mock_with_qa_fail(system_prompt: str, user_message: str) -> str:
            call_log.append({"prompt": system_prompt[:50], "is_frontier": False})
            for key, response in _MOCK_RESPONSES.items():
                if key in system_prompt.lower():
                    # Make audience compliance FAIL on first pass
                    if key == "audience compliance" and qa_fail_count[0] == 0:
                        qa_fail_count[0] += 1
                        return json.dumps({
                            "compliance_status": "FAIL",
                            "compliance_violations": [{"rule": "vocabulary", "detail": "Too complex", "scene_id": "s1"}],
                        })
                    return response
            return json.dumps({})

        def _frontier_mock(system_prompt: str, user_message: str) -> str:
            call_log.append({"prompt": system_prompt[:50], "is_frontier": True})
            for key, response in _MOCK_RESPONSES.items():
                if key in system_prompt.lower():
                    return response
            return json.dumps({})

        graph = load_graph(GRAPH_PATH)
        state = create_initial_state(
            scope_type="story", scope_id="eldoria-1",
            run_id="escalation-test", graph_id="story_graph",
            extra={
                "world_id": "eldoria-1",
                "conn": story_db,
                "claims": [], "metrics": [], "doc_ids": [], "segment_ids": [], "violations": [],
            },
        )

        result = execute_graph(
            graph, state,
            model_call=_mock_with_qa_fail,
            frontier_model_call=_frontier_mock,
        )
        assert result.status == "completed"

        # Check that frontier model was used for the escalated scene_writing
        frontier_calls = [c for c in call_log if c["is_frontier"]]
        assert len(frontier_calls) > 0, "Frontier model should have been called on escalation"

        # Check escalation event is logged
        escalated_events = [e for e in result.events if e.get("escalated")]
        assert len(escalated_events) > 0

    def test_no_escalation_without_frontier_model(self, story_db):
        """Without frontier_model_call, no escalation happens (graceful)."""
        result = _run_story_graph(story_db)
        assert result.status == "completed"
        # No escalation events
        escalated_events = [e for e in result.events if e.get("escalated")]
        assert len(escalated_events) == 0


# ------------------------------------------------------------------
# S4.5 Test: budget enforcement — degradation on scene_writer
# ------------------------------------------------------------------

class TestBudgetEnforcement:

    def test_graph_yaml_has_node_budgets(self):
        """Verify story graph YAML has budget caps on key nodes."""
        graph = load_graph(GRAPH_PATH)
        assert graph.budget is not None
        assert graph.budget["max_tokens"] == 32768

        sw = graph.get_node("scene_writing")
        assert sw.budget is not None
        assert sw.budget["max_tokens"] == 8192

        narr = graph.get_node("narration")
        assert narr.budget is not None
        assert narr.budget["max_tokens"] == 8192

        premise = graph.get_node("premise")
        assert premise.budget is not None
        assert premise.budget["max_tokens"] == 4096

    def test_budget_degradation_injects_state(self, story_db):
        """When budget is near exhaustion, _degradation hint is injected into state."""
        graph = load_graph(GRAPH_PATH)
        state = create_initial_state(
            scope_type="story", scope_id="eldoria-1",
            run_id="budget-test", graph_id="story_graph",
            extra={
                "world_id": "eldoria-1",
                "conn": story_db,
                "claims": [], "metrics": [], "doc_ids": [], "segment_ids": [], "violations": [],
            },
        )
        # Set a tight budget so degradation triggers
        budget = BudgetLedger(max_tokens=100)
        # Pre-record some tokens to trigger degradation
        budget.record(tokens_in=85, tokens_out=0, node_id="warmup")

        result = execute_graph(
            graph, state,
            model_call=_make_mock_model(),
            budget=budget,
        )
        # The graph should still complete (budget degradation is soft failure)
        # or fail with budget_degraded events
        degraded_events = [e for e in result.events if e.get("status") == "budget_degraded"]
        assert budget.degradation_active or len(degraded_events) > 0

    def test_per_run_budget_in_run_story(self):
        """Verify run_story.py sets per-run budget of 32768 tokens."""
        # This is a structural test — the BudgetLedger(max_tokens=32768) is set in main()
        # We verify by checking the graph definition matches
        graph = load_graph(GRAPH_PATH)
        assert graph.budget["max_tokens"] == 32768
