"""Phase 3 publisher tests — golden tests, manifest validation, artifact integrity, QA gate blocking."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from agents import registry
from agents.publisher_agent import PublisherAgent, PUBLISH_ROOT
from agents.qa_validator_agent import QAValidatorAgent


@pytest.fixture(autouse=True)
def cleanup():
    registry.clear()
    registry.register(PublisherAgent())
    registry.register(QAValidatorAgent())
    yield
    registry.clear()
    for scope in ("cert", "topic", "lab"):
        d = PUBLISH_ROOT / scope
        if d.exists():
            shutil.rmtree(d)


def _cert_state():
    return {
        "scope_type": "cert",
        "scope_id": "aws-101",
        "run_id": "r1",
        "graph_id": "certification_graph",
        "snapshot_id": "snap-abc12345",
        "delta_id": "delta-abc12345",
        "gate_status": "PASS",
        "claims": [
            {"claim_id": "c1", "statement": "Cloud is scalable",
             "citations": [{"doc_id": "d1", "segment_id": "s1"}],
             "confidence": 0.9, "status": "active"},
        ],
        "doc_ids": ["d1"],
        "segment_ids": ["s1"],
        "objectives": [
            {"code": "1.1", "text": "Cloud Fundamentals", "weight": 1.0},
        ],
        "modules": [
            {"module_id": "mod-1", "objective_id": "obj-1", "level": "L1",
             "title": "Cloud Overview",
             "content_json": {"sections": ["Intro"], "claim_refs": ["c1"]}},
        ],
        "questions": [
            {"question_id": "q1", "objective_id": "obj-1", "qtype": "multiple_choice",
             "content_json": {"question": "What?", "options": ["A", "B"],
                              "correct_answer": "A", "explanation": "Reason."},
             "grounding_claim_ids": ["c1"]},
        ],
        "metrics": [],
        "metric_points": [],
        "delta_json": {"added_claims": ["c1"], "removed_claims": [], "changed_claims": []},
        "stability_score": 1.0,
    }


def _dossier_state():
    return {
        "scope_type": "topic",
        "scope_id": "healthcare-ai",
        "run_id": "r2",
        "graph_id": "dossier_graph",
        "snapshot_id": "snap-def12345",
        "delta_id": "delta-def12345",
        "claims": [
            {"claim_id": "c1", "statement": "Growth 40%", "status": "disputed",
             "confidence": 0.85, "citations": [{"doc_id": "d1", "segment_id": "s1"}]},
        ],
        "doc_ids": ["d1"],
        "segment_ids": ["s1"],
        "synthesis": {
            "summary": "AI adoption growing.",
            "key_findings": [{"finding": "Growth disputed", "claim_ids": ["c1"]}],
        },
        "metrics": [{"metric_id": "m1", "name": "AI adoption", "unit": "percent"}],
        "metric_points": [{"metric_id": "m1", "value": 40.0, "t": "2025", "confidence": 0.85}],
        "contradictions": [
            {"claim_a_id": "c1", "claim_b_id": "c3", "reason": "Conflicting figures"},
        ],
        "delta_json": {"added_claims": ["c1"], "removed_claims": [], "changed_claims": []},
    }


def _lab_state():
    return {
        "scope_type": "lab",
        "scope_id": "bench-1",
        "run_id": "r3",
        "graph_id": "lab_graph",
        "snapshot_id": "snap-ghi12345",
        "delta_id": "delta-ghi12345",
        "suite_config": {"suite_id": "bench-1"},
        "synthesis": {
            "summary": "Models performed well.",
            "metrics_summary": "Avg accuracy 78%",
            "scores": {"deepseek-r1:1.5b": 0.75},
            "key_findings": [],
        },
        "hw_spec": {"gpu": "RTX 4090"},
        "models": [{"model_id": "deepseek-r1:1.5b"}],
        "metrics": [{"metric_id": "m-acc", "name": "accuracy", "unit": "ratio"}],
        "metric_points": [{"metric_id": "m-acc", "value": 0.78, "t": "2026-02"}],
        "delta_json": {"added_claims": ["d1"]},
    }


# ---------------------------------------------------------------------------
# Manifest schema validation
# ---------------------------------------------------------------------------

class TestManifestSchema:
    REQUIRED_KEYS = {"version", "snapshot_id", "delta_id", "generated_at", "scope_type", "scope_id"}

    def test_cert_manifest_has_required_keys(self):
        agent = PublisherAgent()
        result = agent.run(_cert_state())
        manifest = result["manifest"]
        assert self.REQUIRED_KEYS.issubset(manifest.keys())

    def test_dossier_manifest_has_required_keys(self):
        agent = PublisherAgent()
        result = agent.run(_dossier_state())
        manifest = result["manifest"]
        assert self.REQUIRED_KEYS.issubset(manifest.keys())

    def test_lab_manifest_has_required_keys(self):
        agent = PublisherAgent()
        result = agent.run(_lab_state())
        manifest = result["manifest"]
        assert self.REQUIRED_KEYS.issubset(manifest.keys())


# ---------------------------------------------------------------------------
# Artifacts integrity — paths exist, hashes match
# ---------------------------------------------------------------------------

class TestArtifactIntegrity:
    def _check_artifacts(self, state):
        agent = PublisherAgent()
        result = agent.run(state)
        publish_dir = Path(result["publish_dir"])
        artifacts = result["artifacts"]

        # manifest.json exists
        assert (publish_dir / "manifest.json").exists()

        # artifacts.json exists
        assert (publish_dir / "artifacts.json").exists()

        # All listed artifact files exist and hashes match
        for art in artifacts:
            path = Path(art["path"])
            assert path.exists(), f"Artifact path does not exist: {path}"
            data = path.read_bytes()
            expected_hash = hashlib.sha256(data).hexdigest()
            assert art["hash"] == expected_hash, f"Hash mismatch for {art['name']}"

        return result

    def test_cert_artifacts(self):
        result = self._check_artifacts(_cert_state())
        names = [a["name"] for a in result["artifacts"]]
        assert "claims" in names
        assert "report.md" in names
        assert "modules.csv" in names
        assert "questions.csv" in names

    def test_dossier_artifacts(self):
        result = self._check_artifacts(_dossier_state())
        names = [a["name"] for a in result["artifacts"]]
        assert "claims" in names
        assert "synthesis" in names
        assert "report.md" in names
        # Dossier should NOT have CSVs
        assert "modules.csv" not in names

    def test_lab_artifacts(self):
        result = self._check_artifacts(_lab_state())
        names = [a["name"] for a in result["artifacts"]]
        assert "synthesis" in names
        assert "report.md" in names
        assert "modules.csv" not in names


# ---------------------------------------------------------------------------
# Golden tests — deterministic content hash comparisons
# ---------------------------------------------------------------------------

class TestGoldenOutput:
    def test_cert_report_md_is_deterministic(self):
        """Same input → same Markdown output."""
        agent = PublisherAgent()
        state = _cert_state()
        state["version"] = "1.0.0"  # Fix version for determinism

        result1 = agent.run(state)
        # Clean and re-run
        d = Path(result1["publish_dir"])
        if d.exists():
            shutil.rmtree(d)

        result2 = agent.run(state)

        # Find report.md hash in both runs
        def _md_hash(result):
            for a in result["artifacts"]:
                if a["name"] == "report.md":
                    return a["hash"]
            return None

        assert _md_hash(result1) == _md_hash(result2)

    def test_cert_json_artifacts_deterministic(self):
        """JSON artifact content is stable."""
        agent = PublisherAgent()
        state = _cert_state()
        state["version"] = "1.0.0"

        result = agent.run(state)
        publish_dir = Path(result["publish_dir"])
        claims_json = json.loads((publish_dir / "claims.json").read_text())
        assert claims_json == state["claims"]

    def test_dossier_report_contains_expected_sections(self):
        """Golden check: dossier report has all expected sections."""
        agent = PublisherAgent()
        result = agent.run(_dossier_state())
        report_path = None
        for a in result["artifacts"]:
            if a["name"] == "report.md":
                report_path = Path(a["path"])
                break
        assert report_path and report_path.exists()
        content = report_path.read_text()
        assert "Living Dossier" in content
        assert "Summary" in content
        assert "Key Findings" in content
        assert "Metrics" in content
        assert "Contradictions" in content
        assert "Claims" in content


# ---------------------------------------------------------------------------
# Versioning integration
# ---------------------------------------------------------------------------

class TestVersioningIntegration:
    def test_cert_gets_semver(self):
        agent = PublisherAgent()
        result = agent.run(_cert_state())
        version = result["manifest"]["version"]
        # Should be semver format
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_cert_increments_on_second_publish(self):
        agent = PublisherAgent()
        r1 = agent.run(_cert_state())
        r2 = agent.run(_cert_state())
        assert r1["manifest"]["version"] == "1.0.0"
        assert r2["manifest"]["version"] == "1.1.0"

    def test_dossier_gets_date_version(self):
        agent = PublisherAgent()
        result = agent.run(_dossier_state())
        version = result["manifest"]["version"]
        parts = version.split("-")
        assert len(parts) == 3  # YYYY-MM-DD

    def test_lab_gets_suite_version(self):
        agent = PublisherAgent()
        result = agent.run(_lab_state())
        version = result["manifest"]["version"]
        assert version.startswith("bench-1-")

    def test_explicit_version_overrides_auto(self):
        agent = PublisherAgent()
        state = _cert_state()
        state["version"] = "99.0.0"
        result = agent.run(state)
        assert result["manifest"]["version"] == "99.0.0"


# ---------------------------------------------------------------------------
# QA gate blocking — publish blocked when gate hasn't passed
# ---------------------------------------------------------------------------

class TestQAGateBlocking:
    def test_qa_fail_blocks_publish(self):
        """When claims have no citations, QA gate fails → FAIL status."""
        qa = QAValidatorAgent()
        state = {
            "scope_type": "cert",
            "scope_id": "aws-101",
            "claims": [
                {"claim_id": "c1", "statement": "Bad claim", "citations": []},
            ],
            "metrics": [],
            "metric_points": [],
            "doc_ids": ["d1"],
            "segment_ids": ["s1"],
        }
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        assert len(result["violations"]) > 0

    def test_qa_pass_allows_publish(self):
        """When all rules pass, gate_status is PASS."""
        qa = QAValidatorAgent()
        state = {
            "scope_type": "cert",
            "scope_id": "aws-101",
            "claims": [
                {"claim_id": "c1", "statement": "Good claim",
                 "citations": [{"doc_id": "d1", "segment_id": "s1"}]},
            ],
            "metrics": [{"metric_id": "m1", "unit": "percent"}],
            "metric_points": [{"point_id": "p1", "metric_id": "m1"}],
            "doc_ids": ["d1"],
            "segment_ids": ["s1"],
        }
        result = qa.run(state)
        assert result["gate_status"] == "PASS"

    def test_publish_requires_snapshot_via_qa(self):
        """QA gate catches missing snapshot when _check_publish flag is set."""
        qa = QAValidatorAgent()
        state = {
            "scope_type": "cert",
            "scope_id": "aws-101",
            "claims": [],
            "metrics": [],
            "metric_points": [],
            "doc_ids": [],
            "segment_ids": [],
            "_check_publish": True,
            # No snapshot_id or delta_id
        }
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "publish_requires_snapshot" in rules
        assert "publish_requires_delta" in rules

    def test_publish_passes_with_snapshot_and_delta(self):
        """QA gate passes when snapshot + delta present."""
        qa = QAValidatorAgent()
        state = {
            "scope_type": "cert",
            "scope_id": "aws-101",
            "claims": [],
            "metrics": [],
            "metric_points": [],
            "doc_ids": [],
            "segment_ids": [],
            "_check_publish": True,
            "snapshot_id": "snap-123",
            "delta_id": "delta-123",
        }
        result = qa.run(state)
        assert result["gate_status"] == "PASS"
