"""Delta agent — creates snapshots and computes deltas between them."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class DeltaInput(BaseModel):
    claims: list[dict]
    metrics: list[dict]
    previous_snapshot: dict | None = None


class DeltaOutput(BaseModel):
    snapshot_id: str
    delta_id: str
    delta_json: dict
    stability_score: float


class DeltaAgent(BaseAgent):
    AGENT_ID = "delta"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "You are a snapshot and delta computation agent."
    USER_TEMPLATE = "{_delta_bypass}"
    INPUT_SCHEMA = DeltaInput
    OUTPUT_SCHEMA = DeltaOutput
    POLICY = AgentPolicy(allowed_local_models=["local"], max_tokens=2048)

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """Snapshot + delta is deterministic — no LLM call needed."""
        result = self._compute(state)
        self.validate(result)
        return result

    def parse(self, response: str) -> dict[str, Any]:
        return json.loads(response)

    def validate(self, output: dict[str, Any]) -> None:
        if not output.get("snapshot_id"):
            raise ValueError("snapshot_id is required")
        if not output.get("delta_id"):
            raise ValueError("delta_id is required")
        if not isinstance(output.get("delta_json"), dict):
            raise ValueError("delta_json must be a dict")

    def _compute(self, state: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        claims = state.get("claims", [])
        metrics = state.get("metrics", [])

        current_claim_ids = sorted(c.get("claim_id", "") for c in claims)
        current_metric_ids = sorted(m.get("metric_id", "") for m in metrics)

        # Build snapshot
        snapshot_hash = hashlib.sha256(
            json.dumps({"claims": current_claim_ids, "metrics": current_metric_ids}).encode()
        ).hexdigest()[:16]

        snapshot_id = str(uuid.uuid4())

        # Compute delta vs previous snapshot
        prev = state.get("previous_snapshot")
        prev_claim_ids = set(prev.get("included_claim_ids_json", [])) if prev else set()
        prev_metric_ids = set(prev.get("included_metric_ids_json", [])) if prev else set()

        current_claim_set = set(current_claim_ids)
        current_metric_set = set(current_metric_ids)

        added_claims = sorted(current_claim_set - prev_claim_ids)
        removed_claims = sorted(prev_claim_ids - current_claim_set)
        added_metrics = sorted(current_metric_set - prev_metric_ids)
        removed_metrics = sorted(prev_metric_ids - current_metric_set)

        # Stability score: 1.0 = nothing changed, 0.0 = everything changed
        total = max(len(current_claim_set | prev_claim_ids) + len(current_metric_set | prev_metric_ids), 1)
        changed = len(added_claims) + len(removed_claims) + len(added_metrics) + len(removed_metrics)
        stability_score = round(1.0 - (changed / total), 4)

        delta_json = {
            "added_claims": added_claims,
            "removed_claims": removed_claims,
            "added_metrics": added_metrics,
            "removed_metrics": removed_metrics,
        }

        delta_id = str(uuid.uuid4())

        return {
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "snapshot_created_at": now,
            "included_claim_ids": current_claim_ids,
            "included_metric_ids": current_metric_ids,
            "delta_id": delta_id,
            "delta_json": delta_json,
            "stability_score": stability_score,
            "from_snapshot_id": prev.get("snapshot_id") if prev else None,
        }
