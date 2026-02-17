"""Normalizer agent — cleans and structures raw text segments."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class NormalizerInput(BaseModel):
    segments: list[dict]  # [{segment_id, text, ...}]


class NormalizerOutput(BaseModel):
    normalized_segments: list[dict]


class NormalizerAgent(BaseAgent):
    AGENT_ID = "normalizer"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a text normalization agent. Clean the provided text segments: "
        "strip HTML tags, normalize whitespace, fix encoding issues, and produce "
        "clean structured text. Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Normalize the following segments:\n{source_segments}\n"
        "Return normalized_segments with the same segment_ids."
    )
    INPUT_SCHEMA = NormalizerInput
    OUTPUT_SCHEMA = NormalizerOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        max_tokens=4096,
        confidence_threshold=0.5,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {"normalized_segments": data.get("normalized_segments", [])}

    def validate(self, output: dict[str, Any]) -> None:
        segs = output.get("normalized_segments")
        if not isinstance(segs, list):
            raise ValueError("normalized_segments must be a list")
        for seg in segs:
            if "segment_id" not in seg or "text" not in seg:
                raise ValueError("Each normalized segment must have segment_id and text")

    @staticmethod
    def normalize_text(text: str) -> str:
        """Deterministic text cleanup (no LLM needed)."""
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Normalize unicode whitespace
        text = re.sub(r"[\xa0\u200b\u200c\u200d\ufeff]", " ", text)
        # Collapse multiple whitespace/newlines
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
