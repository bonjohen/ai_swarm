"""Audience Compliance agent — validates episode text against audience profile."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class AudienceComplianceInput(BaseModel):
    episode_text: str
    audience_profile: dict


class AudienceComplianceOutput(BaseModel):
    compliance_status: str
    compliance_violations: list[dict]


class AudienceComplianceAgent(BaseAgent):
    AGENT_ID = "audience_compliance"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are an audience compliance validator for an episodic story engine. "
        "Validate the episode text against the audience profile constraints:\n"
        "- Vocabulary difficulty (match the target level)\n"
        "- Sentence complexity (appropriate for age range)\n"
        "- Content boundaries (violence, themes within tolerance)\n"
        "- Pacing (appropriate for attention span)\n"
        "Return PASS if compliant, FAIL if violations found.\n"
        "For each violation, specify the rule broken, detail, and scene_id.\n"
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Validate this episode text against the audience profile.\n\n"
        "Episode text:\n{episode_text}\n\n"
        "Audience profile:\n{audience_profile}\n\n"
        "Return JSON with:\n"
        '- "compliance_status": "PASS" or "FAIL"\n'
        '- "compliance_violations": [{{"rule": str, "detail": str, "scene_id": str}}]'
    )
    INPUT_SCHEMA = AudienceComplianceInput
    OUTPUT_SCHEMA = AudienceComplianceOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=4096,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "compliance_status": data.get("compliance_status", ""),
            "compliance_violations": data.get("compliance_violations", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        status = output.get("compliance_status")
        if status not in ("PASS", "FAIL"):
            raise ValueError(
                f"compliance_status must be 'PASS' or 'FAIL', got {status!r}"
            )
        violations = output.get("compliance_violations")
        if not isinstance(violations, list):
            raise ValueError("compliance_violations must be a list")
        if status == "FAIL" and not violations:
            raise ValueError("FAIL status must include at least one violation")
        for v in violations:
            if not isinstance(v, dict):
                raise ValueError("Each violation must be a dict")
            if not v.get("rule"):
                raise ValueError("Each violation must have a 'rule' field")
            if not v.get("detail"):
                raise ValueError("Each violation must have a 'detail' field")
