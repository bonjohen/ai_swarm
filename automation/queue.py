"""Queue state — JSON-persisted task queue with atomic writes.

Tracks task IDs across pending / processing / completed / failed lists
and optional parent linkage for chained tasks.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QueueState:
    """In-memory representation of the task queue."""
    pending: list[str] = field(default_factory=list)
    processing: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    parents: dict[str, str] = field(default_factory=dict)


def load_queue(path: str | Path) -> QueueState:
    """Load queue state from a JSON file."""
    path = Path(path)
    raw = json.loads(path.read_text())
    return QueueState(
        pending=raw.get("pending", []),
        processing=raw.get("processing", []),
        completed=raw.get("completed", []),
        failed=raw.get("failed", []),
        parents=raw.get("parents", {}),
    )


def save_queue(path: str | Path, state: QueueState) -> None:
    """Atomically persist queue state to a JSON file.

    Writes to a temporary file first, then uses ``os.replace()``
    so readers never see a partial write.
    """
    path = Path(path)
    tmp_path = path.with_suffix(".tmp")
    data = {
        "pending": state.pending,
        "processing": state.processing,
        "completed": state.completed,
        "failed": state.failed,
        "parents": state.parents,
    }
    tmp_path.write_text(json.dumps(data, indent=2))
    os.replace(tmp_path, path)


def add_pending(state: QueueState, task_id: str) -> None:
    """Add a task to the pending list.  Raises if already present anywhere."""
    _assert_not_present(state, task_id)
    state.pending.append(task_id)


def move_to_processing(state: QueueState, task_id: str) -> None:
    """Move a task from pending to processing."""
    _remove_from(state.pending, task_id, "pending")
    state.processing.append(task_id)


def move_to_completed(state: QueueState, task_id: str) -> None:
    """Move a task from processing to completed."""
    _remove_from(state.processing, task_id, "processing")
    state.completed.append(task_id)


def move_to_failed(state: QueueState, task_id: str) -> None:
    """Move a task from processing to failed."""
    _remove_from(state.processing, task_id, "processing")
    state.failed.append(task_id)


def link_parent(state: QueueState, task_id: str, parent_id: str) -> None:
    """Record a parent relationship for chained tasks."""
    state.parents[task_id] = parent_id


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _all_ids(state: QueueState) -> list[str]:
    return state.pending + state.processing + state.completed + state.failed


def _assert_not_present(state: QueueState, task_id: str) -> None:
    if task_id in _all_ids(state):
        raise ValueError(f"Task {task_id!r} already exists in the queue")


def _remove_from(lst: list[str], task_id: str, list_name: str) -> None:
    try:
        lst.remove(task_id)
    except ValueError:
        raise ValueError(
            f"Task {task_id!r} not found in {list_name}"
        ) from None
