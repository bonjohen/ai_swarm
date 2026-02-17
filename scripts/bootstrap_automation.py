"""CLI entrypoint: bootstrap the automation directory structure and queue state.

Usage: python -m scripts.bootstrap_automation [--config PATH] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from automation.config import load_config, default_config
from automation.queue import QueueState, save_queue

logger = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).parent.parent / "automation" / "config.yaml"


def bootstrap(config_path: Path | None = None) -> dict[str, str]:
    """Create automation directories and initialize queue.json.

    Returns a mapping of ``{path: "created" | "exists"}`` for each directory
    and the queue file.
    """
    if config_path and config_path.exists():
        from automation.config import load_config
        cfg = load_config(config_path)
    else:
        cfg = default_config()

    paths = cfg.paths
    results: dict[str, str] = {}

    for dir_path in [
        paths.base,
        paths.tasks,
        paths.processing,
        paths.outputs,
        paths.archive,
        paths.logs,
        paths.schemas,
    ]:
        p = Path(dir_path)
        if p.exists():
            results[dir_path] = "exists"
        else:
            p.mkdir(parents=True, exist_ok=True)
            results[dir_path] = "created"

    queue_path = Path(paths.base) / "queue.json"
    queue_key = paths.base + "/queue.json"
    if queue_path.exists():
        results[queue_key] = "exists"
    else:
        save_queue(queue_path, QueueState())
        results[queue_key] = "created"

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap the automation directory structure and queue state",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to automation config.yaml (default: automation/config.yaml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config_path = Path(args.config)
    results = bootstrap(config_path)

    print("\n=== Automation Bootstrap ===\n")
    for path, status in results.items():
        marker = "+" if status == "created" else "="
        label = "created" if status == "created" else "already exists"
        print(f"  [{marker}] {path}  ({label})")

    created = sum(1 for s in results.values() if s == "created")
    existed = sum(1 for s in results.values() if s == "exists")
    print(f"\n  {created} created, {existed} already existed.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
