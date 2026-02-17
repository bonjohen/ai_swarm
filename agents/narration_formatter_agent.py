"""Narration Formatter agent — converts episode text to read-aloud format."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class NarrationFormatterInput(BaseModel):
    episode_text: str
    characters: list[dict]
    episode_title: str
    delta_json: dict


class NarrationFormatterOutput(BaseModel):
    narration_script: str
    recap: str


class NarrationFormatterAgent(BaseAgent):
    AGENT_ID = "narration_formatter"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a narration formatter for an episodic story engine. "
        "Convert the episode text into a read-aloud format with:\n"
        "- Stage directions in [brackets]\n"
        "- Pause markers: [pause], [long pause]\n"
        "- Emphasis markers: *word* for emphasis\n"
        "- Character voice tags: [VOICE: character_name] before dialogue\n"
        "- Chapter/scene breaks clearly marked\n\n"
        "Also generate a 'Previously on...' recap from the delta report, "
        "summarizing what changed since the last episode.\n"
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Convert this episode into a read-aloud narration script.\n\n"
        "Episode title: {episode_title}\n\n"
        "Episode text:\n{episode_text}\n\n"
        "Characters:\n{characters}\n\n"
        "Delta (changes since last episode):\n{delta_json}\n\n"
        "Return JSON with:\n"
        '- "narration_script": the full narration-ready text with stage directions, '
        "pause markers, emphasis, and voice tags\n"
        '- "recap": a "Previously on..." summary paragraph based on the delta'
    )
    INPUT_SCHEMA = NarrationFormatterInput
    OUTPUT_SCHEMA = NarrationFormatterOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=8192,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "narration_script": data.get("narration_script", ""),
            "recap": data.get("recap", ""),
        }

    def validate(self, output: dict[str, Any]) -> None:
        if not output.get("narration_script"):
            raise ValueError("narration_script must be non-empty")
        if not output.get("recap"):
            raise ValueError("recap must be non-empty")
