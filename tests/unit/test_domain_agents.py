"""Tests for domain-specific agents — synthesizer, lesson_composer, question_generator."""

import json

import pytest

from agents.synthesizer_agent import SynthesizerAgent
from agents.lesson_composer_agent import LessonComposerAgent
from agents.question_generator_agent import QuestionGeneratorAgent
from agents.publisher_agent import PublisherAgent


# --- Synthesizer ---

class TestSynthesizer:
    def setup_method(self):
        self.agent = SynthesizerAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "summary": "Overview",
            "key_findings": [{"finding": "A", "claim_ids": ["c1"]}],
            "metrics_summary": "stable",
            "changes_since_last": "one new claim",
            "contradictions": [],
        })
        result = self.agent.parse(resp)
        assert "synthesis" in result
        assert result["synthesis"]["summary"] == "Overview"

    def test_validate_valid(self):
        self.agent.validate({
            "synthesis": {"summary": "x", "key_findings": []}
        })

    def test_validate_missing_summary(self):
        with pytest.raises(ValueError, match="summary"):
            self.agent.validate({"synthesis": {"key_findings": []}})

    def test_validate_missing_key_findings(self):
        with pytest.raises(ValueError, match="key_findings"):
            self.agent.validate({"synthesis": {"summary": "x"}})


# --- Lesson Composer ---

class TestLessonComposer:
    def setup_method(self):
        self.agent = LessonComposerAgent()

    def _make_module(self, **overrides):
        base = {
            "module_id": "mod-1", "objective_id": "obj-1", "level": "L1",
            "title": "Intro", "content_json": {"sections": [], "claim_refs": ["c1"]},
        }
        base.update(overrides)
        return base

    def test_parse_valid(self):
        resp = json.dumps({"modules": [self._make_module()]})
        result = self.agent.parse(resp)
        assert len(result["modules"]) == 1

    def test_validate_valid(self):
        self.agent.validate({"modules": [self._make_module()]})

    def test_validate_all_levels(self):
        for level in ("L1", "L2", "L3"):
            self.agent.validate({"modules": [self._make_module(level=level)]})

    def test_validate_bad_level(self):
        with pytest.raises(ValueError, match="L1, L2, or L3"):
            self.agent.validate({"modules": [self._make_module(level="L4")]})

    def test_validate_missing_objective_id(self):
        with pytest.raises(ValueError, match="objective_id"):
            self.agent.validate({"modules": [self._make_module(objective_id="")]})

    def test_validate_content_must_be_dict(self):
        with pytest.raises(ValueError, match="content_json must be a dict"):
            self.agent.validate({"modules": [self._make_module(content_json="string")]})


# --- Question Generator ---

class TestQuestionGenerator:
    def setup_method(self):
        self.agent = QuestionGeneratorAgent()

    def _make_question(self, **overrides):
        base = {
            "question_id": "q-1", "objective_id": "obj-1",
            "qtype": "multiple_choice",
            "content_json": {
                "question": "What is cloud?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A",
                "explanation": "Because.",
            },
            "grounding_claim_ids": ["c1"],
        }
        base.update(overrides)
        return base

    def test_parse_valid(self):
        resp = json.dumps({"questions": [self._make_question()]})
        result = self.agent.parse(resp)
        assert len(result["questions"]) == 1

    def test_validate_valid(self):
        self.agent.validate({"questions": [self._make_question()]})

    def test_validate_all_qtypes(self):
        for qtype in ("multiple_choice", "true_false", "short_answer", "scenario"):
            self.agent.validate({"questions": [self._make_question(qtype=qtype)]})

    def test_validate_bad_qtype(self):
        with pytest.raises(ValueError, match="invalid qtype"):
            self.agent.validate({"questions": [self._make_question(qtype="essay")]})

    def test_validate_no_grounding_raises(self):
        with pytest.raises(ValueError, match="no grounding_claim_ids"):
            self.agent.validate({"questions": [self._make_question(grounding_claim_ids=[])]})

    def test_validate_missing_question_text(self):
        with pytest.raises(ValueError, match="content_json"):
            self.agent.validate({"questions": [self._make_question(content_json={"question": ""})]})

    def test_validate_content_must_have_question_field(self):
        with pytest.raises(ValueError, match="content_json"):
            self.agent.validate({"questions": [self._make_question(content_json={"text": "x"})]})


# --- Publisher ---

class TestPublisher:
    def setup_method(self):
        self.agent = PublisherAgent()

    def test_validate_valid(self):
        self.agent.validate({
            "publish_dir": "/tmp/out/cert/x/v1",
            "manifest": {"snapshot_id": "snap-1"},
            "artifacts": [],
        })

    def test_validate_missing_publish_dir(self):
        with pytest.raises(ValueError, match="publish_dir"):
            self.agent.validate({"publish_dir": "", "manifest": {}, "artifacts": []})

    def test_validate_manifest_needs_snapshot(self):
        with pytest.raises(ValueError, match="snapshot_id"):
            self.agent.validate({"publish_dir": "/x", "manifest": {}, "artifacts": []})
