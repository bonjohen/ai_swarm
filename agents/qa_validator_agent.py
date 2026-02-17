"""QA validator agent — enforces structural integrity and grounding constraints."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class QAValidatorInput(BaseModel):
    claims: list[dict]
    metrics: list[dict]
    metric_points: list[dict]
    doc_ids: list[str]
    segment_ids: list[str]
    snapshot_id: str | None = None
    delta_id: str | None = None


class QAValidatorOutput(BaseModel):
    gate_status: str  # PASS or FAIL
    violations: list[dict]


class QAValidatorAgent(BaseAgent):
    AGENT_ID = "qa_validator"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "You are a quality assurance validator."
    USER_TEMPLATE = "{_qa_bypass}"
    INPUT_SCHEMA = QAValidatorInput
    OUTPUT_SCHEMA = QAValidatorOutput
    POLICY = AgentPolicy(allowed_local_models=["local"], max_tokens=2048)

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """QA validation is deterministic — no LLM call needed."""
        violations = self._check_all(state)
        gate_status = "FAIL" if violations else "PASS"
        result = {"gate_status": gate_status, "violations": violations}
        self.validate(result)
        return result

    def parse(self, response: str) -> dict[str, Any]:
        return json.loads(response)

    def validate(self, output: dict[str, Any]) -> None:
        if output.get("gate_status") not in ("PASS", "FAIL"):
            raise ValueError("gate_status must be PASS or FAIL")
        if not isinstance(output.get("violations"), list):
            raise ValueError("violations must be a list")

    def _check_all(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        known_doc_ids = set(state.get("doc_ids", []))
        known_segment_ids = set(state.get("segment_ids", []))

        # Rule 1: No claim without citations
        for claim in state.get("claims", []):
            citations = claim.get("citations", claim.get("citations_json", []))
            if not citations:
                violations.append({
                    "rule": "claim_requires_citations",
                    "claim_id": claim.get("claim_id"),
                    "message": "Claim has no citations",
                })
            # Rule 2: Every citation must resolve to a known doc+segment
            for cit in citations:
                if cit.get("doc_id") not in known_doc_ids:
                    violations.append({
                        "rule": "citation_doc_resolves",
                        "claim_id": claim.get("claim_id"),
                        "doc_id": cit.get("doc_id"),
                        "message": "Citation references unknown doc_id",
                    })
                if cit.get("segment_id") not in known_segment_ids:
                    violations.append({
                        "rule": "citation_segment_resolves",
                        "claim_id": claim.get("claim_id"),
                        "segment_id": cit.get("segment_id"),
                        "message": "Citation references unknown segment_id",
                    })

        # Rule 3: Metric points must include unit + dimensions
        metric_lookup = {m.get("metric_id"): m for m in state.get("metrics", [])}
        for pt in state.get("metric_points", []):
            metric = metric_lookup.get(pt.get("metric_id"))
            if metric is None:
                violations.append({
                    "rule": "metric_point_has_metric",
                    "point_id": pt.get("point_id"),
                    "message": "Metric point references unknown metric_id",
                })
            elif not metric.get("unit"):
                violations.append({
                    "rule": "metric_has_unit",
                    "metric_id": metric.get("metric_id"),
                    "message": "Metric missing unit",
                })

        # Rule 4: No publish without snapshot + delta
        if state.get("_check_publish"):
            if not state.get("snapshot_id"):
                violations.append({
                    "rule": "publish_requires_snapshot",
                    "message": "Cannot publish without a snapshot",
                })
            if not state.get("delta_id"):
                violations.append({
                    "rule": "publish_requires_delta",
                    "message": "Cannot publish without a delta",
                })

        return violations
