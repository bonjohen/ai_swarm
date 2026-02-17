"""Lesson composer agent — composes lesson modules (L1/L2/L3) per objective."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class LessonComposerInput(BaseModel):
    objectives: list[dict]
    claims: list[dict]
    entities: list[dict] = []


class LessonComposerOutput(BaseModel):
    modules: list[dict]


class LessonComposerAgent(BaseAgent):
    AGENT_ID = "lesson_composer"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a lesson composition agent. For each certification objective, compose "
        "lesson modules at three levels:\n"
        "- L1: Overview / awareness\n"
        "- L2: Working knowledge\n"
        "- L3: Deep expertise\n\n"
        "Each module must be grounded in the provided claims. Reference claim_ids for "
        "every factual statement. Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Compose lesson modules for these objectives:\n{objectives}\n\n"
        "Available claims:\n{claims}\n\n"
        "Known entities:\n{entities}\n\n"
        "Return JSON with:\n"
        '"modules": [{{"module_id": str, "objective_id": str, "level": "L1"|"L2"|"L3", '
        '"title": str, "content_json": {{"sections": [...], "claim_refs": [str]}}}}]'
    )
    INPUT_SCHEMA = LessonComposerInput
    OUTPUT_SCHEMA = LessonComposerOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=8192,
        confidence_threshold=0.7,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {"modules": data.get("modules", [])}

    def validate(self, output: dict[str, Any]) -> None:
        modules = output.get("modules")
        if not isinstance(modules, list):
            raise ValueError("modules must be a list")
        for m in modules:
            if not m.get("module_id"):
                raise ValueError("Each module must have a module_id")
            if not m.get("objective_id"):
                raise ValueError(f"Module {m.get('module_id')} missing objective_id")
            if m.get("level") not in ("L1", "L2", "L3"):
                raise ValueError(f"Module {m.get('module_id')} level must be L1, L2, or L3")
            content = m.get("content_json")
            if not isinstance(content, dict):
                raise ValueError(f"Module {m.get('module_id')} content_json must be a dict")
