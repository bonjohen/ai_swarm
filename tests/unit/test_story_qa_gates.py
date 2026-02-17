"""Tests for story-domain QA gate rules in QAValidatorAgent."""

import pytest

from agents.qa_validator_agent import QAValidatorAgent


@pytest.fixture
def qa():
    return QAValidatorAgent()


def _base_story_state(**overrides):
    """Minimal passing story state."""
    state = {
        "scope_type": "story",
        "scope_id": "w1",
        "doc_ids": [],
        "segment_ids": [],
        "claims": [],
        "metrics": [],
        "metric_points": [],
        "new_claims": [
            {
                "claim_id": "cl1",
                "statement": "A fact",
                "claim_type": "canon_fact",
                "citations": [{"doc_id": "ep1", "segment_id": "s1"}],
            }
        ],
        "characters": [
            {"character_id": "c1", "name": "Aria"},
            {"character_id": "c2", "name": "Bram"},
        ],
        "scene_plans": [
            {"scene_id": "s1", "pov_character": "Aria"},
            {"scene_id": "s2", "pov_character": "Bram"},
        ],
        "scenes": [
            {"scene_id": "s1", "text": "A", "word_count": 10},
            {"scene_id": "s2", "text": "B", "word_count": 10},
        ],
        "selected_threads": ["t1"],
        "new_threads": [],
        "compliance_status": "PASS",
        "compliance_violations": [],
    }
    state.update(overrides)
    return state


# ------------------------------------------------------------------
# Passing case
# ------------------------------------------------------------------

def test_story_qa_pass(qa):
    state = _base_story_state()
    result = qa.run(state)
    assert result["gate_status"] == "PASS"
    assert result["violations"] == []


# ------------------------------------------------------------------
# Rule 1: Canon integrity — claims must have citations
# ------------------------------------------------------------------

def test_story_claim_missing_citations(qa):
    state = _base_story_state(new_claims=[
        {"claim_id": "cl1", "statement": "Fact", "claim_type": "canon_fact", "citations": []},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_claim_has_citations" in rules


def test_story_claim_missing_doc_id(qa):
    state = _base_story_state(new_claims=[
        {"claim_id": "cl1", "statement": "Fact", "claim_type": "canon_fact",
         "citations": [{"doc_id": "", "segment_id": "s1"}]},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_claim_cites_episode" in rules


def test_story_claim_missing_segment_id(qa):
    state = _base_story_state(new_claims=[
        {"claim_id": "cl1", "statement": "Fact", "claim_type": "canon_fact",
         "citations": [{"doc_id": "ep1", "segment_id": ""}]},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_claim_cites_scene" in rules


# ------------------------------------------------------------------
# Rule 2: Character consistency — POV characters must exist
# ------------------------------------------------------------------

def test_story_unknown_pov_character(qa):
    state = _base_story_state(scene_plans=[
        {"scene_id": "s1", "pov_character": "Aria"},
        {"scene_id": "s2", "pov_character": "Unknown Character"},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_pov_character_exists" in rules


# ------------------------------------------------------------------
# Rule 3: Thread tracking — at least one thread advanced
# ------------------------------------------------------------------

def test_story_no_thread_advanced(qa):
    state = _base_story_state(selected_threads=[], new_threads=[])
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_thread_advanced" in rules


def test_story_new_thread_ok(qa):
    """Creating a new thread counts as advancing."""
    state = _base_story_state(
        selected_threads=[],
        new_threads=[{"title": "New Thread", "thematic_tag": "mystery"}],
    )
    result = qa.run(state)
    # No thread-tracking violation
    rules = [v["rule"] for v in result["violations"]]
    assert "story_thread_advanced" not in rules


# ------------------------------------------------------------------
# Rule 4: Audience compliance — must be PASS
# ------------------------------------------------------------------

def test_story_audience_compliance_fail(qa):
    state = _base_story_state(
        compliance_status="FAIL",
        compliance_violations=[{"rule": "vocabulary", "detail": "Too hard"}],
    )
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_audience_compliance" in rules


# ------------------------------------------------------------------
# Rule 5: Structural integrity — at least 2 scenes
# ------------------------------------------------------------------

def test_story_too_few_scenes(qa):
    state = _base_story_state(scenes=[
        {"scene_id": "s1", "text": "A", "word_count": 10},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_min_scenes" in rules


def test_story_exactly_two_scenes_ok(qa):
    state = _base_story_state(scenes=[
        {"scene_id": "s1", "text": "A", "word_count": 10},
        {"scene_id": "s2", "text": "B", "word_count": 10},
    ])
    result = qa.run(state)
    # No structure violation
    rules = [v["rule"] for v in result["violations"]]
    assert "story_min_scenes" not in rules
