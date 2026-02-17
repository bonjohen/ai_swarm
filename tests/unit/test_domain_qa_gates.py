"""Tests for domain-specific QA gates — cert, dossier, lab."""

import pytest

from agents.qa_validator_agent import QAValidatorAgent


class TestCertQAGate:
    def setup_method(self):
        self.qa = QAValidatorAgent()

    def _base_state(self):
        return {
            "scope_type": "cert",
            "scope_id": "aws-101",
            "claims": [],
            "metrics": [],
            "metric_points": [],
            "doc_ids": [],
            "segment_ids": [],
        }

    def test_cert_pass_with_modules_and_questions(self):
        state = self._base_state()
        state["objectives"] = [
            {"objective_id": "obj-1", "weight": 1.0},
            {"objective_id": "obj-2", "weight": 0.5},
        ]
        state["modules"] = [
            {"module_id": "m1", "objective_id": "obj-1"},
            {"module_id": "m2", "objective_id": "obj-2"},
        ]
        state["questions"] = [
            {"question_id": "q1", "objective_id": "obj-1"},
            {"question_id": "q2", "objective_id": "obj-1"},
            {"question_id": "q3", "objective_id": "obj-2"},
        ]
        result = self.qa.run(state)
        assert result["gate_status"] == "PASS"

    def test_cert_fail_missing_module(self):
        state = self._base_state()
        state["objectives"] = [{"objective_id": "obj-1", "weight": 1.0}]
        state["modules"] = []  # No modules
        state["questions"] = [
            {"question_id": "q1", "objective_id": "obj-1"},
            {"question_id": "q2", "objective_id": "obj-1"},
        ]
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "cert_objective_has_module" in rules

    def test_cert_fail_insufficient_questions(self):
        state = self._base_state()
        state["objectives"] = [{"objective_id": "obj-1", "weight": 1.0}]
        state["modules"] = [{"module_id": "m1", "objective_id": "obj-1"}]
        state["questions"] = [
            {"question_id": "q1", "objective_id": "obj-1"},
        ]  # Only 1, needs 2 for weight=1.0
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "cert_objective_min_questions" in rules

    def test_cert_weight_proportional_questions(self):
        """Higher weight requires more questions."""
        state = self._base_state()
        state["objectives"] = [{"objective_id": "obj-1", "weight": 2.0}]
        state["modules"] = [{"module_id": "m1", "objective_id": "obj-1"}]
        # weight=2.0, min_questions = ceil(2.0 * 2) = 4
        state["questions"] = [
            {"question_id": f"q{i}", "objective_id": "obj-1"} for i in range(3)
        ]  # Only 3, needs 4
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        v = [v for v in result["violations"] if v["rule"] == "cert_objective_min_questions"][0]
        assert v["expected"] == 4
        assert v["actual"] == 3


class TestDossierQAGate:
    def setup_method(self):
        self.qa = QAValidatorAgent()

    def _base_state(self):
        return {
            "scope_type": "topic",
            "scope_id": "healthcare-ai",
            "claims": [],
            "metrics": [],
            "metric_points": [],
            "doc_ids": [],
            "segment_ids": [],
        }

    def test_dossier_pass_no_contradictions(self):
        state = self._base_state()
        result = self.qa.run(state)
        assert result["gate_status"] == "PASS"

    def test_dossier_pass_with_proper_disputed_status(self):
        state = self._base_state()
        state["contradictions"] = [
            {"claim_a_id": "c1", "claim_b_id": "c2", "reason": "Conflicting figures"},
        ]
        state["claims"] = [
            {"claim_id": "c1", "status": "disputed", "citations": [{"doc_id": "d1", "segment_id": "s1"}]},
            {"claim_id": "c2", "status": "disputed", "citations": [{"doc_id": "d1", "segment_id": "s1"}]},
        ]
        state["doc_ids"] = ["d1"]
        state["segment_ids"] = ["s1"]
        result = self.qa.run(state)
        assert result["gate_status"] == "PASS"

    def test_dossier_fail_non_disputed_contradicting_claim(self):
        state = self._base_state()
        state["contradictions"] = [
            {"claim_a_id": "c1", "claim_b_id": "c2", "reason": "Conflict"},
        ]
        state["claims"] = [
            {"claim_id": "c1", "status": "active", "citations": [{"doc_id": "d1", "segment_id": "s1"}]},
            {"claim_id": "c2", "status": "disputed", "citations": [{"doc_id": "d1", "segment_id": "s1"}]},
        ]
        state["doc_ids"] = ["d1"]
        state["segment_ids"] = ["s1"]
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "dossier_disputed_claim_status" in rules

    def test_dossier_fail_contradiction_no_reason(self):
        state = self._base_state()
        state["contradictions"] = [
            {"claim_a_id": "c1", "claim_b_id": "c2", "reason": ""},
        ]
        state["claims"] = [
            {"claim_id": "c1", "status": "disputed"},
            {"claim_id": "c2", "status": "disputed"},
        ]
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "dossier_contradiction_has_reason" in rules


class TestLabQAGate:
    def setup_method(self):
        self.qa = QAValidatorAgent()

    def _base_state(self):
        return {
            "scope_type": "lab",
            "scope_id": "bench-1",
            "claims": [],
            "metrics": [],
            "metric_points": [],
            "doc_ids": [],
            "segment_ids": [],
            "hw_spec": {"gpu": "RTX 4090"},
            "models": [{"model_id": "model-a"}],
        }

    def test_lab_pass(self):
        state = self._base_state()
        state["synthesis"] = {
            "summary": "OK",
            "key_findings": [],
            "scores": {"model-a": 0.8},
        }
        result = self.qa.run(state)
        assert result["gate_status"] == "PASS"

    def test_lab_fail_missing_hw_spec(self):
        state = self._base_state()
        state["hw_spec"] = {}
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "lab_has_hw_spec" in rules

    def test_lab_fail_no_models(self):
        state = self._base_state()
        state["models"] = []
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "lab_has_models" in rules

    def test_lab_fail_model_missing_score(self):
        state = self._base_state()
        state["models"] = [{"model_id": "model-a"}, {"model_id": "model-b"}]
        state["synthesis"] = {
            "summary": "OK",
            "key_findings": [],
            "scores": {"model-a": 0.8},  # model-b missing
        }
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "lab_model_has_score" in rules

    def test_lab_fail_metrics_referenced_but_missing(self):
        state = self._base_state()
        state["synthesis"] = {
            "summary": "OK",
            "key_findings": [],
            "metrics_summary": "Accuracy 78%",
        }
        state["metrics"] = []
        result = self.qa.run(state)
        assert result["gate_status"] == "FAIL"
        rules = [v["rule"] for v in result["violations"]]
        assert "lab_metrics_present" in rules
