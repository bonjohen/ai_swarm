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
# Canon integrity — citations relaxed for story scope
# Uncited claims become beliefs/legends (future plot hooks).
# ------------------------------------------------------------------

def test_story_claim_without_citations_passes(qa):
    """Story claims without citations do NOT cause QA failure."""
    state = _base_story_state(new_claims=[
        {"claim_id": "cl1", "statement": "Fact", "claim_type": "canon_fact", "citations": []},
    ])
    result = qa.run(state)
    # No citation-related violations for story scope
    rules = [v["rule"] for v in result["violations"]]
    assert "story_claim_has_citations" not in rules
    assert "story_claim_cites_episode" not in rules
    assert "story_claim_cites_scene" not in rules


def test_story_global_citation_rules_skipped(qa):
    """Global citation rules are skipped for story scope."""
    state = _base_story_state(claims=[
        {"claim_id": "cl-global", "statement": "A", "citations": []},
    ])
    result = qa.run(state)
    rules = [v["rule"] for v in result["violations"]]
    assert "claim_requires_citations" not in rules
    assert "citation_doc_resolves" not in rules


# ------------------------------------------------------------------
# Soft warnings (POV character, thread tracking, min scenes)
# These are logged as warnings but do NOT cause FAIL.
# ------------------------------------------------------------------

def test_story_unknown_pov_character_is_soft_warning(qa):
    """Unknown POV character is a soft warning, not a hard failure."""
    state = _base_story_state(scene_plans=[
        {"scene_id": "s1", "pov_character": "Aria"},
        {"scene_id": "s2", "pov_character": "Unknown Character"},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "PASS"
    # Warning stored in state, not in violations
    warnings = state.get("_qa_warnings", [])
    rules = [w["rule"] for w in warnings]
    assert "story_pov_character_exists" in rules


def test_story_no_thread_advanced_is_soft_warning(qa):
    """Missing thread advancement is a soft warning."""
    state = _base_story_state(selected_threads=[], new_threads=[])
    result = qa.run(state)
    assert result["gate_status"] == "PASS"
    warnings = state.get("_qa_warnings", [])
    rules = [w["rule"] for w in warnings]
    assert "story_thread_advanced" in rules


def test_story_new_thread_ok(qa):
    """Creating a new thread means no thread warning."""
    state = _base_story_state(
        selected_threads=[],
        new_threads=[{"title": "New Thread", "thematic_tag": "mystery"}],
    )
    result = qa.run(state)
    warnings = state.get("_qa_warnings", [])
    rules = [w["rule"] for w in warnings]
    assert "story_thread_advanced" not in rules


def test_story_one_scene_is_soft_warning(qa):
    """One scene is a soft warning (2+ preferred, 0 is hard fail)."""
    state = _base_story_state(scenes=[
        {"scene_id": "s1", "text": "A", "word_count": 10},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "PASS"
    warnings = state.get("_qa_warnings", [])
    rules = [w["rule"] for w in warnings]
    assert "story_min_scenes" in rules


def test_story_zero_scenes_is_hard_fail(qa):
    """Zero scenes is a hard failure."""
    state = _base_story_state(scenes=[])
    result = qa.run(state)
    assert result["gate_status"] == "FAIL"
    rules = [v["rule"] for v in result["violations"]]
    assert "story_min_scenes" in rules


# ------------------------------------------------------------------
# Hard failure: Audience compliance — safety gate
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


def test_story_exactly_two_scenes_ok(qa):
    state = _base_story_state(scenes=[
        {"scene_id": "s1", "text": "A", "word_count": 10},
        {"scene_id": "s2", "text": "B", "word_count": 10},
    ])
    result = qa.run(state)
    assert result["gate_status"] == "PASS"
