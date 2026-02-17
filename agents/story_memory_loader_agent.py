"""Story Memory Loader agent — deterministic, loads world state from DB."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent
from data.dao_story_worlds import get_world
from data.dao_characters import get_characters_for_world
from data.dao_threads import get_open_threads
from data.dao_claims import list_claims_for_scope
from data.dao_snapshots import get_latest_snapshot


class StoryMemoryLoaderInput(BaseModel):
    world_id: str


class StoryMemoryLoaderOutput(BaseModel):
    world_state: dict
    characters: list[dict]
    active_threads: list[dict]
    previous_snapshot: dict | None
    existing_claims: list[dict]
    episode_number: int
    audience_profile: dict
    world_id: str


class StoryMemoryLoaderAgent(BaseAgent):
    AGENT_ID = "story_memory_loader"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "You are a story memory loader agent."
    USER_TEMPLATE = "{_memory_loader_bypass}"
    INPUT_SCHEMA = StoryMemoryLoaderInput
    OUTPUT_SCHEMA = StoryMemoryLoaderOutput
    POLICY = AgentPolicy(allowed_local_models=["local"], max_tokens=2048)

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """Deterministic — loads world state from DB, no LLM call."""
        conn = state["conn"]
        world_id = state["world_id"]

        world = get_world(conn, world_id)
        if world is None:
            raise ValueError(f"World not found: {world_id!r}")

        characters = get_characters_for_world(conn, world_id)
        active_threads = get_open_threads(conn, world_id)
        previous_snapshot = get_latest_snapshot(conn, "story", world_id)
        existing_claims = list_claims_for_scope(conn, "story", world_id)
        episode_number = world["current_episode_number"] + 1
        audience_profile = world.get("audience_profile_json", {})

        result = {
            "world_state": world,
            "characters": characters,
            "active_threads": active_threads,
            "previous_snapshot": previous_snapshot,
            "existing_claims": existing_claims,
            "episode_number": episode_number,
            "audience_profile": audience_profile,
            "world_id": world_id,
        }
        self.validate(result)
        return result

    def parse(self, response: str) -> dict[str, Any]:
        return json.loads(response)

    def validate(self, output: dict[str, Any]) -> None:
        if not isinstance(output.get("world_state"), dict):
            raise ValueError("world_state must be a dict")
        if not isinstance(output.get("characters"), list):
            raise ValueError("characters must be a list")
        if not isinstance(output.get("active_threads"), list):
            raise ValueError("active_threads must be a list")
        if not isinstance(output.get("episode_number"), int):
            raise ValueError("episode_number must be an int")
        if not isinstance(output.get("audience_profile"), dict):
            raise ValueError("audience_profile must be a dict")
        if not output.get("world_id"):
            raise ValueError("world_id is required")
