"""Scene Writer agent — generates prose for all planned scenes."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class SceneWriterInput(BaseModel):
    act_structure: list[dict]
    scene_plans: list[dict]
    characters: list[dict]
    world_state: dict
    audience_profile: dict
    violations: list[dict] | None = None


class SceneWriterOutput(BaseModel):
    scenes: list[dict]
    episode_text: str


class SceneWriterAgent(BaseAgent):
    AGENT_ID = "scene_writer"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a scene writer for an episodic story engine. "
        "Generate prose for ALL planned scenes, respecting:\n"
        "- The audience profile (vocabulary, complexity, content boundaries)\n"
        "- Character voices and personalities\n"
        "- World rules and setting\n"
        "- The scene plan's conflict, objective, stakes, and emotional arc\n"
        "Each scene must use the exact scene_id from the plan.\n"
        "If violations from a previous pass are provided, fix those specific issues.\n"
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Write prose for all planned scenes.\n\n"
        "Act structure:\n{act_structure}\n\n"
        "Scene plans:\n{scene_plans}\n\n"
        "Characters:\n{characters}\n\n"
        "World state:\n{world_state}\n\n"
        "Audience profile:\n{audience_profile}\n\n"
        "Violations to fix (empty on first pass):\n{violations}\n\n"
        "Return JSON with:\n"
        '- "scenes": [{{"scene_id": str, "text": str, "word_count": int}}]\n'
        '- "episode_text": str (full concatenated text of all scenes)'
    )
    INPUT_SCHEMA = SceneWriterInput
    OUTPUT_SCHEMA = SceneWriterOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=8192,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "scenes": data.get("scenes", []),
            "episode_text": data.get("episode_text", ""),
        }

    def validate(self, output: dict[str, Any]) -> None:
        scenes = output.get("scenes")
        if not isinstance(scenes, list) or len(scenes) == 0:
            raise ValueError("scenes must be a non-empty list")
        for s in scenes:
            if not s.get("scene_id"):
                raise ValueError("Every scene must have a scene_id")
            if not s.get("text"):
                raise ValueError(f"Scene {s.get('scene_id')} has no text")
            wc = s.get("word_count", 0)
            if not isinstance(wc, int) or wc <= 0:
                raise ValueError(f"Scene {s.get('scene_id')} has invalid word_count")
        episode_text = output.get("episode_text", "")
        if not episode_text:
            raise ValueError("episode_text must be non-empty")

    def validate_scene_ids(self, output: dict[str, Any], scene_plans: list[dict]) -> None:
        """Extended validation: every scene_id from plans must appear in output."""
        self.validate(output)
        planned_ids = {s.get("scene_id") for s in scene_plans}
        written_ids = {s.get("scene_id") for s in output["scenes"]}
        missing = planned_ids - written_ids
        if missing:
            raise ValueError(f"Missing scenes from plan: {sorted(missing)}")
