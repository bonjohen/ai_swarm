"""Integration test: story graph end-to-end with mock model responses."""

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
from core.orchestrator import execute_graph
from core.state import create_initial_state
from data.db import get_initialized_connection
from data.dao_story_worlds import insert_world, get_world
from data.dao_characters import insert_character, get_character
from data.dao_threads import insert_thread, get_thread
from data.dao_episodes import insert_episode, get_episodes_for_world
from graphs.graph_types import load_graph

GRAPH_PATH = Path(__file__).parent.parent.parent / "graphs" / "story_graph.yaml"


# ---- Mock model responses ----

_MOCK_RESPONSES = {
    "premise architect": json.dumps({
        "premise": "Aria discovers a glowing crystal shard that pulses in rhythm with the approaching storm. She must convince the cautious Bram to help her investigate before the bridge to Crystal Peak collapses.",
        "episode_title": "The Shard of Storms",
        "selected_threads": ["thread-crystal-storms"],
    }),
    "plot architect": json.dumps({
        "act_structure": [
            {"act": 1, "title": "Discovery", "summary": "Aria finds the crystal shard"},
            {"act": 2, "title": "Journey", "summary": "Aria and Bram cross the bridge"},
            {"act": 3, "title": "Revelation", "summary": "The truth about the storms"},
        ],
        "scene_plans": [
            {"scene_id": "s1", "act": 1, "pov_character": "Aria", "conflict": "Strange crystal appears", "objective": "Discover the shard", "stakes": "Miss the clue", "emotional_arc": "curiosity to wonder"},
            {"scene_id": "s2", "act": 2, "pov_character": "Bram", "conflict": "Bridge is unstable", "objective": "Cross safely", "stakes": "Fall into clouds", "emotional_arc": "fear to determination"},
            {"scene_id": "s3", "act": 3, "pov_character": "Aria", "conflict": "Storm intensifies", "objective": "Reach Crystal Peak", "stakes": "Islands could break apart", "emotional_arc": "tension to triumph"},
        ],
    }),
    "scene writer": json.dumps({
        "scenes": [
            {"scene_id": "s1", "text": "Aria spotted the crystal shard nestled between two mossy rocks. It pulsed with a soft blue light, humming gently. She knelt down, her eyes wide with wonder.", "word_count": 30},
            {"scene_id": "s2", "text": "Bram gripped the rope bridge railing, his knuckles white. 'Well, actually,' he said, 'the structural integrity of this bridge is questionable.' Aria grinned and stepped forward.", "word_count": 28},
            {"scene_id": "s3", "text": "The storm swirled above Crystal Peak as Aria held the shard high. Light exploded outward, calming the winds. Bram stared in awe. 'I did not see that coming,' he admitted.", "word_count": 32},
        ],
        "episode_text": "Aria spotted the crystal shard nestled between two mossy rocks. It pulsed with a soft blue light, humming gently. She knelt down, her eyes wide with wonder.\n\nBram gripped the rope bridge railing, his knuckles white. 'Well, actually,' he said, 'the structural integrity of this bridge is questionable.' Aria grinned and stepped forward.\n\nThe storm swirled above Crystal Peak as Aria held the shard high. Light exploded outward, calming the winds. Bram stared in awe. 'I did not see that coming,' he admitted.",
    }),
    "canon updater": json.dumps({
        "new_claims": [
            {
                "claim_id": "cl-storm-shard",
                "statement": "A crystal shard was found that can calm the crystal storms",
                "claim_type": "canon_fact",
                "entities": ["crystal-shard"],
                "citations": [{"doc_id": "eldoria-1-E001", "segment_id": "s1"}],
                "evidence_strength": 0.9,
                "confidence": 0.95,
            },
            {
                "claim_id": "cl-crystal-peak",
                "statement": "Crystal Peak is the source of the storms",
                "claim_type": "event",
                "entities": ["crystal-peak"],
                "citations": [{"doc_id": "eldoria-1-E001", "segment_id": "s3"}],
                "evidence_strength": 0.85,
                "confidence": 0.9,
            },
        ],
        "updated_characters": [
            {"character_id": "char-aria", "changes": {"beliefs": ["crystal shards have power"]}},
        ],
        "new_threads": [],
        "resolved_threads": [],
        "new_entities": [
            {"entity_id": "crystal-shard", "type": "artifact", "name": "Storm Shard"},
            {"entity_id": "crystal-peak", "type": "location", "name": "Crystal Peak"},
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
        "narration_script": "[NARRATOR] [pause] Welcome back to Eldoria. [long pause]\n\n[VOICE: Aria] [excited] Look at this, Bram! A crystal shard!\n\n[VOICE: Bram] [nervous] Well, actually, the structural integrity of this bridge is questionable.\n\n[NARRATOR] And so their adventure began...",
        "recap": "Previously on Eldoria: The floating islands have been battered by mysterious crystal storms. Young Aria, ever curious, has been searching for answers. Today, she finds the first real clue.",
    }),
}


def _mock_model(system_prompt: str, user_message: str) -> str:
    prompt_lower = system_prompt.lower()
    for key, response in _MOCK_RESPONSES.items():
        if key in prompt_lower:
            return response
    return json.dumps({})


@pytest.fixture
def story_db():
    """Create an in-memory DB with world, characters, and a thread."""
    conn = get_initialized_connection(":memory:")
    now = "2026-01-01T00:00:00Z"
    insert_world(
        conn,
        world_id="eldoria-1",
        name="Eldoria",
        genre="fantasy",
        tone="whimsical",
        setting={"geography": "Floating islands"},
        thematic_constraints=["friendship", "courage"],
        audience_profile={"age_range": "8-12", "vocabulary_level": "intermediate"},
        created_at=now,
        updated_at=now,
    )
    insert_character(
        conn, character_id="char-aria", world_id="eldoria-1",
        name="Aria", role="protagonist", traits=["brave", "curious"],
    )
    insert_character(
        conn, character_id="char-bram", world_id="eldoria-1",
        name="Bram", role="supporting", traits=["loyal", "cautious"],
    )
    insert_thread(
        conn, thread_id="thread-crystal-storms", world_id="eldoria-1",
        title="The Crystal Storms", introduced_in_episode=0,
        thematic_tag="mystery", related_character_ids=["char-aria"],
    )
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


def test_story_graph_end_to_end(story_db):
    graph = load_graph(GRAPH_PATH)

    state = create_initial_state(
        scope_type="story", scope_id="eldoria-1",
        run_id="story-integration-1", graph_id="story_graph",
        extra={
            "world_id": "eldoria-1",
            "conn": story_db,
            "claims": [],
            "metrics": [],
            "doc_ids": [],
            "segment_ids": [],
            "violations": [],
        },
    )

    result = execute_graph(graph, state, model_call=_mock_model)

    assert result.status == "completed"
    assert len(result.events) == 11  # all 11 nodes

    # Verify key state
    assert result.state["world_id"] == "eldoria-1"
    assert result.state["episode_number"] == 1
    assert result.state["premise"]
    assert result.state["episode_title"] == "The Shard of Storms"
    assert len(result.state["scenes"]) == 3
    assert result.state["episode_text"]
    assert len(result.state["new_claims"]) == 2
    assert result.state["compliance_status"] == "PASS"
    assert result.state["gate_status"] == "PASS"
    assert result.state["snapshot_id"]
    assert result.state["narration_script"]
    assert result.state["recap"]

    # Verify publish output
    assert result.state["publish_dir"]
    publish_dir = Path(result.state["publish_dir"])
    assert (publish_dir / "manifest.json").exists()
    assert (publish_dir / "artifacts.json").exists()

    # Verify episode versioning — should be E001
    manifest = json.loads((publish_dir / "manifest.json").read_bytes())
    assert manifest["version"] == "E001"
    assert "story" in str(publish_dir)


def test_story_graph_multi_episode_continuity(story_db):
    """Run 2 consecutive episodes and verify continuity."""
    graph = load_graph(GRAPH_PATH)

    # --- Episode 1 ---
    state1 = create_initial_state(
        scope_type="story", scope_id="eldoria-1",
        run_id="story-ep1", graph_id="story_graph",
        extra={
            "world_id": "eldoria-1",
            "conn": story_db,
            "claims": [],
            "metrics": [],
            "doc_ids": [],
            "segment_ids": [],
            "violations": [],
        },
    )

    result1 = execute_graph(graph, state1, model_call=_mock_model)
    assert result1.status == "completed"

    # Simulate post-run: insert episode, increment counter, insert snapshot
    from data.dao_story_worlds import increment_episode_number
    from data.dao_snapshots import insert_snapshot

    insert_episode(
        story_db,
        episode_id="eldoria-1-E001",
        world_id="eldoria-1",
        episode_number=1,
        title=result1.state.get("episode_title", ""),
        scene_count=len(result1.state.get("scenes", [])),
        word_count=len(result1.state.get("episode_text", "").split()),
        snapshot_id=result1.state.get("snapshot_id"),
        run_id="story-ep1",
        status="final",
        created_at="2026-01-01T00:00:00Z",
    )
    increment_episode_number(story_db, "eldoria-1")
    insert_snapshot(
        story_db,
        snapshot_id=result1.state["snapshot_id"],
        scope_type="story",
        scope_id="eldoria-1",
        created_at="2026-01-01T00:00:00Z",
        hash=result1.state.get("snapshot_hash", "abc"),
        included_claim_ids=result1.state.get("included_claim_ids", []),
    )

    # --- Episode 2 ---
    state2 = create_initial_state(
        scope_type="story", scope_id="eldoria-1",
        run_id="story-ep2", graph_id="story_graph",
        extra={
            "world_id": "eldoria-1",
            "conn": story_db,
            "claims": [],
            "metrics": [],
            "doc_ids": [],
            "segment_ids": [],
            "violations": [],
        },
    )

    result2 = execute_graph(graph, state2, model_call=_mock_model)
    assert result2.status == "completed"

    # Verify second run loaded state from first run
    assert result2.state["episode_number"] == 2
    assert result2.state["previous_snapshot"] is not None
    assert result2.state["previous_snapshot"]["snapshot_id"] == result1.state["snapshot_id"]

    # Verify delta shows changes
    delta = result2.state.get("delta_json", {})
    assert isinstance(delta, dict)

    # Verify episode 2 publish is E002
    publish_dir2 = Path(result2.state["publish_dir"])
    manifest2 = json.loads((publish_dir2 / "manifest.json").read_bytes())
    assert manifest2["version"] == "E002"

    # Verify episodes in DB
    episodes = get_episodes_for_world(story_db, "eldoria-1")
    assert len(episodes) == 1  # only ep1 was inserted to DB; ep2 wasn't (no post-run in test)
