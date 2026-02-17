"""Tests for the automation task processor and result writer."""

import textwrap

import pytest

from automation.config import AutomationConfig, PathsConfig
from automation.processor import (
    complete_processing,
    fail_processing,
    pick_next_task,
    start_processing,
)
from automation.queue import QueueState, add_pending, load_queue, save_queue
from automation.result_writer import write_result
from automation.validator import validate_result


def _setup(tmp_path) -> AutomationConfig:
    """Create directory structure and return config pointing at tmp_path."""
    paths = PathsConfig(
        base=str(tmp_path / "auto"),
        tasks=str(tmp_path / "auto" / "tasks"),
        processing=str(tmp_path / "auto" / "processing"),
        outputs=str(tmp_path / "auto" / "outputs"),
        archive=str(tmp_path / "auto" / "archive"),
        logs=str(tmp_path / "auto" / "logs"),
        schemas=str(tmp_path / "auto" / "schemas"),
    )
    cfg = AutomationConfig(paths=paths)

    for d in [paths.base, paths.tasks, paths.processing, paths.outputs,
              paths.archive, paths.logs, paths.schemas]:
        (tmp_path / d) if d.startswith(str(tmp_path)) else None
        from pathlib import Path
        Path(d).mkdir(parents=True, exist_ok=True)

    save_queue(tmp_path / "auto" / "queue.json", QueueState())
    return cfg


TASK_TEMPLATE = textwrap.dedent("""\
    # TASK_ID: {task_id}
    # MODE: PREMIUM
    # TASK_TYPE: ARCHITECTURE
    # PRIORITY: {priority}
    # OUTPUT_FORMAT: MARKDOWN
    # CREATED_AT: 2026-02-17T10:00:00

    ## CONTEXT

    Some context.

    ## CONSTRAINTS

    Some constraints.

    ## DELIVERABLE

    Some deliverable.

    ## SUCCESS CRITERIA

    Some criteria.
""")


def _create_task(cfg, task_id, priority="MEDIUM"):
    """Write a task file and add it to the queue."""
    from pathlib import Path
    path = Path(cfg.paths.tasks) / f"{task_id}.md"
    path.write_text(TASK_TEMPLATE.format(task_id=task_id, priority=priority))

    qp = Path(cfg.paths.base) / "queue.json"
    state = load_queue(qp)
    add_pending(state, task_id)
    save_queue(qp, state)


class TestPickNextTask:
    def test_returns_highest_priority(self, tmp_path):
        cfg = _setup(tmp_path)
        _create_task(cfg, "2026-02-17-001", priority="LOW")
        _create_task(cfg, "2026-02-17-002", priority="HIGH")
        _create_task(cfg, "2026-02-17-003", priority="MEDIUM")

        task = pick_next_task(cfg)
        assert task is not None
        assert task.header.task_id == "2026-02-17-002"

    def test_returns_none_when_empty(self, tmp_path):
        cfg = _setup(tmp_path)
        assert pick_next_task(cfg) is None


class TestStartProcessing:
    def test_moves_file_and_updates_queue(self, tmp_path):
        cfg = _setup(tmp_path)
        _create_task(cfg, "2026-02-17-001")

        start_processing(cfg, "2026-02-17-001")

        from pathlib import Path
        assert not (Path(cfg.paths.tasks) / "2026-02-17-001.md").exists()
        assert (Path(cfg.paths.processing) / "2026-02-17-001.md").exists()

        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert "2026-02-17-001" not in state.pending
        assert "2026-02-17-001" in state.processing


class TestCompleteProcessing:
    def test_writes_result_and_archives(self, tmp_path):
        cfg = _setup(tmp_path)
        _create_task(cfg, "2026-02-17-001")
        start_processing(cfg, "2026-02-17-001")

        result_path = complete_processing(
            cfg, "2026-02-17-001", "Here is the output.",
            quality_level="HIGH",
            meta={
                "assumptions": "Assumed single-tenant.",
                "risks": "None.",
                "suggested_followups": "Deploy.",
            },
        )

        from pathlib import Path
        assert result_path.exists()
        assert "2026-02-17-001.result.md" in result_path.name

        # Validate result file
        errors = validate_result(result_path)
        assert errors == [], f"Validation errors: {errors}"

        # Task archived
        assert (Path(cfg.paths.archive) / "2026-02-17-001.md").exists()

        # Queue updated
        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert "2026-02-17-001" in state.completed
        assert "2026-02-17-001" not in state.processing


class TestFailProcessing:
    def test_writes_failed_result_with_error(self, tmp_path):
        cfg = _setup(tmp_path)
        _create_task(cfg, "2026-02-17-001")
        start_processing(cfg, "2026-02-17-001")

        result_path = fail_processing(
            cfg, "2026-02-17-001", "Insufficient context.",
        )

        from pathlib import Path
        assert result_path.exists()

        # Validate result file
        errors = validate_result(result_path)
        assert errors == [], f"Validation errors: {errors}"

        # Result has ERROR section
        text = result_path.read_text()
        assert "## ERROR" in text
        assert "Insufficient context." in text

        # Queue updated
        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert "2026-02-17-001" in state.failed


class TestWriteResult:
    def test_produces_valid_result(self, tmp_path):
        result_path = write_result(
            output_dir=tmp_path,
            task_id="2026-02-17-001",
            status="COMPLETE",
            quality_level="MEDIUM",
            output="Deliverable content here.",
            meta={
                "assumptions": "None.",
                "risks": "None.",
                "suggested_followups": "None.",
            },
        )

        errors = validate_result(result_path)
        assert errors == [], f"Validation errors: {errors}"


class TestFullLifecycle:
    def test_create_process_complete_archive(self, tmp_path):
        cfg = _setup(tmp_path)

        # 1. Create
        _create_task(cfg, "2026-02-17-001", priority="HIGH")

        from pathlib import Path
        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert "2026-02-17-001" in state.pending

        # 2. Pick
        task = pick_next_task(cfg)
        assert task.header.task_id == "2026-02-17-001"

        # 3. Start processing
        start_processing(cfg, "2026-02-17-001")
        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert "2026-02-17-001" in state.processing

        # 4. Complete
        result_path = complete_processing(
            cfg, "2026-02-17-001", "Final output.",
        )
        assert result_path.exists()
        assert validate_result(result_path) == []

        # 5. Verify final state
        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert "2026-02-17-001" in state.completed
        assert (Path(cfg.paths.archive) / "2026-02-17-001.md").exists()
