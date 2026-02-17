"""Tests for QA validator agent — each gate rule pass and fail."""

import pytest
from agents.qa_validator_agent import QAValidatorAgent


@pytest.fixture
def qa():
    return QAValidatorAgent()


def _base_state(**overrides):
    state = {
        "scope_type": "cert",
        "scope_id": "c1",
        "run_id": "r1",
        "graph_id": "test",
        "doc_ids": ["d1"],
        "segment_ids": ["s1"],
        "claims": [],
        "metrics": [],
        "metric_points": [],
    }
    state.update(overrides)
    return state


class TestQAPassCases:
    def test_no_claims_passes(self, qa):
        result = qa.run(_base_state())
        assert result["gate_status"] == "PASS"
        assert result["violations"] == []

    def test_valid_claim_passes(self, qa):
        state = _base_state(claims=[{
            "claim_id": "c1",
            "statement": "test",
            "citations": [{"doc_id": "d1", "segment_id": "s1"}],
        }])
        result = qa.run(state)
        assert result["gate_status"] == "PASS"

    def test_valid_metric_passes(self, qa):
        state = _base_state(
            metrics=[{"metric_id": "m1", "unit": "ms"}],
            metric_points=[{"point_id": "p1", "metric_id": "m1"}],
        )
        result = qa.run(state)
        assert result["gate_status"] == "PASS"


class TestQAFailCases:
    def test_claim_without_citations_fails(self, qa):
        state = _base_state(claims=[{
            "claim_id": "c1",
            "statement": "test",
            "citations": [],
        }])
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        assert any(v["rule"] == "claim_requires_citations" for v in result["violations"])

    def test_citation_unknown_doc_fails(self, qa):
        state = _base_state(claims=[{
            "claim_id": "c1",
            "statement": "test",
            "citations": [{"doc_id": "unknown", "segment_id": "s1"}],
        }])
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        assert any(v["rule"] == "citation_doc_resolves" for v in result["violations"])

    def test_citation_unknown_segment_fails(self, qa):
        state = _base_state(claims=[{
            "claim_id": "c1",
            "statement": "test",
            "citations": [{"doc_id": "d1", "segment_id": "unknown"}],
        }])
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        assert any(v["rule"] == "citation_segment_resolves" for v in result["violations"])

    def test_metric_point_unknown_metric_fails(self, qa):
        state = _base_state(
            metrics=[],
            metric_points=[{"point_id": "p1", "metric_id": "missing"}],
        )
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        assert any(v["rule"] == "metric_point_has_metric" for v in result["violations"])

    def test_metric_missing_unit_fails(self, qa):
        state = _base_state(
            metrics=[{"metric_id": "m1", "unit": ""}],
            metric_points=[{"point_id": "p1", "metric_id": "m1"}],
        )
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        assert any(v["rule"] == "metric_has_unit" for v in result["violations"])

    def test_publish_without_snapshot_fails(self, qa):
        state = _base_state(_check_publish=True)
        result = qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "publish_requires_snapshot" in rules
        assert "publish_requires_delta" in rules

    def test_publish_with_snapshot_and_delta_passes(self, qa):
        state = _base_state(_check_publish=True, snapshot_id="snap-1", delta_id="delta-1")
        result = qa.run(state)
        assert result["gate_status"] == "PASS"


class TestQAValidateMethod:
    def test_validate_pass(self, qa):
        qa.validate({"gate_status": "PASS", "violations": []})

    def test_validate_fail(self, qa):
        qa.validate({"gate_status": "FAIL", "violations": [{"rule": "x"}]})

    def test_validate_bad_status_raises(self, qa):
        with pytest.raises(ValueError, match="PASS or FAIL"):
            qa.validate({"gate_status": "MAYBE", "violations": []})
