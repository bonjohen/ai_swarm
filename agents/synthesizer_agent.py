"""Synthesizer agent — general synthesis constrained to provided claims, metrics, and deltas."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class SynthesizerInput(BaseModel):
    claims: list[dict]
    metrics: list[dict] = []
    metric_points: list[dict] = []
    delta_json: dict = {}


class SynthesizerOutput(BaseModel):
    synthesis: dict


class SynthesizerAgent(BaseAgent):
    AGENT_ID = "synthesizer"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a synthesis agent. Produce a structured synthesis from the provided claims, "
        "metrics, and delta report. You may ONLY reference information explicitly provided — "
        "do not introduce external knowledge. Output valid JSON only.\n\n"
        "Your output must include:\n"
        '- "summary": a concise overview\n'
        '- "key_findings": list of findings, each citing claim_ids\n'
        '- "metrics_summary": summary of metric trends (if metrics provided)\n'
        '- "changes_since_last": summary of what changed (if delta provided)\n'
        '- "contradictions": list of unresolved disputes (if any)'
    )
    USER_TEMPLATE = (
        "Synthesize from the following data.\n\n"
        "Claims:\n{claims}\n\n"
        "Metrics:\n{metrics}\n\n"
        "Metric points:\n{metric_points}\n\n"
        "Delta report:\n{delta_json}\n\n"
        "Scope: {scope_type}/{scope_id}"
    )
    INPUT_SCHEMA = SynthesizerInput
    OUTPUT_SCHEMA = SynthesizerOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=8192,
        confidence_threshold=0.8,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {"synthesis": data}

    def validate(self, output: dict[str, Any]) -> None:
        synthesis = output.get("synthesis")
        if not isinstance(synthesis, dict):
            raise ValueError("synthesis must be a dict")
        if "summary" not in synthesis:
            raise ValueError("synthesis must include 'summary'")
        if "key_findings" not in synthesis:
            raise ValueError("synthesis must include 'key_findings'")
        if not isinstance(synthesis["key_findings"], list):
            raise ValueError("key_findings must be a list")
