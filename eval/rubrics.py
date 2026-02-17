"""Scoring rubrics with required score components."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreComponent:
    """A single scoring dimension within a rubric."""
    name: str
    weight: float = 1.0
    min_score: float = 0.0
    max_score: float = 1.0
    description: str = ""


@dataclass
class Rubric:
    """A scoring rubric composed of weighted score components."""
    rubric_id: str
    name: str
    components: list[ScoreComponent] = field(default_factory=list)
    passing_threshold: float = 0.6

    def required_component_names(self) -> list[str]:
        return [c.name for c in self.components]

    def validate_scores(self, scores: dict[str, float]) -> list[str]:
        """Return list of validation errors (empty if valid)."""
        errors = []
        for comp in self.components:
            if comp.name not in scores:
                errors.append(f"Missing required score component: {comp.name}")
            else:
                val = scores[comp.name]
                if val < comp.min_score or val > comp.max_score:
                    errors.append(
                        f"Score '{comp.name}' = {val} out of range "
                        f"[{comp.min_score}, {comp.max_score}]"
                    )
        return errors

    def compute_weighted_score(self, scores: dict[str, float]) -> float:
        """Compute weighted average score."""
        total_weight = sum(c.weight for c in self.components)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(
            scores.get(c.name, 0.0) * c.weight for c in self.components
        )
        return weighted_sum / total_weight

    def passes(self, scores: dict[str, float]) -> bool:
        return self.compute_weighted_score(scores) >= self.passing_threshold


# --- Built-in rubrics ---

ACCURACY_RUBRIC = Rubric(
    rubric_id="accuracy",
    name="Accuracy Rubric",
    components=[
        ScoreComponent(name="correctness", weight=2.0, description="Factual correctness of answer"),
        ScoreComponent(name="completeness", weight=1.0, description="Coverage of required content"),
        ScoreComponent(name="relevance", weight=1.0, description="Relevance to the prompt"),
    ],
    passing_threshold=0.6,
)

REASONING_RUBRIC = Rubric(
    rubric_id="reasoning",
    name="Reasoning Rubric",
    components=[
        ScoreComponent(name="logical_coherence", weight=2.0, description="Logical consistency"),
        ScoreComponent(name="step_accuracy", weight=2.0, description="Correctness of reasoning steps"),
        ScoreComponent(name="conclusion_validity", weight=1.0, description="Final conclusion quality"),
    ],
    passing_threshold=0.5,
)

CODING_RUBRIC = Rubric(
    rubric_id="coding",
    name="Coding Rubric",
    components=[
        ScoreComponent(name="correctness", weight=3.0, description="Code produces correct output"),
        ScoreComponent(name="efficiency", weight=1.0, description="Algorithmic efficiency"),
        ScoreComponent(name="style", weight=0.5, description="Code clarity and style"),
    ],
    passing_threshold=0.5,
)

BUILTIN_RUBRICS: dict[str, Rubric] = {
    r.rubric_id: r for r in [ACCURACY_RUBRIC, REASONING_RUBRIC, CODING_RUBRIC]
}


def get_rubric(rubric_id: str) -> Rubric:
    if rubric_id not in BUILTIN_RUBRICS:
        raise KeyError(f"Unknown rubric: {rubric_id}")
    return BUILTIN_RUBRICS[rubric_id]
