"""Claim extractor agent — extracts atomic claims with citations."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class ClaimExtractorInput(BaseModel):
    normalized_segments: list[dict]
    entities: list[dict]


class ClaimExtractorOutput(BaseModel):
    claims: list[dict]


class ClaimExtractorAgent(BaseAgent):
    AGENT_ID = "claim_extractor"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a claim extraction agent. Extract atomic, verifiable claims from text segments. "
        "Each claim must be linked to at least one citation (doc_id + segment_id). "
        "Assign evidence_strength (0-1) and confidence (0-1) scores. "
        "Set status to 'active' for new claims. Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Extract claims from these segments:\n{normalized_segments}\n\n"
        "Known entities: {entities}\n"
        "Scope: {scope_type}/{scope_id}\n\n"
        "Return JSON with:\n"
        '- "claims": [{{"claim_id": str, "statement": str, "claim_type": str, '
        '"entities": [str], "citations": [{{"doc_id": str, "segment_id": str}}], '
        '"evidence_strength": float, "confidence": float, "status": "active"}}]'
    )
    INPUT_SCHEMA = ClaimExtractorInput
    OUTPUT_SCHEMA = ClaimExtractorOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=8192,
        confidence_threshold=0.7,
        required_citations=True,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {"claims": data.get("claims", [])}

    def validate(self, output: dict[str, Any]) -> None:
        claims = output.get("claims")
        if not isinstance(claims, list):
            raise ValueError("claims must be a list")
        for c in claims:
            if not c.get("claim_id"):
                raise ValueError("Each claim must have a claim_id")
            if not c.get("statement"):
                raise ValueError("Each claim must have a statement")
            if not c.get("claim_type"):
                raise ValueError("Each claim must have a claim_type")
            citations = c.get("citations", [])
            if not citations:
                raise ValueError(f"Claim {c['claim_id']} has no citations — every claim requires at least one")
            for cit in citations:
                if not cit.get("doc_id") or not cit.get("segment_id"):
                    raise ValueError(f"Citation in claim {c['claim_id']} missing doc_id or segment_id")
