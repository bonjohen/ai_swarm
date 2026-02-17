"""Lab task definitions — prompt templates, golden answers, rubric references."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LabTask:
    """A single benchmark task definition."""
    task_id: str
    category: str
    prompt_template: str
    golden: dict[str, Any] = field(default_factory=dict)
    rubric_id: str = "accuracy"
    variables: dict[str, Any] = field(default_factory=dict)

    def render_prompt(self, **kwargs: Any) -> str:
        """Fill in prompt template variables."""
        merged = {**self.variables, **kwargs}
        return self.prompt_template.format(**merged)


@dataclass
class TaskSuite:
    """A collection of tasks to run as a benchmark suite."""
    suite_id: str
    name: str
    tasks: list[LabTask] = field(default_factory=list)
    model_ids: list[str] = field(default_factory=list)
    hw_id: str = ""

    def get_task(self, task_id: str) -> LabTask:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        raise KeyError(f"Task not found in suite '{self.suite_id}': {task_id}")


# --- Built-in example tasks ---

SUMMARIZATION_TASK = LabTask(
    task_id="summarize-1",
    category="summarization",
    prompt_template="Summarize the following text in 2-3 sentences:\n\n{text}",
    golden={"key_points": ["main idea", "supporting detail"]},
    rubric_id="accuracy",
)

REASONING_TASK = LabTask(
    task_id="reason-1",
    category="reasoning",
    prompt_template="Solve step by step: {problem}",
    golden={"answer": "{expected_answer}"},
    rubric_id="reasoning",
)

CODING_TASK = LabTask(
    task_id="code-1",
    category="coding",
    prompt_template="Write a Python function that {task_description}.\nInclude type hints.",
    golden={"test_cases": []},
    rubric_id="coding",
)

BUILTIN_TASKS: dict[str, LabTask] = {
    t.task_id: t for t in [SUMMARIZATION_TASK, REASONING_TASK, CODING_TASK]
}
