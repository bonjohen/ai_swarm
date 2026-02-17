"""Metric extractor agent — extracts quantitative metrics from text."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class MetricExtractorInput(BaseModel):
    normalized_segments: list[dict]


class MetricExtractorOutput(BaseModel):
    metrics: list[dict]
    metric_points: list[dict]


class MetricExtractorAgent(BaseAgent):
    AGENT_ID = "metric_extractor"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a metric extraction agent. Extract quantitative metrics from text segments. "
        "Each metric must have a name, unit, and dimensions. Each metric point must link to "
        "the source doc/segment for provenance. Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Extract metrics from these segments:\n{normalized_segments}\n"
        "Scope: {scope_type}/{scope_id}\n\n"
        "Return JSON with:\n"
        '- "metrics": [{{"metric_id": str, "name": str, "unit": str, "dimensions": {{}}}}]\n'
        '- "metric_points": [{{"point_id": str, "metric_id": str, "t": str, "value": float, '
        '"doc_id": str, "segment_id": str, "confidence": float}}]'
    )
    INPUT_SCHEMA = MetricExtractorInput
    OUTPUT_SCHEMA = MetricExtractorOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        max_tokens=4096,
        confidence_threshold=0.6,
    )

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {
            "metrics": data.get("metrics", []),
            "metric_points": data.get("metric_points", []),
        }

    def validate(self, output: dict[str, Any]) -> None:
        metrics = output.get("metrics")
        if not isinstance(metrics, list):
            raise ValueError("metrics must be a list")
        for m in metrics:
            if not m.get("metric_id") or not m.get("name"):
                raise ValueError("Each metric must have metric_id and name")
            if not m.get("unit"):
                raise ValueError(f"Metric {m.get('metric_id')} missing unit")

        points = output.get("metric_points")
        if not isinstance(points, list):
            raise ValueError("metric_points must be a list")
        for p in points:
            if not p.get("point_id") or not p.get("metric_id"):
                raise ValueError("Each metric_point must have point_id and metric_id")
            if "value" not in p:
                raise ValueError(f"Metric point {p.get('point_id')} missing value")
