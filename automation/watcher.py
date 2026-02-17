"""Watcher — polls the outputs directory for new result files.

Validates each new result and updates queue state accordingly.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from automation.config import AutomationConfig, default_config, load_config
from automation.logging import log_event
from automation.queue import load_queue, move_to_completed, move_to_failed, save_queue
from automation.task_schema import _HEADER_RE
from automation.validator import validate_result

logger = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def _queue_path(cfg: AutomationConfig) -> Path:
    return Path(cfg.paths.base) / "queue.json"


def watch_once(cfg: AutomationConfig) -> list[str]:
    """Run a single poll cycle.  Returns list of task IDs processed."""
    outputs_dir = Path(cfg.paths.outputs)
    if not outputs_dir.exists():
        return []

    state = load_queue(_queue_path(cfg))
    already_done = set(state.completed + state.failed)
    processed: list[str] = []

    for result_file in sorted(outputs_dir.glob("*.result.md")):
        # Extract task ID from the RESULT_FOR header, fall back to filename
        task_id = _extract_task_id(result_file)
        if not task_id:
            task_id = result_file.name.replace(".result.md", "")
        if not task_id:
            logger.warning("Cannot determine task ID from %s", result_file.name)
            continue

        if task_id in already_done:
            continue

        if task_id not in state.processing:
            # Not a task we're tracking in processing — skip
            continue

        errors = validate_result(result_file)

        if not errors:
            move_to_completed(state, task_id)
            log_event(cfg, action="task_completed", task_id=task_id,
                      details=f"Result validated: {result_file.name}")
            logger.info("Completed: %s", task_id)
        else:
            move_to_failed(state, task_id)
            error_msgs = "; ".join(f"{e.field}: {e.message}" for e in errors)
            log_event(cfg, action="validation_failed", task_id=task_id,
                      status="failed", details=error_msgs)
            logger.warning("Failed validation: %s — %s", task_id, error_msgs)

        processed.append(task_id)

    if processed:
        save_queue(_queue_path(cfg), state)

    log_event(cfg, action="watcher_poll",
              details=f"Processed {len(processed)} result(s)")

    return processed


def watch(cfg: AutomationConfig, *, max_cycles: int = 0) -> None:
    """Continuous polling loop.

    Args:
        cfg: Automation configuration.
        max_cycles: Stop after N cycles (0 = run forever).
    """
    cycle = 0
    while True:
        cycle += 1
        watch_once(cfg)

        if max_cycles and cycle >= max_cycles:
            break

        time.sleep(cfg.watcher.interval_seconds)


def _extract_task_id(path: Path) -> str | None:
    """Read a result file's RESULT_FOR header."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _HEADER_RE.match(line)
            if m and m.group(1).upper() == "RESULT_FOR":
                return m.group(2).strip()
    except OSError:
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch for automation result files")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="Path to automation config.yaml")
    parser.add_argument("--once", action="store_true",
                        help="Run a single poll cycle then exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cfg_path = Path(args.config)
    cfg = load_config(cfg_path) if cfg_path.exists() else default_config()

    if args.once:
        processed = watch_once(cfg)
        print(f"Processed {len(processed)} result(s): {processed}")
        return 0

    watch(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
