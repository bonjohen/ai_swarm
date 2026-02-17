"""CLI entrypoint: provision Ollama models across the fleet.

Usage: python -m scripts.provision_fleet [--config PATH] [--node NAME] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core.fleet import (
    FleetConfig,
    load_fleet_config,
    provision_fleet,
    select_tier3_model,
)

logger = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "fleet_config.yaml"


def _print_dry_run(config: FleetConfig) -> None:
    """Print what would be provisioned without pulling anything."""
    print("=== Dry-run provisioning plan ===\n")
    for node in config.nodes:
        tier3_tag, tier3_size = select_tier3_model(node.gpu_vram_gb)
        print(f"Node: {node.name}")
        print(f"  Host:     {node.host}")
        print(f"  Platform: {node.platform}")
        print(f"  GPU:      {node.gpu_type} ({node.gpu_vram_gb} GB VRAM)")
        print(f"  Base models to pull: {config.base_models}")
        print(f"  Custom models to create: {[cm.name for cm in config.custom_models]}")
        print(f"  Tier3 model: {tier3_tag} (~{tier3_size} GB)")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision Ollama models across the fleet")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="Path to fleet_config.yaml")
    parser.add_argument("--node", default=None,
                        help="Provision a single node by name")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be provisioned without pulling")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = load_fleet_config(args.config)

    # Filter to a single node if --node specified
    if args.node:
        matching = [n for n in config.nodes if n.name == args.node]
        if not matching:
            logger.error("Unknown node: %s", args.node)
            print(f"Error: unknown node '{args.node}'. "
                  f"Available: {[n.name for n in config.nodes]}")
            return 1
        config = FleetConfig(
            nodes=matching,
            base_models=config.base_models,
            custom_models=config.custom_models,
        )

    if args.dry_run:
        _print_dry_run(config)
        return 0

    result = provision_fleet(config)

    # Print summary
    print("\n=== Provisioning Summary ===\n")
    for nr in result.node_results:
        status = "OK" if nr.reachable and not nr.failed else "FAILED"
        if not nr.reachable:
            status = "UNREACHABLE"
        print(f"  {nr.node_name}: {status}")
        if nr.deleted:
            print(f"    Deleted: {nr.deleted}")
        if nr.pulled:
            print(f"    Pulled:  {nr.pulled}")
        if nr.created:
            print(f"    Created: {nr.created}")
        if nr.tier3_model:
            print(f"    Tier3:   {nr.tier3_model}")
        if nr.errors:
            for err in nr.errors:
                print(f"    ERROR: {err}")

    return 0 if result.all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
