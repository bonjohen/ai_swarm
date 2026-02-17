"""Tests for automation error handling and hardening."""

import json
import shutil
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from automation.config import AutomationConfig, PathsConfig
from automation.hardening import rebuild_queue, safe_move
from automation.queue import (
    QueueState,
    add_pending,
    load_queue,
    move_to_processing,
    save_queue,
)
from automation.watcher import watch_once

TASK_MD = textwrap.dedent("""\
    # TASK_ID: {task_id}
    # MODE: FAST
    # TASK_TYPE: REVIEW
    # PRIORITY: MEDIUM
    # OUTPUT_FORMAT: MARKDOWN
    # CREATED_AT: 2026-02-17T10:00:00

    ## CONTEXT
    Some context.
    ## CONSTRAINTS
    None.
    ## DELIVERABLE
    Something.
    ## SUCCESS CRITERIA
    It works.
""")

VALID_RESULT = textwrap.dedent("""\
    # RESULT_FOR: {task_id}
    # STATUS: COMPLETE
    # QUALITY_LEVEL: HIGH
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## OUTPUT
    Content.

    ## META
    ### Assumptions
    None.
    ### Risks
    None.
    ### Suggested_Followups
    None.
""")

MALFORMED_RESULT = "This is not a valid result file at all.\n"

MISMATCHED_RESULT = textwrap.dedent("""\
    # RESULT_FOR: nonexistent-task
    # STATUS: COMPLETE
    # QUALITY_LEVEL: HIGH
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## OUTPUT
    Content.

    ## META
    ### Assumptions
    None.
    ### Risks
    None.
    ### Suggested_Followups
    None.
""")

FAILED_RESULT = textwrap.dedent("""\
    # RESULT_FOR: {task_id}
    # STATUS: FAILED
    # QUALITY_LEVEL: LOW
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## ERROR
    Something went wrong.

    ## META
    ### Assumptions
    None.
    ### Risks
    None.
    ### Suggested_Followups
    None.
""")


def _cfg(tmp_path) -> AutomationConfig:
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


class TestMalformedResult:
    def test_malformed_result_triggers_failed(self, tmp_path):
        """Watcher marks task as FAILED when result file is malformed."""
        cfg = _cfg(tmp_path)
        task_id = "2026-02-17-001"

        # Put task in processing
        qp = Path(cfg.paths.base) / "queue.json"
        state = load_queue(qp)
        add_pending(state, task_id)
        move_to_processing(state, task_id)
        save_queue(qp, state)

        # Write malformed result
        (Path(cfg.paths.outputs) / f"{task_id}.result.md").write_text(MALFORMED_RESULT)

        watch_once(cfg)

        state = load_queue(qp)
        assert task_id in state.failed


class TestHeaderMismatch:
    def test_mismatch_is_skipped(self, tmp_path):
        """Watcher skips results whose RESULT_FOR doesn't match any processing task."""
        cfg = _cfg(tmp_path)

        # Write result for a task that isn't in processing
        (Path(cfg.paths.outputs) / "nonexistent-task.result.md").write_text(
            MISMATCHED_RESULT)

        processed = watch_once(cfg)
        assert processed == []


class TestRebuildQueue:
    def test_rebuild_from_filesystem(self, tmp_path):
        """rebuild_queue reconstructs state from directory contents."""
        cfg = _cfg(tmp_path)

        # Place files in various directories
        (Path(cfg.paths.tasks) / "2026-02-17-001.md").write_text(
            TASK_MD.format(task_id="2026-02-17-001"))
        (Path(cfg.paths.tasks) / "2026-02-17-002.md").write_text(
            TASK_MD.format(task_id="2026-02-17-002"))
        (Path(cfg.paths.processing) / "2026-02-17-003.md").write_text(
            TASK_MD.format(task_id="2026-02-17-003"))
        (Path(cfg.paths.archive) / "2026-02-17-004.md").write_text(
            TASK_MD.format(task_id="2026-02-17-004"))
        (Path(cfg.paths.outputs) / "2026-02-17-004.result.md").write_text(
            VALID_RESULT.format(task_id="2026-02-17-004"))
        (Path(cfg.paths.archive) / "2026-02-17-005.md").write_text(
            TASK_MD.format(task_id="2026-02-17-005"))
        (Path(cfg.paths.outputs) / "2026-02-17-005.result.md").write_text(
            FAILED_RESULT.format(task_id="2026-02-17-005"))

        # Corrupt queue.json
        qp = Path(cfg.paths.base) / "queue.json"
        qp.write_text("CORRUPTED")

        state = rebuild_queue(cfg)

        assert "2026-02-17-001" in state.pending
        assert "2026-02-17-002" in state.pending
        assert "2026-02-17-003" in state.processing
        assert "2026-02-17-004" in state.completed
        assert "2026-02-17-005" in state.failed

        # Verify it's persisted
        loaded = load_queue(qp)
        assert loaded.pending == state.pending


class TestSafeMove:
    def test_successful_move(self, tmp_path):
        src = tmp_path / "file.txt"
        src.write_text("hello")
        dst = tmp_path / "dest" / "file.txt"

        safe_move(src, dst)

        assert dst.exists()
        assert not src.exists()

    def test_retry_on_transient_failure(self, tmp_path):
        src = tmp_path / "file.txt"
        src.write_text("hello")
        dst = tmp_path / "dest" / "file.txt"

        call_count = 0
        original_move = shutil.move

        def flaky_move(s, d):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("transient failure")
            return original_move(s, d)

        with patch("automation.hardening.shutil.move", side_effect=flaky_move):
            safe_move(src, dst, retries=1, delay=0.01)

        assert dst.exists()
        assert call_count == 2

    def test_raises_after_all_retries(self, tmp_path):
        src = tmp_path / "file.txt"
        src.write_text("hello")
        dst = tmp_path / "dest" / "file.txt"

        def always_fail(s, d):
            raise OSError("permanent failure")

        with patch("automation.hardening.shutil.move", side_effect=always_fail):
            with pytest.raises(OSError, match="permanent failure"):
                safe_move(src, dst, retries=1, delay=0.01)


class TestConcurrentAccess:
    def test_atomic_queue_write_no_corruption(self, tmp_path):
        """Multiple sequential queue operations don't corrupt state."""
        cfg = _cfg(tmp_path)
        qp = Path(cfg.paths.base) / "queue.json"

        for i in range(20):
            state = load_queue(qp)
            add_pending(state, f"task-{i:03d}")
            save_queue(qp, state)

        state = load_queue(qp)
        assert len(state.pending) == 20
        # Verify JSON is well-formed
        data = json.loads(qp.read_text())
        assert len(data["pending"]) == 20
