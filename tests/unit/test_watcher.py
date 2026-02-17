"""Tests for the automation watcher service."""

import json
import textwrap
from pathlib import Path

import pytest

from automation.config import AutomationConfig, PathsConfig
from automation.queue import QueueState, add_pending, load_queue, move_to_processing, save_queue
from automation.watcher import watch_once

VALID_RESULT = textwrap.dedent("""\
    # RESULT_FOR: {task_id}
    # STATUS: COMPLETE
    # QUALITY_LEVEL: HIGH
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## OUTPUT

    Deliverable content.

    ## META

    ### Assumptions

    None.

    ### Risks

    None.

    ### Suggested_Followups

    None.
""")

INVALID_RESULT = textwrap.dedent("""\
    # RESULT_FOR: {task_id}
    # STATUS: COMPLETE
    # COMPLETED_AT: 2026-02-17T12:00:00
""")


def _setup(tmp_path) -> AutomationConfig:
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
        Path(d).mkdir(parents=True, exist_ok=True)
    save_queue(tmp_path / "auto" / "queue.json", QueueState())
    return cfg


def _add_processing_task(cfg, task_id):
    """Add a task directly to the processing list."""
    qp = Path(cfg.paths.base) / "queue.json"
    state = load_queue(qp)
    add_pending(state, task_id)
    move_to_processing(state, task_id)
    save_queue(qp, state)


class TestWatchOnce:
    def test_detects_new_result_and_completes(self, tmp_path):
        cfg = _setup(tmp_path)
        task_id = "2026-02-17-001"
        _add_processing_task(cfg, task_id)

        # Write valid result
        result_path = Path(cfg.paths.outputs) / f"{task_id}.result.md"
        result_path.write_text(VALID_RESULT.format(task_id=task_id))

        processed = watch_once(cfg)

        assert task_id in processed
        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert task_id in state.completed
        assert task_id not in state.processing

    def test_marks_failed_on_validation_error(self, tmp_path):
        cfg = _setup(tmp_path)
        task_id = "2026-02-17-002"
        _add_processing_task(cfg, task_id)

        # Write invalid result (missing QUALITY_LEVEL, OUTPUT, META)
        result_path = Path(cfg.paths.outputs) / f"{task_id}.result.md"
        result_path.write_text(INVALID_RESULT.format(task_id=task_id))

        processed = watch_once(cfg)

        assert task_id in processed
        state = load_queue(Path(cfg.paths.base) / "queue.json")
        assert task_id in state.failed
        assert task_id not in state.processing

    def test_ignores_already_processed(self, tmp_path):
        cfg = _setup(tmp_path)
        task_id = "2026-02-17-003"
        _add_processing_task(cfg, task_id)

        result_path = Path(cfg.paths.outputs) / f"{task_id}.result.md"
        result_path.write_text(VALID_RESULT.format(task_id=task_id))

        # First poll picks it up
        first = watch_once(cfg)
        assert task_id in first

        # Second poll skips it
        second = watch_once(cfg)
        assert task_id not in second

    def test_logs_structured_entries(self, tmp_path):
        cfg = _setup(tmp_path)
        task_id = "2026-02-17-004"
        _add_processing_task(cfg, task_id)

        result_path = Path(cfg.paths.outputs) / f"{task_id}.result.md"
        result_path.write_text(VALID_RESULT.format(task_id=task_id))

        watch_once(cfg)

        log_path = Path(cfg.paths.logs) / "system.log"
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        entries = [json.loads(line) for line in lines]

        actions = [e["action"] for e in entries]
        assert "task_completed" in actions
        assert "watcher_poll" in actions

        # Each entry has required fields
        for entry in entries:
            assert "timestamp" in entry
            assert "action" in entry
            assert "status" in entry
