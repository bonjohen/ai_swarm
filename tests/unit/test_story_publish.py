"""Tests for story publishing (Phase S3): artifact structure, manifest, hashes, format."""

import hashlib
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
from data.dao_story_worlds import insert_world
from data.dao_characters import insert_character
from data.dao_threads import insert_thread
from graphs.graph_types import load_graph
from publish.renderer import (
    render_story_markdown,
    render_recap_markdown,
    render_world_state_json,
    render_episode_json,
)

GRAPH_PATH = Path(__file__).parent.parent.parent / "graphs" / "story_graph.yaml"


# ---- Shared mock model ----

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
            {"scene_id": "s1", "text": "Aria found the crystal shard glowing softly among the rocks.", "word_count": 10},
            {"scene_id": "s2", "text": "Bram hesitated at the bridge. 'Well, actually...' he began.", "word_count": 10},
            {"scene_id": "s3", "text": "Together they reached Crystal Peak as the storm calmed.", "word_count": 9},
        ],
        "episode_text": "Aria found the crystal shard glowing softly among the rocks.\n\nBram hesitated at the bridge. 'Well, actually...' he began.\n\nTogether they reached Crystal Peak as the storm calmed.",
    }),
    "canon updater": json.dumps({
        "new_claims": [
            {"claim_id": "cl-shard", "statement": "A crystal shard can calm storms",
             "claim_type": "canon_fact", "entities": ["crystal-shard"],
             "citations": [{"doc_id": "eldoria-1-E001", "segment_id": "s1"}],
             "evidence_strength": 0.9, "confidence": 0.95},
        ],
        "updated_characters": [],
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
        "narration_script": "[NARRATOR] Welcome to Eldoria.\n\n[VOICE: Aria] Look at this crystal!\n\n[VOICE: Bram] Well, actually...",
        "recap": "Previously on Eldoria: The floating islands face mysterious crystal storms. Young Aria seeks answers.",
    }),
}


def _mock_model(system_prompt: str, user_message: str) -> str:
    for key, response in _MOCK_RESPONSES.items():
        if key in system_prompt.lower():
            return response
    return json.dumps({})


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


def _run_story_graph(story_db, run_id="pub-test-1"):
    """Helper: run the story graph and return result + publish_dir."""
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
    result = execute_graph(graph, state, model_call=_mock_model)
    assert result.status == "completed"
    return result, Path(result.state["publish_dir"])


# ------------------------------------------------------------------
# S3.3 Golden test: artifact structure
# ------------------------------------------------------------------

def test_story_publish_artifact_structure(story_db):
    """Verify story publish produces all expected files."""
    result, publish_dir = _run_story_graph(story_db)

    expected_files = [
        "manifest.json",
        "artifacts.json",
        "report.md",
        "episode.md",
        "episode.json",
        "narration_script.txt",
        "recap.md",
        "world_state.json",
    ]
    for fname in expected_files:
        assert (publish_dir / fname).exists(), f"Missing: {fname}"


# ------------------------------------------------------------------
# Manifest.json schema validation
# ------------------------------------------------------------------

def test_story_manifest_schema(story_db):
    """Verify manifest.json has required fields for story publishes."""
    _, publish_dir = _run_story_graph(story_db)
    manifest = json.loads((publish_dir / "manifest.json").read_bytes())

    assert manifest["scope_type"] == "story"
    assert manifest["scope_id"] == "eldoria-1"
    assert manifest["version"] == "E001"
    assert manifest["snapshot_id"]
    assert manifest["delta_id"]
    assert manifest["generated_at"]


# ------------------------------------------------------------------
# Artifacts.json integrity: paths exist, hashes match
# ------------------------------------------------------------------

def test_story_artifacts_integrity(story_db):
    """Verify every artifact listed in artifacts.json exists and hash matches."""
    _, publish_dir = _run_story_graph(story_db)
    artifacts = json.loads((publish_dir / "artifacts.json").read_bytes())

    assert len(artifacts) > 0
    for art in artifacts:
        assert "name" in art
        assert "path" in art
        assert "hash" in art

        art_path = Path(art["path"])
        assert art_path.exists(), f"Artifact path missing: {art['path']}"

        content = art_path.read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        assert actual_hash == art["hash"], (
            f"Hash mismatch for {art['name']}: expected {art['hash']}, got {actual_hash}"
        )


# ------------------------------------------------------------------
# Episode.md readable format
# ------------------------------------------------------------------

def test_episode_md_format(story_db):
    """Verify episode.md has expected structure: title, scenes, word count."""
    _, publish_dir = _run_story_graph(story_db)
    content = (publish_dir / "episode.md").read_text(encoding="utf-8")

    # Title
    assert "# Episode:" in content
    assert "The Shard of Storms" in content

    # Scenes
    assert "## Scene: s1" in content
    assert "## Scene: s2" in content
    assert "## Scene: s3" in content

    # Scene text
    assert "crystal shard" in content

    # Word count footer
    assert "Total word count:" in content


# ------------------------------------------------------------------
# episode.json structure
# ------------------------------------------------------------------

def test_episode_json_structure(story_db):
    """Verify episode.json has structured episode data."""
    _, publish_dir = _run_story_graph(story_db)
    ep = json.loads((publish_dir / "episode.json").read_bytes())

    assert ep["episode_title"] == "The Shard of Storms"
    assert ep["episode_number"] == 1
    assert ep["world_id"] == "eldoria-1"
    assert ep["premise"]
    assert len(ep["act_structure"]) >= 2
    assert len(ep["scenes"]) == 3
    assert ep["episode_text"]
    assert ep["word_count"] > 0
    assert ep["compliance_status"] == "PASS"


# ------------------------------------------------------------------
# narration_script.txt
# ------------------------------------------------------------------

def test_narration_script_txt(story_db):
    """Verify narration_script.txt is plain text with narration markers."""
    _, publish_dir = _run_story_graph(story_db)
    content = (publish_dir / "narration_script.txt").read_text(encoding="utf-8")

    assert "[NARRATOR]" in content
    assert "[VOICE:" in content


# ------------------------------------------------------------------
# recap.md
# ------------------------------------------------------------------

def test_recap_md(story_db):
    """Verify recap.md has 'Previously On' content."""
    _, publish_dir = _run_story_graph(story_db)
    content = (publish_dir / "recap.md").read_text(encoding="utf-8")

    assert "Previously On" in content
    assert "Eldoria" in content


# ------------------------------------------------------------------
# world_state.json
# ------------------------------------------------------------------

def test_world_state_json(story_db):
    """Verify world_state.json has characters, threads, and claim summary."""
    _, publish_dir = _run_story_graph(story_db)
    ws = json.loads((publish_dir / "world_state.json").read_bytes())

    assert ws["world_id"] == "eldoria-1"
    assert ws["name"] == "Eldoria"
    assert ws["genre"] == "fantasy"
    assert ws["episode_number"] == 1
    assert len(ws["characters"]) == 2
    assert ws["characters"][0]["name"] in ("Aria", "Bram")
    assert len(ws["active_threads"]) >= 1
    assert len(ws["claim_summary"]) >= 1


# ------------------------------------------------------------------
# Multi-episode publish: E001 and E002 in separate directories
# ------------------------------------------------------------------

def test_multi_episode_separate_directories(story_db):
    """Verify E001 and E002 publish to separate version directories."""
    # Run episode 1
    _, pub1 = _run_story_graph(story_db, run_id="pub-ep1")
    assert "E001" in str(pub1)

    # Simulate state update for episode 2
    from data.dao_story_worlds import increment_episode_number
    from data.dao_snapshots import insert_snapshot

    increment_episode_number(story_db, "eldoria-1")
    # Insert a snapshot so episode 2 can find it
    insert_snapshot(
        story_db, snapshot_id="snap-ep1", scope_type="story", scope_id="eldoria-1",
        created_at="2026-01-01T00:00:00Z", hash="abc123",
    )

    # Run episode 2
    _, pub2 = _run_story_graph(story_db, run_id="pub-ep2")
    assert "E002" in str(pub2)

    # Verify both exist and are separate directories
    assert pub1.exists()
    assert pub2.exists()
    assert pub1 != pub2

    # Both have manifests
    m1 = json.loads((pub1 / "manifest.json").read_bytes())
    m2 = json.loads((pub2 / "manifest.json").read_bytes())
    assert m1["version"] == "E001"
    assert m2["version"] == "E002"


# ------------------------------------------------------------------
# Unit tests for renderer helpers
# ------------------------------------------------------------------

class TestRendererHelpers:

    def test_render_recap_markdown(self):
        state = {"episode_title": "The Quest", "recap": "Last time, things happened."}
        md = render_recap_markdown(state)
        assert "Previously On: The Quest" in md
        assert "Last time, things happened." in md

    def test_render_recap_markdown_empty(self):
        state = {"episode_title": "The Quest", "recap": ""}
        md = render_recap_markdown(state)
        assert "No previous episode recap available" in md

    def test_render_world_state_json(self):
        state = {
            "scope_id": "w1",
            "world_state": {"name": "Eldoria", "genre": "fantasy", "tone": "whimsical"},
            "episode_number": 3,
            "characters": [
                {"character_id": "c1", "name": "Aria", "role": "protagonist",
                 "arc_stage": "rising", "alive": True,
                 "traits_json": ["brave"], "goals_json": ["quest"],
                 "fears_json": ["dark"], "beliefs_json": ["magic"]},
            ],
            "active_threads": [
                {"thread_id": "t1", "title": "Mystery", "status": "open",
                 "thematic_tag": "mystery", "introduced_in_episode": 1},
            ],
            "new_claims": [
                {"claim_id": "cl1", "claim_type": "event", "statement": "A thing happened"},
            ],
        }
        ws = render_world_state_json(state)
        assert ws["world_id"] == "w1"
        assert ws["episode_number"] == 3
        assert len(ws["characters"]) == 1
        assert ws["characters"][0]["traits"] == ["brave"]
        assert len(ws["active_threads"]) == 1
        assert len(ws["claim_summary"]) == 1

    def test_render_episode_json(self):
        state = {
            "episode_title": "The Quest",
            "episode_number": 2,
            "scope_id": "w1",
            "premise": "A quest begins",
            "act_structure": [{"act": 1}],
            "scenes": [{"scene_id": "s1", "text": "text", "word_count": 5}],
            "episode_text": "text goes here",
            "selected_threads": ["t1"],
            "compliance_status": "PASS",
        }
        ep = render_episode_json(state)
        assert ep["episode_title"] == "The Quest"
        assert ep["episode_number"] == 2
        assert ep["word_count"] == 3  # "text goes here"
        assert ep["compliance_status"] == "PASS"
