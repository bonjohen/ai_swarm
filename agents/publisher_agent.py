"""Publisher agent — render only, packages artifacts to publish/out/."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent

PUBLISH_ROOT = Path("publish/out")


def _next_semver(publish_root: Path, scope_type: str, scope_id: str) -> str:
    """Compute next semver for certification publishes (e.g. 1.0.0 → 1.1.0)."""
    base = publish_root / scope_type / scope_id
    if not base.exists():
        return "1.0.0"
    existing = []
    for d in base.iterdir():
        if d.is_dir() and re.match(r"^\d+\.\d+\.\d+$", d.name):
            existing.append(tuple(int(x) for x in d.name.split(".")))
    if not existing:
        return "1.0.0"
    latest = max(existing)
    return f"{latest[0]}.{latest[1] + 1}.0"


def _date_version() -> str:
    """Date-based version for dossier publishes (e.g. 2026-02-16)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _suite_version(state: dict[str, Any]) -> str:
    """Suite-based version for lab publishes: suite_id + short snapshot hash."""
    suite_id = state.get("suite_config", {}).get("suite_id", state.get("scope_id", "suite"))
    snap = state.get("snapshot_id", "unknown")[:8]
    return f"{suite_id}-{snap}"


def _episode_version(state: dict[str, Any]) -> str:
    """Episode-number version for story publishes: E001, E002, etc."""
    ep_num = state.get("episode_number", 1)
    return f"E{ep_num:03d}"


def auto_version(scope_type: str, state: dict[str, Any], publish_root: Path = PUBLISH_ROOT) -> str:
    """Generate a version label based on scope_type."""
    if scope_type == "cert":
        return _next_semver(publish_root, scope_type, state.get("scope_id", "unknown"))
    elif scope_type == "topic":
        return _date_version()
    elif scope_type == "lab":
        return _suite_version(state)
    elif scope_type == "story":
        return _episode_version(state)
    else:
        # Fallback: short snapshot hash
        return state.get("snapshot_id", "unknown")[:8]


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
    POLICY = AgentPolicy(allowed_local_models=["local"], max_tokens=1024, preferred_tier=0)

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

        # Check license flags — filter out restricted content from verbatim republish
        restricted_docs = set(state.get("_restricted_doc_ids", []))
        if restricted_docs:
            claims = state.get("claims", [])
            for claim in claims:
                citations = claim.get("citations_json", claim.get("citations", []))
                if isinstance(citations, str):
                    citations = json.loads(citations)
                for cit in citations:
                    doc_id = cit.get("doc_id", "")
                    if doc_id in restricted_docs:
                        claim["_license_restricted"] = True
                        break

        # Determine version label
        version = state.get("version") or auto_version(scope_type, state)
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
                     "metric_points", "synthesis", "delta_json", "scores", "results",
                     "new_claims", "scenes", "narration_script", "recap", "episode_text"):
            if key in state and state[key]:
                artifact_data[key] = state[key]

        # Write each artifact (binary mode for consistent hashing)
        for name, data in artifact_data.items():
            content_bytes = json.dumps(data, indent=2, default=str).encode("utf-8")
            file_path = publish_dir / f"{name}.json"
            file_path.write_bytes(content_bytes)
            artifacts.append({
                "name": name,
                "path": str(file_path),
                "hash": hashlib.sha256(content_bytes).hexdigest(),
            })

        # Render Markdown + CSV exports
        from publish.renderer import render_exports
        export_artifacts = render_exports(scope_type, {**state, "manifest": manifest}, publish_dir)
        artifacts.extend(export_artifacts)

        # Write manifest
        manifest_path = publish_dir / "manifest.json"
        manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))

        # Write artifacts index
        artifacts_index_path = publish_dir / "artifacts.json"
        artifacts_index_path.write_bytes(json.dumps(artifacts, indent=2).encode("utf-8"))

        return {
            "publish_dir": str(publish_dir),
            "manifest": manifest,
            "artifacts": artifacts,
        }
