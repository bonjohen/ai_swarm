"""Canon Updater agent — extracts canonical changes from episode scenes."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent

VALID_CLAIM_TYPES = ("canon_fact", "world_rule", "character_trait", "event", "belief", "legend")


class CanonUpdaterInput(BaseModel):
    scenes: list[dict]
    characters: list[dict]
    world_state: dict
    existing_claims: list[dict]


class CanonUpdaterOutput(BaseModel):
    new_claims: list[dict]
    updated_characters: list[dict]
    new_threads: list[dict]
    resolved_threads: list[str]
    new_entities: list[dict]


class CanonUpdaterAgent(BaseAgent):
    AGENT_ID = "canon_updater"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a canon updater for an episodic story engine. "
        "Extract canonical changes from the episode scenes:\n"
        "- New facts about the world (canon_fact)\n"
        "- New or changed world rules (world_rule)\n"
        "- Character trait changes (character_trait)\n"
        "- Significant events (event)\n"
        "Also identify: character state changes, new narrative threads, "
        "resolved threads, and new entities.\n"
        "Claims should include citations with doc_id (episode_id) and "
        "segment_id (scene_id) when referencing a specific scene.\n"
        "If a claim cannot be tied to a specific scene, use claim_type "
        "'belief' (character/population belief) or 'legend' (unverified lore). "
        "These types do not require citations — they may become the basis "
        "for future investigation plots.\n"
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Extract canonical changes from these scenes.\n\n"
        "Scenes:\n{scenes}\n\n"
        "Characters:\n{characters}\n\n"
        "World state:\n{world_state}\n\n"
        "Existing claims:\n{existing_claims}\n\n"
        "Return JSON with:\n"
        '- "new_claims": [{{"claim_id": str, "statement": str, '
        '"claim_type": "canon_fact"|"world_rule"|"character_trait"|"event", '
        '"entities": [str], "citations": [{{"doc_id": str, "segment_id": str}}], '
        '"evidence_strength": float, "confidence": float}}]\n'
        '- "updated_characters": [{{"character_id": str, "changes": dict}}]\n'
        '- "new_threads": [{{"title": str, "thematic_tag": str, "related_character_ids": [str]}}]\n'
        '- "resolved_threads": [thread_id strings]\n'
        '- "new_entities": [{{"entity_id": str, "type": str, "name": str}}]'
    )
    INPUT_SCHEMA = CanonUpdaterInput
    OUTPUT_SCHEMA = CanonUpdaterOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=4096,
        required_citations=True,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "new_claims": data.get("new_claims", []),
            "updated_characters": data.get("updated_characters", []),
            "new_threads": data.get("new_threads", []),
            "resolved_threads": data.get("resolved_threads", []),
            "new_entities": data.get("new_entities", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        claims = output.get("new_claims")
        if not isinstance(claims, list):
            raise ValueError("new_claims must be a list")
        for c in claims:
            if not c.get("claim_id"):
                raise ValueError("Every claim must have a claim_id")
            if not c.get("statement"):
                raise ValueError(f"Claim {c.get('claim_id')} has no statement")
            ct = c.get("claim_type")
            if ct not in VALID_CLAIM_TYPES:
                raise ValueError(
                    f"Claim {c.get('claim_id')} has invalid claim_type: {ct!r}. "
                    f"Must be one of {VALID_CLAIM_TYPES}"
                )
            # Claims without citations are reclassified as beliefs/legends
            # rather than hard-failing — they become future plot hooks
            citations = c.get("citations", [])
            if not citations and ct not in ("belief", "legend"):
                c["claim_type"] = "belief"
                c.setdefault("_note", "Auto-reclassified: no citation provided")

        if not isinstance(output.get("updated_characters"), list):
            raise ValueError("updated_characters must be a list")
        if not isinstance(output.get("new_threads"), list):
            raise ValueError("new_threads must be a list")
        if not isinstance(output.get("resolved_threads"), list):
            raise ValueError("resolved_threads must be a list")
        if not isinstance(output.get("new_entities"), list):
            raise ValueError("new_entities must be a list")
