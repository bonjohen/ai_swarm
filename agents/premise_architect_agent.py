"""Premise Architect agent — generates episode premise aligned to world and audience."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class PremiseArchitectInput(BaseModel):
    world_state: dict
    characters: list[dict]
    active_threads: list[dict]
    audience_profile: dict


class PremiseArchitectOutput(BaseModel):
    premise: str
    episode_title: str
    selected_threads: list[str]


class PremiseArchitectAgent(BaseAgent):
    AGENT_ID = "premise_architect"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a premise architect for an episodic story engine. "
        "Generate a compelling episode premise that:\n"
        "- Advances at least one existing narrative thread (or introduces a new one if none exist)\n"
        "- Fits the world's genre, tone, and constraints\n"
        "- Matches the audience profile (age range, vocabulary level, content boundaries)\n"
        "- Creates clear stakes and conflict for the episode\n"
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Generate an episode premise for this story world.\n\n"
        "World state:\n{world_state}\n\n"
        "Characters:\n{characters}\n\n"
        "Active narrative threads:\n{active_threads}\n\n"
        "Audience profile:\n{audience_profile}\n\n"
        "Return JSON with:\n"
        '- "premise": a 2-4 sentence episode premise\n'
        '- "episode_title": a short, evocative title\n'
        '- "selected_threads": list of thread_id strings to advance in this episode '
        "(select from active threads, or use an empty list if creating a brand new thread)"
    )
    INPUT_SCHEMA = PremiseArchitectInput
    OUTPUT_SCHEMA = PremiseArchitectOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=2048,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "premise": data.get("premise", ""),
            "episode_title": data.get("episode_title", ""),
            "selected_threads": data.get("selected_threads", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        if not output.get("premise"):
            raise ValueError("premise must be non-empty")
        if not output.get("episode_title"):
            raise ValueError("episode_title must be non-empty")
        selected = output.get("selected_threads")
        if not isinstance(selected, list):
            raise ValueError("selected_threads must be a list")
