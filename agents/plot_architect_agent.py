"""Plot Architect agent — generates structured episode outline (no prose)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class PlotArchitectInput(BaseModel):
    premise: str
    characters: list[dict]
    active_threads: list[dict]
    selected_threads: list[str]
    audience_profile: dict


class PlotArchitectOutput(BaseModel):
    act_structure: list[dict]
    scene_plans: list[dict]


class PlotArchitectAgent(BaseAgent):
    AGENT_ID = "plot_architect"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a plot architect for an episodic story engine. "
        "Generate a structured episode outline with acts and scene plans. "
        "Do NOT write prose — only structured planning.\n"
        "Each scene plan must specify: scene_id, act number, pov_character, "
        "conflict, objective, stakes, and emotional_arc.\n"
        "Ensure every act has at least one scene and every POV character "
        "exists in the provided character list.\n"
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Create a structured episode outline.\n\n"
        "Premise:\n{premise}\n\n"
        "Characters:\n{characters}\n\n"
        "Active threads:\n{active_threads}\n\n"
        "Selected threads for this episode:\n{selected_threads}\n\n"
        "Audience profile:\n{audience_profile}\n\n"
        "Return JSON with:\n"
        '- "act_structure": [{{"act": int, "title": str, "summary": str}}]\n'
        '- "scene_plans": [{{"scene_id": str, "act": int, "pov_character": str, '
        '"conflict": str, "objective": str, "stakes": str, "emotional_arc": str}}]'
    )
    INPUT_SCHEMA = PlotArchitectInput
    OUTPUT_SCHEMA = PlotArchitectOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=4096,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "act_structure": data.get("act_structure", []),
            "scene_plans": data.get("scene_plans", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        acts = output.get("act_structure")
        if not isinstance(acts, list) or len(acts) == 0:
            raise ValueError("act_structure must be a non-empty list")
        scenes = output.get("scene_plans")
        if not isinstance(scenes, list) or len(scenes) < 2:
            raise ValueError("scene_plans must have at least 2 scenes")

        # Every act must have at least one scene
        act_nums = {a.get("act") for a in acts}
        scene_acts = {s.get("act") for s in scenes}
        for act_num in act_nums:
            if act_num not in scene_acts:
                raise ValueError(f"Act {act_num} has no scenes")

        # Every scene must have required fields
        for s in scenes:
            if not s.get("scene_id"):
                raise ValueError("Every scene must have a scene_id")
            if not s.get("pov_character"):
                raise ValueError(f"Scene {s.get('scene_id')} missing pov_character")

    def validate_with_characters(self, output: dict[str, Any], characters: list[dict]) -> None:
        """Extended validation checking POV characters exist in character list."""
        self.validate(output)
        char_names = {c.get("name", "").lower() for c in characters}
        for s in output["scene_plans"]:
            pov = s.get("pov_character", "").lower()
            if pov not in char_names:
                raise ValueError(
                    f"Scene {s['scene_id']} has pov_character '{s['pov_character']}' "
                    f"not found in character list"
                )
