"""Entity resolver agent — extracts and deduplicates entities from text."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class EntityResolverInput(BaseModel):
    normalized_segments: list[dict]


class EntityResolverOutput(BaseModel):
    entities: list[dict]
    relationships: list[dict]


class EntityResolverAgent(BaseAgent):
    AGENT_ID = "entity_resolver"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are an entity resolution agent. Extract named entities (people, organizations, "
        "technologies, products, standards, certifications) from the provided text segments. "
        "Resolve duplicates by merging name variants and aliases into a single entity record. "
        "Also extract relationships between entities. Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Extract and resolve entities from these segments:\n{normalized_segments}\n\n"
        "Return JSON with:\n"
        '- "entities": [{{"entity_id": str, "type": str, "names": [str], "props": {{}}}}]\n'
        '- "relationships": [{{"rel_id": str, "type": str, "from_id": str, "to_id": str, "confidence": float}}]'
    )
    INPUT_SCHEMA = EntityResolverInput
    OUTPUT_SCHEMA = EntityResolverOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=4096,
        confidence_threshold=0.7,
        preferred_tier=1,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "entities": data.get("entities", []),
            "relationships": data.get("relationships", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        entities = output.get("entities")
        if not isinstance(entities, list):
            raise ValueError("entities must be a list")
        for e in entities:
            if not e.get("entity_id") or not e.get("type"):
                raise ValueError("Each entity must have entity_id and type")
            if not isinstance(e.get("names", []), list):
                raise ValueError("Entity names must be a list")

        rels = output.get("relationships")
        if not isinstance(rels, list):
            raise ValueError("relationships must be a list")
        for r in rels:
            if not r.get("rel_id") or not r.get("type") or not r.get("from_id") or not r.get("to_id"):
                raise ValueError("Each relationship must have rel_id, type, from_id, to_id")
