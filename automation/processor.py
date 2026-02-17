"""Task processor — pick, start, complete, and fail tasks.

Manages the lifecycle of moving task files between directories and
updating queue state.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from automation.config import AutomationConfig
from automation.queue import (
    load_queue,
    move_to_completed,
    move_to_failed,
    move_to_processing,
    save_queue,
)
from automation.logging import log_event
from automation.result_writer import write_result
from automation.task_schema import PRIORITIES, TaskFile, parse_task_file

logger = logging.getLogger(__name__)

_PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _queue_path(cfg: AutomationConfig) -> Path:
    return Path(cfg.paths.base) / "queue.json"


def pick_next_task(cfg: AutomationConfig) -> TaskFile | None:
    """Return the highest-priority pending task, or ``None``."""
    state = load_queue(_queue_path(cfg))
    if not state.pending:
        return None

    tasks_dir = Path(cfg.paths.tasks)
    candidates: list[tuple[int, str, TaskFile]] = []

    for tid in state.pending:
        path = tasks_dir / f"{tid}.md"
        if not path.exists():
            continue
        try:
            task = parse_task_file(path)
            prio = _PRIORITY_ORDER.get(task.header.priority, 99)
            candidates.append((prio, tid, task))
        except (ValueError, OSError):
            logger.warning("Skipping unparseable task: %s", tid)

    if not candidates:
        return None

    candidates.sort(key=lambda t: t[0])
    return candidates[0][2]


def start_processing(cfg: AutomationConfig, task_id: str) -> None:
    """Move a task from ``tasks/`` to ``processing/`` and update queue."""
    src = Path(cfg.paths.tasks) / f"{task_id}.md"
    dst_dir = Path(cfg.paths.processing)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{task_id}.md"

    shutil.move(str(src), str(dst))

    state = load_queue(_queue_path(cfg))
    move_to_processing(state, task_id)
    save_queue(_queue_path(cfg), state)

    log_event(cfg, action="task_processing", task_id=task_id)


def complete_processing(
    cfg: AutomationConfig,
    task_id: str,
    result_content: str,
    quality_level: str = "MEDIUM",
    meta: dict[str, str] | None = None,
) -> Path:
    """Write a COMPLETE result, archive the task, and update queue."""
    meta = meta or {
        "assumptions": "None specified.",
        "risks": "None specified.",
        "suggested_followups": "None specified.",
    }

    outputs_dir = Path(cfg.paths.outputs)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    result_path = write_result(
        output_dir=outputs_dir,
        task_id=task_id,
        status="COMPLETE",
        quality_level=quality_level,
        output=result_content,
        meta=meta,
    )

    # Move task to archive
    _archive_task(cfg, task_id)

    # Update queue
    state = load_queue(_queue_path(cfg))
    move_to_completed(state, task_id)
    save_queue(_queue_path(cfg), state)

    log_event(cfg, action="task_completed", task_id=task_id)

    return result_path


def fail_processing(
    cfg: AutomationConfig,
    task_id: str,
    error_reason: str,
    meta: dict[str, str] | None = None,
) -> Path:
    """Write a FAILED result, archive the task, and update queue."""
    meta = meta or {
        "assumptions": "None specified.",
        "risks": "None specified.",
        "suggested_followups": "None specified.",
    }

    outputs_dir = Path(cfg.paths.outputs)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    result_path = write_result(
        output_dir=outputs_dir,
        task_id=task_id,
        status="FAILED",
        quality_level="LOW",
        output="",
        meta=meta,
        error=error_reason,
    )

    # Move task to archive
    _archive_task(cfg, task_id)

    # Update queue
    state = load_queue(_queue_path(cfg))
    move_to_failed(state, task_id)
    save_queue(_queue_path(cfg), state)

    log_event(cfg, action="task_failed", task_id=task_id, status="failed",
              details=error_reason)

    return result_path


def _archive_task(cfg: AutomationConfig, task_id: str) -> None:
    """Move the task file from processing/ to archive/."""
    src = Path(cfg.paths.processing) / f"{task_id}.md"
    if not src.exists():
        return
    archive_dir = Path(cfg.paths.archive)
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(archive_dir / f"{task_id}.md"))
