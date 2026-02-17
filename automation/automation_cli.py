"""CLI entrypoint: automation task management.

Usage: python -m automation.automation_cli <subcommand> [options]

Subcommands: create, list, validate, archive, status
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from automation.config import AutomationConfig, default_config, load_config
from automation.queue import (
    QueueState,
    add_pending,
    link_parent,
    load_queue,
    move_to_completed,
    move_to_failed,
    save_queue,
)
from automation.task_schema import (
    MODES,
    OUTPUT_FORMATS,
    PRIORITIES,
    TASK_TYPES,
    generate_task_id,
    parse_task_file,
)
from automation.logging import log_event
from automation.validator import validate_result, validate_task

logger = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_cfg(args: argparse.Namespace) -> AutomationConfig:
    cfg_path = Path(args.config)
    if cfg_path.exists():
        return load_config(cfg_path)
    return default_config()


def _queue_path(cfg: AutomationConfig) -> Path:
    return Path(cfg.paths.base) / "queue.json"


def _load_queue_state(cfg: AutomationConfig) -> QueueState:
    qp = _queue_path(cfg)
    if qp.exists():
        return load_queue(qp)
    return QueueState()


def _save_queue_state(cfg: AutomationConfig, state: QueueState) -> None:
    save_queue(_queue_path(cfg), state)


def _find_task_file(cfg: AutomationConfig, task_id: str) -> Path | None:
    """Search tasks/, processing/, archive/ for a task file."""
    for subdir in (cfg.paths.tasks, cfg.paths.processing, cfg.paths.archive):
        p = Path(subdir) / f"{task_id}.md"
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    tasks_dir = Path(cfg.paths.tasks)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    task_id = generate_task_id(tasks_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    parent_line = ""
    if args.parent:
        parent_line = f"# PARENT_TASK: {args.parent}\n"

    content = (
        f"# TASK_ID: {task_id}\n"
        f"# MODE: {args.mode}\n"
        f"# TASK_TYPE: {args.type}\n"
        f"# PRIORITY: {args.priority}\n"
        f"# OUTPUT_FORMAT: {args.format}\n"
        f"# CREATED_AT: {now}\n"
        f"{parent_line}"
        f"\n"
        f"## CONTEXT\n"
        f"\n"
        f"{args.title}\n"
        f"\n"
        f"## CONSTRAINTS\n"
        f"\n"
        f"TODO: Add constraints.\n"
        f"\n"
        f"## DELIVERABLE\n"
        f"\n"
        f"TODO: Describe expected output.\n"
        f"\n"
        f"## SUCCESS CRITERIA\n"
        f"\n"
        f"TODO: Define success criteria.\n"
    )

    task_path = tasks_dir / f"{task_id}.md"
    task_path.write_text(content, encoding="utf-8")

    # Update queue
    state = _load_queue_state(cfg)
    add_pending(state, task_id)
    if args.parent:
        link_parent(state, task_id, args.parent)
    _save_queue_state(cfg, state)

    log_event(cfg, action="task_created", task_id=task_id,
              details=f"type={args.type} mode={args.mode} priority={args.priority}")

    print(f"Created: {task_path}")
    print(f"TASK_ID: {task_id}")
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    state = _load_queue_state(cfg)

    groups: dict[str, list[str]] = {
        "pending": state.pending,
        "processing": state.processing,
        "completed": state.completed,
        "failed": state.failed,
    }

    # Filter by --status if given
    if args.status:
        groups = {args.status: groups.get(args.status, [])}

    for status, ids in groups.items():
        if not ids:
            continue
        print(f"\n  {status.upper()} ({len(ids)}):")
        for tid in ids:
            detail = _task_detail(cfg, tid)
            print(f"    {tid}  {detail}")

    if all(len(v) == 0 for v in groups.values()):
        print("  No tasks found.")

    return 0


def _task_detail(cfg: AutomationConfig, task_id: str) -> str:
    """Try to read task file headers for display."""
    path = _find_task_file(cfg, task_id)
    if not path:
        return ""
    try:
        task = parse_task_file(path)
        h = task.header
        return f"type={h.task_type}  mode={h.mode}  priority={h.priority}  created={h.created_at}"
    except (ValueError, OSError):
        return "(parse error)"


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    result_path = Path(cfg.paths.outputs) / f"{args.task_id}.result.md"

    if not result_path.exists():
        print(f"Result file not found: {result_path}")
        return 1

    errors = validate_result(result_path)
    if not errors:
        log_event(cfg, action="validation_passed", task_id=args.task_id)
        print(f"PASS: {result_path}")
        return 0

    log_event(cfg, action="validation_failed", task_id=args.task_id, status="failed",
              details="; ".join(f"{e.field}: {e.message}" for e in errors))
    print(f"FAIL: {result_path}")
    for err in errors:
        print(f"  [{err.severity}] {err.field}: {err.message}")
    return 1


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------


def cmd_archive(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    task_id = args.task_id

    src = _find_task_file(cfg, task_id)
    if not src:
        print(f"Task file not found: {task_id}")
        return 1

    archive_dir = Path(cfg.paths.archive)
    archive_dir.mkdir(parents=True, exist_ok=True)
    dst = archive_dir / src.name

    shutil.move(str(src), str(dst))

    # Update queue — remove from whichever list it's in
    state = _load_queue_state(cfg)
    moved = False
    for lst in (state.pending, state.processing):
        if task_id in lst:
            lst.remove(task_id)
            moved = True
            break
    if moved and task_id not in state.completed and task_id not in state.failed:
        state.completed.append(task_id)
    _save_queue_state(cfg, state)

    log_event(cfg, action="task_archived", task_id=task_id)

    print(f"Archived: {dst}")
    return 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    state = _load_queue_state(cfg)

    print("\n=== Queue Status ===\n")
    print(f"  Pending:    {len(state.pending)}")
    print(f"  Processing: {len(state.processing)}")
    print(f"  Completed:  {len(state.completed)}")
    print(f"  Failed:     {len(state.failed)}")

    if state.parents:
        print("\n  Dependency chains:")
        for child, parent in state.parents.items():
            print(f"    {child} -> {parent}")

    print()
    return 0


# ---------------------------------------------------------------------------
# Main / argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="automation_cli",
        description="Automation task management CLI",
    )
    parser.add_argument(
        "--config", default=str(DEFAULT_CONFIG),
        help="Path to automation config.yaml",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a new task")
    p_create.add_argument("--type", required=True, choices=sorted(TASK_TYPES))
    p_create.add_argument("--mode", required=True, choices=sorted(MODES))
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--priority", default="MEDIUM", choices=sorted(PRIORITIES))
    p_create.add_argument("--format", default="MARKDOWN", choices=sorted(OUTPUT_FORMATS))
    p_create.add_argument("--parent", default=None, help="Parent task ID for chaining")

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument(
        "--status", default=None,
        choices=["pending", "processing", "completed", "failed"],
    )

    # validate
    p_validate = sub.add_parser("validate", help="Validate a result file")
    p_validate.add_argument("task_id", help="Task ID to validate")

    # archive
    p_archive = sub.add_parser("archive", help="Archive a task")
    p_archive.add_argument("task_id", help="Task ID to archive")

    # status
    sub.add_parser("status", help="Show queue status summary")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    dispatch = {
        "create": cmd_create,
        "list": cmd_list,
        "validate": cmd_validate,
        "archive": cmd_archive,
        "status": cmd_status,
    }

    if not args.command:
        parser.print_help()
        return 1

    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
