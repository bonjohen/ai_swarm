"""Micro router agent — Tier 1 intent classification and tool selection.

Uses deepseek-r1:1.5b with small context (2k) and max_tokens 128 for fast
structured classification.  Outputs a JSON routing decision.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class MicroRouterInput(BaseModel):
    request_text: str
    available_actions: list[str] = []
    available_graphs: list[str] = []


class MicroRouterOutput(BaseModel):
    intent: str
    requires_reasoning: bool
    complexity_score: float
    confidence: float
    recommended_tier: int
    action: str
    target: str


class MicroRouterAgent(BaseAgent):
    AGENT_ID = "micro_router"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a fast intent classification agent. Given a user request, classify the "
        "intent, estimate complexity, and recommend which processing tier should handle it.\n\n"
        "Output a JSON object with exactly these fields:\n"
        "- intent: short string describing the intent (e.g. 'run_cert', 'ask_question', 'analyze_code')\n"
        "- requires_reasoning: boolean, true if the request needs multi-step reasoning\n"
        "- complexity_score: float 0.0-1.0, how complex the request is\n"
        "- confidence: float 0.0-1.0, how confident you are in this classification\n"
        "- recommended_tier: integer 1, 2, or 3 indicating which tier should handle this\n"
        "- action: the action to perform (e.g. 'execute_graph', 'answer_question', 'analyze')\n"
        "- target: the specific target (e.g. 'run_cert.py', 'run_lab.py', or '' if N/A)\n\n"
        "Guidelines for recommended_tier:\n"
        "- Tier 1: simple classification, tool selection, straightforward lookups\n"
        "- Tier 2: short reasoning, extraction, summarization, light synthesis\n"
        "- Tier 3: complex reasoning, multi-document synthesis, high-fidelity output\n\n"
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Classify this request and recommend a processing tier:\n"
        "Request: {request_text}\n"
        "Available actions: {available_actions}\n"
        "Available graphs: {available_graphs}"
    )
    INPUT_SCHEMA = MicroRouterInput
    OUTPUT_SCHEMA = MicroRouterOutput
    POLICY = AgentPolicy(
        allowed_local_models=["micro"],
        max_tokens=128,
        confidence_threshold=0.75,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "intent": str(data.get("intent", "")),
            "requires_reasoning": bool(data.get("requires_reasoning", False)),
            "complexity_score": float(data.get("complexity_score", 0.5)),
            "confidence": float(data.get("confidence", 0.0)),
            "recommended_tier": int(data.get("recommended_tier", 2)),
            "action": str(data.get("action", "")),
            "target": str(data.get("target", "")),
        }

    def validate(self, output: dict[str, Any]) -> None:
        confidence = output.get("confidence", 0)
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {confidence}")

        complexity = output.get("complexity_score", 0)
        if not (0.0 <= complexity <= 1.0):
            raise ValueError(f"complexity_score must be in [0, 1], got {complexity}")

        tier = output.get("recommended_tier", 0)
        if tier not in (1, 2, 3):
            raise ValueError(f"recommended_tier must be 1, 2, or 3, got {tier}")

        if not output.get("intent"):
            raise ValueError("intent must be non-empty")
