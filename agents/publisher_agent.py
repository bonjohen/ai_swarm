"""Publisher agent — render only, packages artifacts to publish/out/."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent

PUBLISH_ROOT = Path("publish/out")


class PublisherInput(BaseModel):
    scope_type: str
    scope_id: str
    snapshot_id: str
    delta_id: str


class PublisherOutput(BaseModel):
    publish_dir: str
    manifest: dict
    artifacts: list[dict]


class PublisherAgent(BaseAgent):
    AGENT_ID = "publisher"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "You are a publisher agent."
    USER_TEMPLATE = "{_publisher_bypass}"
    INPUT_SCHEMA = PublisherInput
    OUTPUT_SCHEMA = PublisherOutput
    POLICY = AgentPolicy(allowed_local_models=["local"], max_tokens=1024)

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """Publishing is deterministic — no LLM call needed."""
        result = self._publish(state)
        self.validate(result)
        return result

    def parse(self, response: str) -> dict[str, Any]:
        return json.loads(response)

    def validate(self, output: dict[str, Any]) -> None:
        if not output.get("publish_dir"):
            raise ValueError("publish_dir is required")
        manifest = output.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a dict")
        if not manifest.get("snapshot_id"):
            raise ValueError("manifest must include snapshot_id")

    def _publish(self, state: dict[str, Any]) -> dict[str, Any]:
        scope_type = state["scope_type"]
        scope_id = state["scope_id"]
        snapshot_id = state.get("snapshot_id", "unknown")
        delta_id = state.get("delta_id", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        # Determine version label
        version = state.get("version", snapshot_id[:8])
        publish_dir = PUBLISH_ROOT / scope_type / scope_id / version
        publish_dir.mkdir(parents=True, exist_ok=True)

        # Build manifest
        manifest = {
            "version": version,
            "snapshot_id": snapshot_id,
            "delta_id": delta_id,
            "generated_at": now,
            "scope_type": scope_type,
            "scope_id": scope_id,
        }

        # Collect domain artifacts from state
        artifacts = []
        artifact_data = {}

        for key in ("claims", "entities", "modules", "questions", "metrics",
                     "metric_points", "synthesis", "delta_json", "scores", "results"):
            if key in state and state[key]:
                artifact_data[key] = state[key]

        # Write each artifact
        for name, data in artifact_data.items():
            content = json.dumps(data, indent=2, default=str)
            file_path = publish_dir / f"{name}.json"
            file_path.write_text(content)
            artifacts.append({
                "name": name,
                "path": str(file_path),
                "hash": hashlib.sha256(content.encode()).hexdigest(),
            })

        # Write manifest
        manifest_path = publish_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # Write artifacts index
        artifacts_index_path = publish_dir / "artifacts.json"
        artifacts_index_path.write_text(json.dumps(artifacts, indent=2))

        return {
            "publish_dir": str(publish_dir),
            "manifest": manifest,
            "artifacts": artifacts,
        }
