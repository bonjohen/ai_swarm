"""Ingestor agent — fetches raw sources, produces source_docs and segments."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class IngestorInput(BaseModel):
    sources: list[dict]  # [{uri, source_type, ...}]


class IngestorOutput(BaseModel):
    doc_ids: list[str]
    segment_ids: list[str]


class IngestorAgent(BaseAgent):
    AGENT_ID = "ingestor"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a document ingestion agent. Given a list of source URIs and their types, "
        "fetch each source, segment it into logical chunks, and return structured doc and segment records. "
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Ingest the following sources and return doc_ids and segment_ids:\n"
        "Sources: {sources}\n"
        "Scope: {scope_type}/{scope_id}"
    )
    INPUT_SCHEMA = IngestorInput
    OUTPUT_SCHEMA = IngestorOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        max_tokens=4096,
        confidence_threshold=0.5,
        preferred_tier=1,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "doc_ids": data.get("doc_ids", []),
            "segment_ids": data.get("segment_ids", []),
            "source_docs": data.get("source_docs", []),
            "source_segments": data.get("source_segments", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        if not isinstance(output.get("doc_ids"), list):
            raise ValueError("doc_ids must be a list")
        if not isinstance(output.get("segment_ids"), list):
            raise ValueError("segment_ids must be a list")

    @staticmethod
    def make_doc_record(
        uri: str,
        source_type: str,
        text: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Helper to build a source_doc record outside of LLM flow."""
        now = datetime.now(timezone.utc).isoformat()
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        return {
            "doc_id": str(uuid.uuid4()),
            "uri": uri,
            "source_type": source_type,
            "retrieved_at": now,
            "title": title,
            "content_hash": content_hash,
            "text": text,
        }

    @staticmethod
    def segment_text(doc_id: str, text: str, max_chars: int = 2000) -> list[dict[str, Any]]:
        """Split text into segments of roughly max_chars, breaking on paragraph boundaries."""
        paragraphs = text.split("\n\n")
        segments: list[dict[str, Any]] = []
        current_chunk: list[str] = []
        current_len = 0
        idx = 0

        for para in paragraphs:
            if current_len + len(para) > max_chars and current_chunk:
                segments.append({
                    "segment_id": str(uuid.uuid4()),
                    "doc_id": doc_id,
                    "idx": idx,
                    "text": "\n\n".join(current_chunk),
                })
                idx += 1
                current_chunk = []
                current_len = 0
            current_chunk.append(para)
            current_len += len(para)

        if current_chunk:
            segments.append({
                "segment_id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "idx": idx,
                "text": "\n\n".join(current_chunk),
            })

        return segments
