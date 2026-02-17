"""Structured logging for the automation bridge.

Writes one JSON object per line to ``automation/logs/system.log``.
Each entry carries: ``timestamp``, ``task_id``, ``action``, ``status``,
``details``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from automation.config import AutomationConfig

# Recognised action verbs
ACTIONS = {
    "task_created",
    "task_processing",
    "task_completed",
    "task_failed",
    "task_archived",
    "validation_passed",
    "validation_failed",
    "watcher_poll",
}


def log_path(cfg: AutomationConfig) -> Path:
    """Return the path to the structured log file, creating dirs if needed."""
    logs_dir = Path(cfg.paths.logs)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "system.log"


def log_event(
    cfg: AutomationConfig,
    *,
    action: str,
    status: str = "ok",
    task_id: str = "",
    details: str = "",
) -> dict:
    """Append a structured log entry and return it.

    Args:
        cfg: Automation configuration (for log path).
        action: One of the recognised action verbs.
        status: ``ok``, ``failed``, ``warning``, etc.
        task_id: Related task ID (empty string if N/A).
        details: Free-text description.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "task_id": task_id,
        "action": action,
        "status": status,
        "details": details,
    }
    with open(log_path(cfg), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def read_log(cfg: AutomationConfig) -> list[dict]:
    """Read all log entries from the structured log file."""
    lp = log_path(cfg)
    if not lp.exists():
        return []
    entries = []
    for line in lp.read_text(encoding="utf-8").strip().splitlines():
        if line:
            entries.append(json.loads(line))
    return entries
