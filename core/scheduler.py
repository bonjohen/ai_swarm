"""Scheduler — cron-based loop execution for automated graph runs.

Loads schedule configs from YAML, evaluates cron expressions, and
dispatches graph runs at the configured intervals.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ScheduleEntry:
    """A single scheduled job."""
    name: str
    graph: str          # "certification", "dossier", or "lab"
    scope_id: str       # cert_id, topic_id, or suite_id
    cron: str           # simplified cron: "daily", "weekly", "monthly", or "0 2 * * 1" style
    enabled: bool = True
    notify: list[str] = field(default_factory=list)  # notification hook names
    budget: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleConfig:
    """Full scheduler configuration."""
    entries: list[ScheduleEntry] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)


def load_schedule_config(path: Path | str) -> ScheduleConfig:
    """Load schedule configuration from a YAML file."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not raw:
        return ScheduleConfig()

    defaults = raw.get("defaults", {})
    entries = []
    for entry in raw.get("schedules", []):
        entries.append(ScheduleEntry(
            name=entry["name"],
            graph=entry["graph"],
            scope_id=entry["scope_id"],
            cron=entry.get("cron", "weekly"),
            enabled=entry.get("enabled", True),
            notify=entry.get("notify", defaults.get("notify", [])),
            budget=entry.get("budget", defaults.get("budget", {})),
        ))
    return ScheduleConfig(entries=entries, defaults=defaults)


# ---------------------------------------------------------------------------
# Cron expression evaluation (simplified)
# ---------------------------------------------------------------------------

# Supported shortcuts
_CRON_SHORTCUTS = {
    "daily": "0 0 * * *",
    "weekly": "0 0 * * 1",
    "monthly": "0 0 1 * *",
    "hourly": "0 * * * *",
}


def _parse_cron_field(field_str: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into a set of matching values."""
    if field_str == "*":
        return set(range(min_val, max_val + 1))

    values: set[int] = set()

    for part in field_str.split(","):
        # Handle step: */5 or 1-10/2
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            step = int(step_str)
            if range_part == "*":
                start, end = min_val, max_val
            elif "-" in range_part:
                start, end = (int(x) for x in range_part.split("-", 1))
            else:
                start = int(range_part)
                end = max_val
            values.update(range(start, end + 1, step))
        elif "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            values.update(range(start, end + 1))
        else:
            values.add(int(part))

    return values


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a datetime matches a cron expression.

    Format: minute hour day_of_month month day_of_week
    Supports: *, ranges (1-5), steps (*/15), lists (1,3,5), shortcuts.
    """
    expr = _CRON_SHORTCUTS.get(cron_expr, cron_expr)
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr!r} (need 5 fields)")

    minute, hour, dom, month, dow = parts

    if dt.minute not in _parse_cron_field(minute, 0, 59):
        return False
    if dt.hour not in _parse_cron_field(hour, 0, 23):
        return False
    if dt.day not in _parse_cron_field(dom, 1, 31):
        return False
    if dt.month not in _parse_cron_field(month, 1, 12):
        return False
    # 0 = Monday in Python, but cron uses 0 = Sunday. Convert.
    cron_dow = (dt.weekday() + 1) % 7  # Python Monday=0 → cron Sunday=0
    if cron_dow not in _parse_cron_field(dow, 0, 6):
        return False

    return True


def get_due_entries(config: ScheduleConfig, now: datetime | None = None) -> list[ScheduleEntry]:
    """Return schedule entries that are due to run at the given time."""
    if now is None:
        now = datetime.now(timezone.utc)
    return [
        entry for entry in config.entries
        if entry.enabled and cron_matches(entry.cron, now)
    ]


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

@dataclass
class SchedulerState:
    """Tracks scheduler execution state."""
    last_check: datetime | None = None
    runs_dispatched: int = 0
    errors: list[str] = field(default_factory=list)


def run_scheduler(
    config: ScheduleConfig,
    dispatch_fn: Callable[[ScheduleEntry], None],
    *,
    check_interval_seconds: int = 60,
    max_iterations: int = 0,
    on_error: Callable[[ScheduleEntry, Exception], None] | None = None,
) -> SchedulerState:
    """Run the scheduler loop.

    Args:
        config: Schedule configuration.
        dispatch_fn: Called for each due entry to execute the graph run.
        check_interval_seconds: How often to check for due entries.
        max_iterations: Stop after N iterations (0 = run forever).
        on_error: Optional error handler.

    Returns:
        SchedulerState with execution summary.
    """
    state = SchedulerState()
    iteration = 0

    while True:
        iteration += 1
        now = datetime.now(timezone.utc)
        state.last_check = now

        due = get_due_entries(config, now)
        for entry in due:
            try:
                logger.info("Dispatching scheduled run: %s (%s/%s)",
                            entry.name, entry.graph, entry.scope_id)
                dispatch_fn(entry)
                state.runs_dispatched += 1
            except Exception as exc:
                err_msg = f"Schedule '{entry.name}' failed: {exc}"
                logger.error(err_msg)
                state.errors.append(err_msg)
                if on_error:
                    on_error(entry, exc)

        if max_iterations and iteration >= max_iterations:
            break

        time.sleep(check_interval_seconds)

    return state
