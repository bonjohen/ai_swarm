"""Tests for story-domain agents — parse/validate with sample inputs (Phase S1)."""

import json

import pytest

from data.db import get_initialized_connection
from data.dao_story_worlds import insert_world
from data.dao_characters import insert_character
from data.dao_threads import insert_thread
from data.dao_claims import insert_claim
from data.dao_snapshots import insert_snapshot

from agents.story_memory_loader_agent import StoryMemoryLoaderAgent
from agents.premise_architect_agent import PremiseArchitectAgent
from agents.plot_architect_agent import PlotArchitectAgent
from agents.scene_writer_agent import SceneWriterAgent
from agents.canon_updater_agent import CanonUpdaterAgent
from agents.audience_compliance_agent import AudienceComplianceAgent
from agents.narration_formatter_agent import NarrationFormatterAgent


# ------------------------------------------------------------------
# StoryMemoryLoaderAgent
# ------------------------------------------------------------------

class TestStoryMemoryLoader:

    @pytest.fixture
    def populated_db(self):
        conn = get_initialized_connection(":memory:")
        insert_world(
            conn,
            world_id="w1",
            name="Eldoria",
            genre="fantasy",
            tone="whimsical",
            audience_profile={"age_range": "8-12", "vocabulary_level": "intermediate"},
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        insert_character(
            conn,
            character_id="c1",
            world_id="w1",
            name="Aria",
            role="protagonist",
            traits=["brave"],
        )
        insert_character(
            conn,
            character_id="c2",
            world_id="w1",
            name="Bram",
            role="supporting",
            traits=["loyal"],
        )
        insert_thread(
            conn,
            thread_id="t1",
            world_id="w1",
            title="The Missing Gem",
            introduced_in_episode=1,
        )
        insert_claim(
            conn,
            claim_id="cl1",
            scope_type="story",
            scope_id="w1",
            statement="The gem is hidden in the cave",
            claim_type="canon_fact",
            first_seen_at="2026-01-01T00:00:00Z",
        )
        insert_snapshot(
            conn,
            snapshot_id="snap1",
            scope_type="story",
            scope_id="w1",
            created_at="2026-01-01T00:00:00Z",
            hash="abc123",
            included_claim_ids=["cl1"],
        )
        yield conn
        conn.close()

    def test_loads_state_from_db(self, populated_db):
        agent = StoryMemoryLoaderAgent()
        state = {"conn": populated_db, "world_id": "w1"}
        result = agent.run(state)
        assert result["world_id"] == "w1"
        assert result["world_state"]["name"] == "Eldoria"
        assert len(result["characters"]) == 2
        assert len(result["active_threads"]) == 1
        assert result["previous_snapshot"]["snapshot_id"] == "snap1"
        assert len(result["existing_claims"]) == 1
        assert result["episode_number"] == 1  # 0 + 1
        assert result["audience_profile"]["age_range"] == "8-12"

    def test_correct_state_keys(self, populated_db):
        agent = StoryMemoryLoaderAgent()
        state = {"conn": populated_db, "world_id": "w1"}
        result = agent.run(state)
        expected_keys = {
            "world_state", "characters", "active_threads",
            "previous_snapshot", "existing_claims", "episode_number",
            "audience_profile", "world_id",
        }
        assert set(result.keys()) == expected_keys

    def test_missing_world_raises(self, populated_db):
        agent = StoryMemoryLoaderAgent()
        state = {"conn": populated_db, "world_id": "nonexistent"}
        with pytest.raises(ValueError, match="World not found"):
            agent.run(state)

    def test_empty_world_no_snapshot(self):
        conn = get_initialized_connection(":memory:")
        insert_world(
            conn,
            world_id="w2",
            name="Empty",
            genre="scifi",
            tone="dark",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        agent = StoryMemoryLoaderAgent()
        result = agent.run({"conn": conn, "world_id": "w2"})
        assert result["characters"] == []
        assert result["active_threads"] == []
        assert result["previous_snapshot"] is None
        assert result["existing_claims"] == []
        assert result["episode_number"] == 1
        conn.close()


# ------------------------------------------------------------------
# PremiseArchitectAgent
# ------------------------------------------------------------------

class TestPremiseArchitect:

    def setup_method(self):
        self.agent = PremiseArchitectAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "premise": "Aria discovers a hidden map leading to the lost gem.",
            "episode_title": "The Hidden Map",
            "selected_threads": ["t1"],
        })
        result = self.agent.parse(resp)
        assert result["premise"] == "Aria discovers a hidden map leading to the lost gem."
        assert result["episode_title"] == "The Hidden Map"
        assert result["selected_threads"] == ["t1"]

    def test_validate_valid(self):
        self.agent.validate({
            "premise": "A quest begins.",
            "episode_title": "The Quest",
            "selected_threads": ["t1"],
        })

    def test_validate_empty_premise(self):
        with pytest.raises(ValueError, match="premise must be non-empty"):
            self.agent.validate({
                "premise": "",
                "episode_title": "Title",
                "selected_threads": [],
            })

    def test_validate_empty_title(self):
        with pytest.raises(ValueError, match="episode_title must be non-empty"):
            self.agent.validate({
                "premise": "Some premise",
                "episode_title": "",
                "selected_threads": [],
            })

    def test_validate_threads_not_list(self):
        with pytest.raises(ValueError, match="selected_threads must be a list"):
            self.agent.validate({
                "premise": "Some premise",
                "episode_title": "Title",
                "selected_threads": "t1",
            })

    def test_validate_no_threads_ok(self):
        """Empty list is OK — means new thread will be created."""
        self.agent.validate({
            "premise": "A new adventure.",
            "episode_title": "New Thread",
            "selected_threads": [],
        })


# ------------------------------------------------------------------
# PlotArchitectAgent
# ------------------------------------------------------------------

class TestPlotArchitect:

    def setup_method(self):
        self.agent = PlotArchitectAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "act_structure": [
                {"act": 1, "title": "Setup", "summary": "Intro"},
                {"act": 2, "title": "Climax", "summary": "Conflict"},
            ],
            "scene_plans": [
                {"scene_id": "s1", "act": 1, "pov_character": "Aria", "conflict": "c", "objective": "o", "stakes": "s", "emotional_arc": "e"},
                {"scene_id": "s2", "act": 2, "pov_character": "Bram", "conflict": "c", "objective": "o", "stakes": "s", "emotional_arc": "e"},
            ],
        })
        result = self.agent.parse(resp)
        assert len(result["act_structure"]) == 2
        assert len(result["scene_plans"]) == 2

    def test_validate_valid(self):
        self.agent.validate({
            "act_structure": [{"act": 1, "title": "A1"}, {"act": 2, "title": "A2"}],
            "scene_plans": [
                {"scene_id": "s1", "act": 1, "pov_character": "Aria"},
                {"scene_id": "s2", "act": 2, "pov_character": "Bram"},
            ],
        })

    def test_validate_empty_acts(self):
        with pytest.raises(ValueError, match="act_structure must be a non-empty list"):
            self.agent.validate({
                "act_structure": [],
                "scene_plans": [{"scene_id": "s1", "act": 1, "pov_character": "X"}],
            })

    def test_validate_too_few_scenes(self):
        with pytest.raises(ValueError, match="at least 2 scenes"):
            self.agent.validate({
                "act_structure": [{"act": 1}],
                "scene_plans": [{"scene_id": "s1", "act": 1, "pov_character": "X"}],
            })

    def test_validate_act_without_scene(self):
        with pytest.raises(ValueError, match="Act 2 has no scenes"):
            self.agent.validate({
                "act_structure": [{"act": 1}, {"act": 2}],
                "scene_plans": [
                    {"scene_id": "s1", "act": 1, "pov_character": "Aria"},
                    {"scene_id": "s2", "act": 1, "pov_character": "Bram"},
                ],
            })

    def test_validate_missing_scene_id(self):
        with pytest.raises(ValueError, match="scene_id"):
            self.agent.validate({
                "act_structure": [{"act": 1}],
                "scene_plans": [
                    {"act": 1, "pov_character": "X"},
                    {"scene_id": "s2", "act": 1, "pov_character": "Y"},
                ],
            })

    def test_validate_missing_pov_character(self):
        with pytest.raises(ValueError, match="pov_character"):
            self.agent.validate({
                "act_structure": [{"act": 1}],
                "scene_plans": [
                    {"scene_id": "s1", "act": 1},
                    {"scene_id": "s2", "act": 1, "pov_character": "Y"},
                ],
            })

    def test_validate_with_characters_valid(self):
        chars = [{"name": "Aria"}, {"name": "Bram"}]
        self.agent.validate_with_characters(
            {
                "act_structure": [{"act": 1}],
                "scene_plans": [
                    {"scene_id": "s1", "act": 1, "pov_character": "Aria"},
                    {"scene_id": "s2", "act": 1, "pov_character": "Bram"},
                ],
            },
            chars,
        )

    def test_validate_with_characters_unknown_pov(self):
        chars = [{"name": "Aria"}]
        with pytest.raises(ValueError, match="not found in character list"):
            self.agent.validate_with_characters(
                {
                    "act_structure": [{"act": 1}],
                    "scene_plans": [
                        {"scene_id": "s1", "act": 1, "pov_character": "Aria"},
                        {"scene_id": "s2", "act": 1, "pov_character": "Unknown"},
                    ],
                },
                chars,
            )


# ------------------------------------------------------------------
# SceneWriterAgent
# ------------------------------------------------------------------

class TestSceneWriter:

    def setup_method(self):
        self.agent = SceneWriterAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "scenes": [
                {"scene_id": "s1", "text": "Once upon a time...", "word_count": 150},
                {"scene_id": "s2", "text": "And then...", "word_count": 200},
            ],
            "episode_text": "Once upon a time... And then...",
        })
        result = self.agent.parse(resp)
        assert len(result["scenes"]) == 2
        assert result["episode_text"] == "Once upon a time... And then..."

    def test_validate_valid(self):
        self.agent.validate({
            "scenes": [
                {"scene_id": "s1", "text": "Some text", "word_count": 100},
            ],
            "episode_text": "Some text",
        })

    def test_validate_empty_scenes(self):
        with pytest.raises(ValueError, match="non-empty list"):
            self.agent.validate({"scenes": [], "episode_text": "text"})

    def test_validate_missing_text(self):
        with pytest.raises(ValueError, match="has no text"):
            self.agent.validate({
                "scenes": [{"scene_id": "s1", "text": "", "word_count": 0}],
                "episode_text": "text",
            })

    def test_validate_bad_word_count(self):
        with pytest.raises(ValueError, match="invalid word_count"):
            self.agent.validate({
                "scenes": [{"scene_id": "s1", "text": "words", "word_count": 0}],
                "episode_text": "words",
            })

    def test_validate_empty_episode_text(self):
        with pytest.raises(ValueError, match="episode_text must be non-empty"):
            self.agent.validate({
                "scenes": [{"scene_id": "s1", "text": "words", "word_count": 5}],
                "episode_text": "",
            })

    def test_validate_scene_ids_all_present(self):
        plans = [{"scene_id": "s1"}, {"scene_id": "s2"}]
        self.agent.validate_scene_ids(
            {
                "scenes": [
                    {"scene_id": "s1", "text": "A", "word_count": 1},
                    {"scene_id": "s2", "text": "B", "word_count": 1},
                ],
                "episode_text": "A B",
            },
            plans,
        )

    def test_validate_scene_ids_missing(self):
        plans = [{"scene_id": "s1"}, {"scene_id": "s2"}, {"scene_id": "s3"}]
        with pytest.raises(ValueError, match="Missing scenes from plan"):
            self.agent.validate_scene_ids(
                {
                    "scenes": [
                        {"scene_id": "s1", "text": "A", "word_count": 1},
                    ],
                    "episode_text": "A",
                },
                plans,
            )


# ------------------------------------------------------------------
# CanonUpdaterAgent
# ------------------------------------------------------------------

class TestCanonUpdater:

    def setup_method(self):
        self.agent = CanonUpdaterAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "new_claims": [
                {
                    "claim_id": "cl-new-1",
                    "statement": "The cave contains a dragon",
                    "claim_type": "canon_fact",
                    "entities": ["dragon"],
                    "citations": [{"doc_id": "ep1", "segment_id": "s1"}],
                    "evidence_strength": 0.9,
                    "confidence": 0.95,
                }
            ],
            "updated_characters": [{"character_id": "c1", "changes": {"beliefs": ["dragons exist"]}}],
            "new_threads": [{"title": "Dragon Threat", "thematic_tag": "danger", "related_character_ids": ["c1"]}],
            "resolved_threads": ["t1"],
            "new_entities": [{"entity_id": "dragon-1", "type": "creature", "name": "Fyrax"}],
        })
        result = self.agent.parse(resp)
        assert len(result["new_claims"]) == 1
        assert len(result["updated_characters"]) == 1
        assert len(result["new_threads"]) == 1
        assert result["resolved_threads"] == ["t1"]
        assert len(result["new_entities"]) == 1

    def test_validate_valid(self):
        self.agent.validate({
            "new_claims": [
                {
                    "claim_id": "cl1",
                    "statement": "Fact",
                    "claim_type": "canon_fact",
                    "citations": [{"doc_id": "ep1", "segment_id": "s1"}],
                }
            ],
            "updated_characters": [],
            "new_threads": [],
            "resolved_threads": [],
            "new_entities": [],
        })

    def test_validate_invalid_claim_type(self):
        with pytest.raises(ValueError, match="invalid claim_type"):
            self.agent.validate({
                "new_claims": [
                    {
                        "claim_id": "cl1",
                        "statement": "Fact",
                        "claim_type": "bogus_type",
                        "citations": [{"doc_id": "ep1", "segment_id": "s1"}],
                    }
                ],
                "updated_characters": [],
                "new_threads": [],
                "resolved_threads": [],
                "new_entities": [],
            })

    def test_validate_missing_citations(self):
        with pytest.raises(ValueError, match="no citations"):
            self.agent.validate({
                "new_claims": [
                    {
                        "claim_id": "cl1",
                        "statement": "Fact",
                        "claim_type": "event",
                        "citations": [],
                    }
                ],
                "updated_characters": [],
                "new_threads": [],
                "resolved_threads": [],
                "new_entities": [],
            })

    def test_validate_citation_missing_doc_id(self):
        with pytest.raises(ValueError, match="missing doc_id or segment_id"):
            self.agent.validate({
                "new_claims": [
                    {
                        "claim_id": "cl1",
                        "statement": "Fact",
                        "claim_type": "event",
                        "citations": [{"doc_id": "", "segment_id": "s1"}],
                    }
                ],
                "updated_characters": [],
                "new_threads": [],
                "resolved_threads": [],
                "new_entities": [],
            })

    def test_validate_all_claim_types(self):
        for ct in ("canon_fact", "world_rule", "character_trait", "event"):
            self.agent.validate({
                "new_claims": [
                    {
                        "claim_id": f"cl-{ct}",
                        "statement": "Fact",
                        "claim_type": ct,
                        "citations": [{"doc_id": "ep1", "segment_id": "s1"}],
                    }
                ],
                "updated_characters": [],
                "new_threads": [],
                "resolved_threads": [],
                "new_entities": [],
            })

    def test_validate_missing_statement(self):
        with pytest.raises(ValueError, match="no statement"):
            self.agent.validate({
                "new_claims": [
                    {
                        "claim_id": "cl1",
                        "statement": "",
                        "claim_type": "event",
                        "citations": [{"doc_id": "ep1", "segment_id": "s1"}],
                    }
                ],
                "updated_characters": [],
                "new_threads": [],
                "resolved_threads": [],
                "new_entities": [],
            })


# ------------------------------------------------------------------
# AudienceComplianceAgent
# ------------------------------------------------------------------

class TestAudienceCompliance:

    def setup_method(self):
        self.agent = AudienceComplianceAgent()

    def test_parse_pass(self):
        resp = json.dumps({
            "compliance_status": "PASS",
            "compliance_violations": [],
        })
        result = self.agent.parse(resp)
        assert result["compliance_status"] == "PASS"
        assert result["compliance_violations"] == []

    def test_parse_fail(self):
        resp = json.dumps({
            "compliance_status": "FAIL",
            "compliance_violations": [
                {"rule": "vocabulary", "detail": "Too complex", "scene_id": "s1"}
            ],
        })
        result = self.agent.parse(resp)
        assert result["compliance_status"] == "FAIL"
        assert len(result["compliance_violations"]) == 1

    def test_validate_pass(self):
        self.agent.validate({
            "compliance_status": "PASS",
            "compliance_violations": [],
        })

    def test_validate_fail_with_violations(self):
        self.agent.validate({
            "compliance_status": "FAIL",
            "compliance_violations": [
                {"rule": "vocabulary", "detail": "Too complex", "scene_id": "s1"}
            ],
        })

    def test_validate_invalid_status(self):
        with pytest.raises(ValueError, match="must be 'PASS' or 'FAIL'"):
            self.agent.validate({
                "compliance_status": "MAYBE",
                "compliance_violations": [],
            })

    def test_validate_fail_without_violations(self):
        with pytest.raises(ValueError, match="must include at least one violation"):
            self.agent.validate({
                "compliance_status": "FAIL",
                "compliance_violations": [],
            })

    def test_validate_violation_missing_rule(self):
        with pytest.raises(ValueError, match="must have a 'rule' field"):
            self.agent.validate({
                "compliance_status": "FAIL",
                "compliance_violations": [{"detail": "Bad stuff"}],
            })

    def test_validate_violation_missing_detail(self):
        with pytest.raises(ValueError, match="must have a 'detail' field"):
            self.agent.validate({
                "compliance_status": "FAIL",
                "compliance_violations": [{"rule": "vocabulary"}],
            })


# ------------------------------------------------------------------
# NarrationFormatterAgent
# ------------------------------------------------------------------

class TestNarrationFormatter:

    def setup_method(self):
        self.agent = NarrationFormatterAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "narration_script": "[NARRATOR] Once upon a time...\n[VOICE: Aria] Hello!",
            "recap": "Previously on Eldoria: Aria found a mysterious map.",
        })
        result = self.agent.parse(resp)
        assert "[NARRATOR]" in result["narration_script"]
        assert "Previously" in result["recap"]

    def test_validate_valid(self):
        self.agent.validate({
            "narration_script": "Some narration",
            "recap": "Previously...",
        })

    def test_validate_empty_narration(self):
        with pytest.raises(ValueError, match="narration_script must be non-empty"):
            self.agent.validate({
                "narration_script": "",
                "recap": "Previously...",
            })

    def test_validate_empty_recap(self):
        with pytest.raises(ValueError, match="recap must be non-empty"):
            self.agent.validate({
                "narration_script": "Some narration",
                "recap": "",
            })
