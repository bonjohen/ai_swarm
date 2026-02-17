"""Scoring engine — scores benchmark results against rubrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eval.rubrics import Rubric, get_rubric


@dataclass
class ScoreResult:
    """Result of scoring a single task response."""
    task_id: str
    model_id: str
    scores_json: dict[str, float]
    weighted_score: float
    passed: bool
    fail_modes: list[str] = field(default_factory=list)
    notes: str = ""


def score_response(
    *,
    task_id: str,
    model_id: str,
    rubric_id: str,
    component_scores: dict[str, float],
    golden: dict[str, Any] | None = None,
    response_text: str = "",
) -> ScoreResult:
    """Score a model response against a rubric.

    component_scores: pre-computed scores for each rubric component.
    In a full pipeline, an LLM judge or automated checker produces these.
    """
    rubric = get_rubric(rubric_id)

    # Validate all required components are present
    validation_errors = rubric.validate_scores(component_scores)
    fail_modes = validation_errors.copy()

    # Compute weighted score
    weighted = rubric.compute_weighted_score(component_scores)
    passed = rubric.passes(component_scores)

    # Check for specific fail modes
    for comp_name, value in component_scores.items():
        if value == 0.0:
            fail_modes.append(f"zero_score:{comp_name}")

    return ScoreResult(
        task_id=task_id,
        model_id=model_id,
        scores_json=component_scores,
        weighted_score=round(weighted, 4),
        passed=passed,
        fail_modes=fail_modes,
    )


def score_suite(
    results: list[dict[str, Any]],
    rubric_id: str = "accuracy",
) -> list[ScoreResult]:
    """Score a batch of task results.

    Each result dict must have: task_id, model_id, component_scores.
    """
    scored = []
    for r in results:
        scored.append(score_response(
            task_id=r["task_id"],
            model_id=r["model_id"],
            rubric_id=r.get("rubric_id", rubric_id),
            component_scores=r["component_scores"],
            golden=r.get("golden"),
            response_text=r.get("response_text", ""),
        ))
    return scored


def aggregate_scores(results: list[ScoreResult]) -> dict[str, Any]:
    """Aggregate scores across a suite run."""
    if not results:
        return {"count": 0, "avg_score": 0.0, "pass_rate": 0.0}

    total = len(results)
    avg_score = sum(r.weighted_score for r in results) / total
    pass_count = sum(1 for r in results if r.passed)

    # Collect all fail modes
    all_fail_modes: dict[str, int] = {}
    for r in results:
        for fm in r.fail_modes:
            all_fail_modes[fm] = all_fail_modes.get(fm, 0) + 1

    return {
        "count": total,
        "avg_score": round(avg_score, 4),
        "pass_rate": round(pass_count / total, 4),
        "pass_count": pass_count,
        "fail_count": total - pass_count,
        "fail_modes": all_fail_modes,
    }
