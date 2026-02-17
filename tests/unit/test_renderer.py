"""Tests for publish renderer — Markdown and CSV output."""

import shutil
from pathlib import Path

import pytest

from publish.renderer import (
    render_cert_markdown,
    render_dossier_markdown,
    render_lab_markdown,
    render_markdown,
    render_exports,
    export_cert_modules_csv,
    export_cert_questions_csv,
)

TMP_DIR = Path("publish/out/_test_renderer")


@pytest.fixture(autouse=True)
def cleanup():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)


# ---------------------------------------------------------------------------
# Certification Markdown
# ---------------------------------------------------------------------------

class TestCertMarkdown:
    def _state(self):
        return {
            "scope_id": "aws-101",
            "manifest": {"version": "1.0.0"},
            "objectives": [
                {"code": "1.1", "text": "Cloud Fundamentals", "weight": 1.0},
                {"code": "1.2", "text": "Security Basics", "weight": 0.5},
            ],
            "modules": [
                {"module_id": "mod-1", "objective_id": "obj-1", "level": "L1",
                 "title": "Cloud Overview",
                 "content_json": {"sections": ["Intro to cloud"], "claim_refs": ["c1"]}},
            ],
            "questions": [
                {"question_id": "q1", "objective_id": "obj-1", "qtype": "multiple_choice",
                 "content_json": {"question": "What is cloud?", "options": ["A", "B"],
                                  "correct_answer": "A", "explanation": "Because."},
                 "grounding_claim_ids": ["c1"]},
            ],
            "delta_json": {"added_claims": ["c1", "c2"], "removed_claims": [], "changed_claims": []},
            "stability_score": 0.95,
        }

    def test_contains_title(self):
        md = render_cert_markdown(self._state())
        assert "# Certification: aws-101" in md

    def test_contains_version(self):
        md = render_cert_markdown(self._state())
        assert "1.0.0" in md

    def test_contains_objective_map(self):
        md = render_cert_markdown(self._state())
        assert "Objective Map" in md
        assert "Cloud Fundamentals" in md
        assert "1.1" in md

    def test_contains_modules(self):
        md = render_cert_markdown(self._state())
        assert "Lesson Modules" in md
        assert "Cloud Overview" in md

    def test_contains_questions(self):
        md = render_cert_markdown(self._state())
        assert "Question Bank" in md
        assert "What is cloud?" in md

    def test_contains_changelog(self):
        md = render_cert_markdown(self._state())
        assert "Changelog" in md
        assert "c1, c2" in md

    def test_stability_score(self):
        md = render_cert_markdown(self._state())
        assert "0.95" in md


# ---------------------------------------------------------------------------
# Dossier Markdown
# ---------------------------------------------------------------------------

class TestDossierMarkdown:
    def _state(self):
        return {
            "scope_id": "healthcare-ai",
            "manifest": {"version": "2026-02-16"},
            "synthesis": {
                "summary": "AI adoption growing.",
                "key_findings": [
                    {"finding": "Growth 25-40%", "claim_ids": ["c1", "c3"]},
                ],
            },
            "delta_json": {"added_claims": ["c1", "c2", "c3"], "removed_claims": [], "changed_claims": []},
            "metrics": [{"metric_id": "m1", "name": "AI adoption", "unit": "percent"}],
            "metric_points": [{"metric_id": "m1", "value": 40.0, "t": "2025", "confidence": 0.85}],
            "contradictions": [
                {"claim_a_id": "c1", "claim_b_id": "c3", "reason": "Conflicting figures"},
            ],
            "claims": [
                {"claim_id": "c1", "statement": "Growth 40%", "status": "disputed", "confidence": 0.85},
            ],
        }

    def test_contains_title(self):
        md = render_dossier_markdown(self._state())
        assert "Living Dossier: healthcare-ai" in md

    def test_contains_summary(self):
        md = render_dossier_markdown(self._state())
        assert "AI adoption growing." in md

    def test_contains_key_findings(self):
        md = render_dossier_markdown(self._state())
        assert "Growth 25-40%" in md

    def test_contains_metrics_table(self):
        md = render_dossier_markdown(self._state())
        assert "AI adoption" in md
        assert "40.0" in md

    def test_contains_contradictions(self):
        md = render_dossier_markdown(self._state())
        assert "Contradictions" in md
        assert "Conflicting figures" in md

    def test_contains_claims_table(self):
        md = render_dossier_markdown(self._state())
        assert "Claims" in md
        assert "disputed" in md


# ---------------------------------------------------------------------------
# Lab Markdown
# ---------------------------------------------------------------------------

class TestLabMarkdown:
    def _state(self):
        return {
            "scope_id": "bench-1",
            "manifest": {"version": "bench-1-abc12345"},
            "hw_spec": {"gpu": "RTX 4090", "ram": "64GB"},
            "models": [{"model_id": "deepseek-r1:1.5b"}, {"model_id": "qwen2.5:7b"}],
            "synthesis": {
                "summary": "Both models performed adequately.",
                "metrics_summary": "Average accuracy 78%",
                "scores": {"deepseek-r1:1.5b": 0.75, "qwen2.5:7b": 0.82},
                "routing_config": {
                    "local_threshold": 0.7,
                    "frontier_threshold": 0.9,
                    "recommended": {"summarization": "qwen2.5:7b"},
                },
            },
            "metrics": [{"metric_id": "m-acc", "name": "accuracy", "unit": "ratio"}],
            "metric_points": [{"metric_id": "m-acc", "value": 0.78, "t": "2026-02"}],
            "delta_json": {"added_claims": ["d1"]},
        }

    def test_contains_title(self):
        md = render_lab_markdown(self._state())
        assert "AI Lab Report: bench-1" in md

    def test_contains_hardware(self):
        md = render_lab_markdown(self._state())
        assert "RTX 4090" in md

    def test_contains_models(self):
        md = render_lab_markdown(self._state())
        assert "deepseek-r1:1.5b" in md

    def test_contains_scores(self):
        md = render_lab_markdown(self._state())
        assert "0.75" in md
        assert "0.82" in md

    def test_contains_routing(self):
        md = render_lab_markdown(self._state())
        assert "Routing Recommendations" in md
        assert "qwen2.5:7b" in md

    def test_contains_metrics(self):
        md = render_lab_markdown(self._state())
        assert "accuracy" in md


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

class TestRenderDispatch:
    def test_cert_dispatch(self):
        md = render_markdown("cert", {"scope_id": "x", "manifest": {}})
        assert "Certification" in md

    def test_topic_dispatch(self):
        md = render_markdown("topic", {"scope_id": "x", "manifest": {}})
        assert "Dossier" in md

    def test_lab_dispatch(self):
        md = render_markdown("lab", {"scope_id": "x", "manifest": {}})
        assert "Lab Report" in md

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown scope_type"):
            render_markdown("unknown", {})


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------

class TestCSVExports:
    def test_modules_csv(self):
        modules = [
            {"module_id": "mod-1", "objective_id": "obj-1", "level": "L1", "title": "Intro"},
            {"module_id": "mod-2", "objective_id": "obj-2", "level": "L2", "title": "Advanced"},
        ]
        csv_str = export_cert_modules_csv(modules)
        assert "module_id,objective_id,level,title" in csv_str
        assert "mod-1,obj-1,L1,Intro" in csv_str
        assert "mod-2,obj-2,L2,Advanced" in csv_str

    def test_questions_csv(self):
        questions = [
            {"question_id": "q1", "objective_id": "obj-1", "qtype": "multiple_choice",
             "content_json": {"question": "What?", "correct_answer": "A"},
             "grounding_claim_ids": ["c1", "c2"]},
        ]
        csv_str = export_cert_questions_csv(questions)
        assert "question_id" in csv_str
        assert "c1;c2" in csv_str


# ---------------------------------------------------------------------------
# render_exports integration
# ---------------------------------------------------------------------------

class TestRenderExports:
    def test_cert_produces_md_and_csvs(self):
        state = {
            "scope_id": "aws-101", "scope_type": "cert", "manifest": {"version": "1.0.0"},
            "modules": [{"module_id": "m1", "objective_id": "o1", "level": "L1", "title": "X"}],
            "questions": [{"question_id": "q1", "objective_id": "o1", "qtype": "mc",
                           "content_json": {"question": "Q?", "correct_answer": "A"},
                           "grounding_claim_ids": ["c1"]}],
        }
        artifacts = render_exports("cert", state, TMP_DIR)
        names = [a["name"] for a in artifacts]
        assert "report.md" in names
        assert "modules.csv" in names
        assert "questions.csv" in names
        # Files actually exist
        for a in artifacts:
            assert Path(a["path"]).exists()

    def test_topic_produces_md_only(self):
        state = {"scope_id": "x", "scope_type": "topic", "manifest": {}}
        artifacts = render_exports("topic", state, TMP_DIR)
        names = [a["name"] for a in artifacts]
        assert "report.md" in names
        assert "modules.csv" not in names

    def test_lab_produces_md_only(self):
        state = {"scope_id": "x", "scope_type": "lab", "manifest": {}}
        artifacts = render_exports("lab", state, TMP_DIR)
        names = [a["name"] for a in artifacts]
        assert "report.md" in names
        assert "modules.csv" not in names

    def test_hashes_are_valid(self):
        import hashlib
        state = {"scope_id": "x", "scope_type": "topic", "manifest": {}}
        artifacts = render_exports("topic", state, TMP_DIR)
        for a in artifacts:
            data = Path(a["path"]).read_bytes()
            expected = hashlib.sha256(data).hexdigest()
            assert a["hash"] == expected
