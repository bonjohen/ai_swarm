"""Unified CLI entrypoint — routes requests through the tiered dispatcher.

Usage:
    python -m scripts.run_router "/cert az-104"
    python -m scripts.run_router "/status"
    python -m scripts.run_router '{"command": "/lab suite-1"}'
    python -m scripts.run_router "Explain the certification architecture"
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from core.command_registry import CommandRegistry, register_defaults
from core.tiered_dispatch import DispatchResult, TieredDispatcher

logger = logging.getLogger(__name__)

# Maps target script names to their module paths
_TARGET_MODULES: dict[str, str] = {
    "run_cert.py": "scripts.run_cert",
    "run_dossier.py": "scripts.run_dossier",
    "run_story.py": "scripts.run_story",
    "run_lab.py": "scripts.run_lab",
}

# Maps graph targets to their argument flag and argument key
_TARGET_ARG_MAP: dict[str, tuple[str, str]] = {
    "run_cert.py": ("--cert_id", "cert_id"),
    "run_dossier.py": ("--topic_id", "topic_id"),
    "run_story.py": ("--world_id", "world_id"),
    "run_lab.py": ("--suite_id", "suite_id"),
}


def _execute_result(result: DispatchResult, *, dry_run: bool = False) -> int:
    """Execute the action described by a dispatch result.

    Returns exit code (0 = success).
    """
    if result.action == "needs_escalation":
        print(f"No Tier 0 match. Higher tiers not yet implemented.")
        print(f"Request would be escalated to Tier 1 (micro LLM).")
        return 1

    if result.action == "show_status":
        print("Status: system operational")
        return 0

    if result.action == "show_help":
        print("Available commands:")
        print("  /cert <cert_id>     — Run the certification graph")
        print("  /dossier <topic_id> — Run the dossier graph")
        print("  /story <world_id>   — Run the story graph")
        print("  /lab <suite_id>     — Run the lab graph")
        print("  /status             — Show system status")
        print("  /help               — Show this help")
        return 0

    if result.action == "execute_graph":
        module = _TARGET_MODULES.get(result.target)
        if not module:
            print(f"Unknown target: {result.target}")
            return 1

        arg_flag, arg_key = _TARGET_ARG_MAP.get(result.target, (None, None))
        arg_value = result.args.get(arg_key, "") if arg_key else ""

        if dry_run:
            print(f"[dry-run] Would execute: python -m {module} {arg_flag} {arg_value}")
            return 0

        cmd = [sys.executable, "-m", module]
        if arg_flag and arg_value:
            cmd.extend([arg_flag, arg_value])

        logger.info("Executing: %s", " ".join(cmd))
        return subprocess.call(cmd)

    if result.action == "unknown_command":
        print(f"Unknown command in JSON payload: {result.args}")
        return 1

    print(f"Unhandled action: {result.action}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified router — routes requests through tiered dispatch",
    )
    parser.add_argument("request", nargs="?", default=None,
                        help="Request text (slash command, JSON payload, or free text)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be executed without running it")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.request is None:
        parser.print_help()
        return 1

    # Build dispatcher
    registry = CommandRegistry()
    register_defaults(registry)
    dispatcher = TieredDispatcher(command_registry=registry)

    # Dispatch
    result = dispatcher.dispatch(args.request)
    logger.info("Dispatch result: tier=%d action=%s target=%s confidence=%.2f",
                result.tier, result.action, result.target, result.confidence)

    return _execute_result(result, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
