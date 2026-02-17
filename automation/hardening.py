"""Hardening — error recovery utilities for the automation bridge.

Provides queue rebuild from filesystem state and retried file moves.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from automation.config import AutomationConfig
from automation.logging import log_event
from automation.queue import QueueState, save_queue

logger = logging.getLogger(__name__)


def rebuild_queue(cfg: AutomationConfig) -> QueueState:
    """Rebuild queue.json from the filesystem directory state.

    Scans tasks/, processing/, outputs/, and archive/ to reconstruct
    which task IDs belong in which queue list.
    """
    pending: list[str] = []
    processing: list[str] = []
    completed: list[str] = []
    failed: list[str] = []

    tasks_dir = Path(cfg.paths.tasks)
    processing_dir = Path(cfg.paths.processing)
    outputs_dir = Path(cfg.paths.outputs)
    archive_dir = Path(cfg.paths.archive)

    # Tasks in tasks/ → pending
    if tasks_dir.exists():
        for f in sorted(tasks_dir.glob("*.md")):
            pending.append(f.stem)

    # Tasks in processing/ → processing
    if processing_dir.exists():
        for f in sorted(processing_dir.glob("*.md")):
            processing.append(f.stem)

    # Completed results in outputs/
    completed_ids: set[str] = set()
    failed_ids: set[str] = set()
    if outputs_dir.exists():
        for f in sorted(outputs_dir.glob("*.result.md")):
            # Extract task_id from filename: <task_id>.result.md
            task_id = f.name.replace(".result.md", "")
            # Read STATUS header to determine completed vs failed
            try:
                text = f.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if line.startswith("# STATUS:"):
                        status = line.split(":", 1)[1].strip()
                        if status == "FAILED":
                            failed_ids.add(task_id)
                        else:
                            completed_ids.add(task_id)
                        break
            except OSError:
                failed_ids.add(task_id)

    # Tasks in archive/ with results → completed/failed; without → completed
    if archive_dir.exists():
        for f in sorted(archive_dir.glob("*.md")):
            tid = f.stem
            if tid in failed_ids:
                if tid not in failed:
                    failed.append(tid)
            elif tid not in completed:
                completed.append(tid)

    # Also add result-only completed/failed that aren't in archive
    for tid in completed_ids:
        if tid not in completed and tid not in processing:
            completed.append(tid)
    for tid in failed_ids:
        if tid not in failed and tid not in processing:
            failed.append(tid)

    state = QueueState(
        pending=pending,
        processing=processing,
        completed=completed,
        failed=failed,
    )

    queue_path = Path(cfg.paths.base) / "queue.json"
    save_queue(queue_path, state)

    log_event(cfg, action="task_processing", status="ok",
              details=f"Queue rebuilt: {len(pending)} pending, {len(processing)} processing, "
                      f"{len(completed)} completed, {len(failed)} failed")

    return state


def safe_move(src: Path, dst: Path, *, retries: int = 1, delay: float = 0.5) -> None:
    """Move a file with retry on failure.

    Args:
        src: Source path.
        dst: Destination path.
        retries: Number of retries after initial failure.
        delay: Seconds to wait between attempts.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None

    for attempt in range(1 + retries):
        try:
            shutil.move(str(src), str(dst))
            return
        except OSError as exc:
            last_exc = exc
            logger.warning("File move failed (attempt %d/%d): %s -> %s: %s",
                           attempt + 1, 1 + retries, src, dst, exc)
            if attempt < retries:
                time.sleep(delay)

    raise last_exc  # type: ignore[misc]
