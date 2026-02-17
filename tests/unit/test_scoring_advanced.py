"""Tests for scoring improvements — expanded rubrics, category mapping, baseline comparison."""

import pytest

from eval.rubrics import (
    BUILTIN_RUBRICS,
    CATEGORY_RUBRICS,
    Rubric,
    ScoreComponent,
    get_rubric,
    get_rubric_for_category,
    register_rubric,
)
from eval.scoring import (
    BaselineComparison,
    ScoreResult,
    compare_to_baseline,
    score_response,
)


class TestExpandedRubrics:
    def test_six_builtin_rubrics(self):
        assert len(BUILTIN_RUBRICS) == 6
        expected = {"accuracy", "reasoning", "coding", "summarization",
                    "instruction_following", "safety"}
        assert set(BUILTIN_RUBRICS.keys()) == expected

    def test_summarization_rubric(self):
        rubric = get_rubric("summarization")
        names = rubric.required_component_names()
        assert "coverage" in names
        assert "faithfulness" in names

    def test_instruction_following_rubric(self):
        rubric = get_rubric("instruction_following")
        names = rubric.required_component_names()
        assert "format_compliance" in names
        assert "constraint_adherence" in names

    def test_safety_rubric(self):
        rubric = get_rubric("safety")
        assert rubric.passing_threshold == 0.8  # Higher bar for safety
        names = rubric.required_component_names()
        assert "harmlessness" in names


class TestCategoryMapping:
    def test_known_categories(self):
        for cat in ("summarization", "reasoning", "coding", "accuracy",
                     "instruction_following", "safety"):
            rubric = get_rubric_for_category(cat)
            assert rubric.rubric_id is not None

    def test_unknown_category_falls_back_to_accuracy(self):
        rubric = get_rubric_for_category("unknown_category")
        assert rubric.rubric_id == "accuracy"


class TestCustomRubric:
    def test_register_and_retrieve(self):
        custom = Rubric(
            rubric_id="custom_test",
            name="Custom Test Rubric",
            components=[
                ScoreComponent(name="dim_a", weight=1.0),
                ScoreComponent(name="dim_b", weight=1.0),
            ],
        )
        register_rubric(custom)
        retrieved = get_rubric("custom_test")
        assert retrieved.name == "Custom Test Rubric"
        # Clean up
        del BUILTIN_RUBRICS["custom_test"]


class TestBaselineComparison:
    def _make_results(self, scores: list[float]) -> list[ScoreResult]:
        return [
            ScoreResult(
                task_id=f"t{i}", model_id="model-a",
                scores_json={}, weighted_score=s, passed=s >= 0.5,
            )
            for i, s in enumerate(scores)
        ]

    def test_improved(self):
        current = self._make_results([0.8, 0.9, 0.85])
        baseline = self._make_results([0.5, 0.6, 0.55])
        comp = compare_to_baseline(current, baseline)
        assert comp.direction == "improved"
        assert comp.delta > 0
        assert comp.current_avg > comp.baseline_avg

    def test_regressed(self):
        current = self._make_results([0.3, 0.4, 0.35])
        baseline = self._make_results([0.7, 0.8, 0.75])
        comp = compare_to_baseline(current, baseline)
        assert comp.direction == "regressed"
        assert comp.delta < 0

    def test_unchanged(self):
        current = self._make_results([0.5, 0.5, 0.5])
        baseline = self._make_results([0.5, 0.5, 0.5])
        comp = compare_to_baseline(current, baseline)
        assert comp.direction == "unchanged"
        assert abs(comp.delta) < 0.001

    def test_statistical_significance_large_difference(self):
        current = self._make_results([0.9, 0.85, 0.95, 0.88, 0.92])
        baseline = self._make_results([0.3, 0.35, 0.25, 0.28, 0.32])
        comp = compare_to_baseline(current, baseline)
        assert comp.significant is True
        assert comp.p_value < 0.05

    def test_no_significance_small_difference(self):
        current = self._make_results([0.51, 0.49, 0.50])
        baseline = self._make_results([0.50, 0.50, 0.50])
        comp = compare_to_baseline(current, baseline)
        # Small difference, likely not significant
        assert comp.p_value is not None

    def test_empty_results(self):
        comp = compare_to_baseline([], [])
        assert comp.direction == "unchanged"
        assert comp.p_value is None

    def test_relative_change(self):
        current = self._make_results([0.6, 0.6, 0.6])
        baseline = self._make_results([0.5, 0.5, 0.5])
        comp = compare_to_baseline(current, baseline)
        # 0.1 / 0.5 = 0.2 = 20% improvement
        assert abs(comp.relative_change - 0.2) < 0.01
