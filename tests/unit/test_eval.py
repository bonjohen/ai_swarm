"""Tests for eval framework — rubrics, lab_tasks, scoring."""

import pytest

from eval.rubrics import (
    ACCURACY_RUBRIC,
    REASONING_RUBRIC,
    CODING_RUBRIC,
    Rubric,
    ScoreComponent,
    get_rubric,
)
from eval.lab_tasks import LabTask, TaskSuite, SUMMARIZATION_TASK
from eval.scoring import score_response, score_suite, aggregate_scores


# --- Rubric tests ---

class TestRubrics:
    def test_accuracy_rubric_components(self):
        names = ACCURACY_RUBRIC.required_component_names()
        assert "correctness" in names
        assert "completeness" in names
        assert "relevance" in names

    def test_validate_scores_pass(self):
        scores = {"correctness": 0.8, "completeness": 0.7, "relevance": 0.9}
        errors = ACCURACY_RUBRIC.validate_scores(scores)
        assert errors == []

    def test_validate_scores_missing(self):
        errors = ACCURACY_RUBRIC.validate_scores({"correctness": 0.8})
        assert len(errors) == 2  # missing completeness and relevance

    def test_validate_scores_out_of_range(self):
        scores = {"correctness": 1.5, "completeness": 0.5, "relevance": 0.5}
        errors = ACCURACY_RUBRIC.validate_scores(scores)
        assert any("out of range" in e for e in errors)

    def test_weighted_score(self):
        # correctness weight=2, completeness weight=1, relevance weight=1
        scores = {"correctness": 1.0, "completeness": 0.5, "relevance": 0.5}
        # weighted = (1.0*2 + 0.5*1 + 0.5*1) / 4 = 3.0/4 = 0.75
        assert ACCURACY_RUBRIC.compute_weighted_score(scores) == 0.75

    def test_passes(self):
        assert ACCURACY_RUBRIC.passes({"correctness": 0.8, "completeness": 0.7, "relevance": 0.6})

    def test_fails(self):
        assert not ACCURACY_RUBRIC.passes({"correctness": 0.2, "completeness": 0.1, "relevance": 0.1})

    def test_get_rubric(self):
        assert get_rubric("accuracy") is ACCURACY_RUBRIC
        assert get_rubric("reasoning") is REASONING_RUBRIC

    def test_get_rubric_unknown(self):
        with pytest.raises(KeyError, match="Unknown rubric"):
            get_rubric("nonexistent")


# --- Lab task tests ---

class TestLabTasks:
    def test_render_prompt(self):
        prompt = SUMMARIZATION_TASK.render_prompt(text="Hello world.")
        assert "Hello world." in prompt

    def test_task_suite(self):
        suite = TaskSuite(
            suite_id="test-suite", name="Test",
            tasks=[SUMMARIZATION_TASK],
            model_ids=["model-a"],
        )
        assert suite.get_task("summarize-1") is SUMMARIZATION_TASK

    def test_task_suite_missing(self):
        suite = TaskSuite(suite_id="s", name="S", tasks=[])
        with pytest.raises(KeyError, match="Task not found"):
            suite.get_task("nope")


# --- Scoring tests ---

class TestScoring:
    def test_score_response_pass(self):
        result = score_response(
            task_id="t1", model_id="m1", rubric_id="accuracy",
            component_scores={"correctness": 0.9, "completeness": 0.8, "relevance": 0.7},
        )
        assert result.passed
        assert result.weighted_score > 0.6
        assert result.task_id == "t1"

    def test_score_response_fail(self):
        result = score_response(
            task_id="t1", model_id="m1", rubric_id="accuracy",
            component_scores={"correctness": 0.1, "completeness": 0.1, "relevance": 0.1},
        )
        assert not result.passed

    def test_score_response_zero_fail_mode(self):
        result = score_response(
            task_id="t1", model_id="m1", rubric_id="accuracy",
            component_scores={"correctness": 0.0, "completeness": 0.5, "relevance": 0.5},
        )
        assert "zero_score:correctness" in result.fail_modes

    def test_score_determinism(self):
        kwargs = dict(
            task_id="t1", model_id="m1", rubric_id="accuracy",
            component_scores={"correctness": 0.8, "completeness": 0.7, "relevance": 0.6},
        )
        r1 = score_response(**kwargs)
        r2 = score_response(**kwargs)
        assert r1.weighted_score == r2.weighted_score
        assert r1.passed == r2.passed

    def test_score_suite(self):
        results = [
            {"task_id": "t1", "model_id": "m1", "component_scores": {"correctness": 0.9, "completeness": 0.8, "relevance": 0.7}},
            {"task_id": "t2", "model_id": "m1", "component_scores": {"correctness": 0.3, "completeness": 0.2, "relevance": 0.1}},
        ]
        scored = score_suite(results, rubric_id="accuracy")
        assert len(scored) == 2
        assert scored[0].passed
        assert not scored[1].passed

    def test_aggregate_scores(self):
        results = score_suite([
            {"task_id": "t1", "model_id": "m1", "component_scores": {"correctness": 0.9, "completeness": 0.8, "relevance": 0.7}},
            {"task_id": "t2", "model_id": "m1", "component_scores": {"correctness": 0.3, "completeness": 0.2, "relevance": 0.1}},
        ], rubric_id="accuracy")
        agg = aggregate_scores(results)
        assert agg["count"] == 2
        assert agg["pass_count"] == 1
        assert agg["fail_count"] == 1
        assert 0 < agg["avg_score"] < 1
        assert 0 < agg["pass_rate"] < 1

    def test_aggregate_empty(self):
        agg = aggregate_scores([])
        assert agg["count"] == 0
