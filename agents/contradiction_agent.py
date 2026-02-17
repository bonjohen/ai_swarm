"""Contradiction agent — detects conflicting claims and sets status to disputed."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class ContradictionInput(BaseModel):
    claims: list[dict]
    existing_claims: list[dict]


class ContradictionOutput(BaseModel):
    contradictions: list[dict]
    updated_claim_ids: list[str]


class ContradictionAgent(BaseAgent):
    AGENT_ID = "contradiction"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a contradiction detection agent. Compare new claims against existing claims "
        "for the same scope. Identify contradictions where two claims make incompatible statements. "
        "For each contradiction, provide both sides with their citations. "
        "Mark contradicting claims as 'disputed'. Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Check for contradictions.\n\n"
        "New claims:\n{claims}\n\n"
        "Existing claims:\n{existing_claims}\n\n"
        "Return JSON with:\n"
        '- "contradictions": [{{"claim_a_id": str, "claim_b_id": str, '
        '"reason": str, "severity": "low"|"medium"|"high"}}]\n'
        '- "updated_claim_ids": [str]  (claims whose status changed to disputed)'
    )
    INPUT_SCHEMA = ContradictionInput
    OUTPUT_SCHEMA = ContradictionOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=4096,
        confidence_threshold=0.8,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "contradictions": data.get("contradictions", []),
            "updated_claim_ids": data.get("updated_claim_ids", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        contradictions = output.get("contradictions")
        if not isinstance(contradictions, list):
            raise ValueError("contradictions must be a list")
        for c in contradictions:
            if not c.get("claim_a_id") or not c.get("claim_b_id"):
                raise ValueError("Each contradiction must reference claim_a_id and claim_b_id")
            if not c.get("reason"):
                raise ValueError("Each contradiction must have a reason")

        updated = output.get("updated_claim_ids")
        if not isinstance(updated, list):
            raise ValueError("updated_claim_ids must be a list")
