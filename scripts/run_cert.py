"""CLI entrypoint: run the certification graph.

Usage: python -m scripts.run_cert --cert_id <id> [--db <path>]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents import registry
from agents.ingestor_agent import IngestorAgent
from agents.normalizer_agent import NormalizerAgent
from agents.entity_resolver_agent import EntityResolverAgent
from agents.claim_extractor_agent import ClaimExtractorAgent
from agents.lesson_composer_agent import LessonComposerAgent
from agents.question_generator_agent import QuestionGeneratorAgent
from agents.qa_validator_agent import QAValidatorAgent
from agents.delta_agent import DeltaAgent
from agents.publisher_agent import PublisherAgent
from core.budgets import BudgetLedger
from core.orchestrator import execute_graph
from core.adapters import make_model_call, make_router_from_config
from core.state import create_initial_state
from data.db import get_initialized_connection
from data.dao_runs import insert_run, finish_run
from data.dao_snapshots import get_latest_snapshot
from graphs.graph_types import load_graph

logger = logging.getLogger(__name__)
GRAPH_PATH = Path(__file__).parent.parent / "graphs" / "certification_graph.yaml"


def _register_agents() -> None:
    registry.clear()
    registry.register(IngestorAgent())
    registry.register(NormalizerAgent())
    registry.register(EntityResolverAgent())
    registry.register(ClaimExtractorAgent())
    registry.register(LessonComposerAgent())
    registry.register(QuestionGeneratorAgent())
    registry.register(QAValidatorAgent())
    registry.register(DeltaAgent())
    registry.register(PublisherAgent())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the certification graph")
    parser.add_argument("--cert_id", required=True, help="Certification ID to process")
    parser.add_argument("--db", default="ai_swarm.db", help="SQLite database path")
    parser.add_argument("--sources", default=None,
                        help="Path to a JSON file with seed data (sources, objectives, etc.)")
    parser.add_argument("--model-call", default="stub",
                        help="Model call mode: stub, ollama, ollama:<model>")
    parser.add_argument("--router-config", default=None,
                        help="Path to router_config.yaml for tiered model routing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    _register_agents()
    graph = load_graph(GRAPH_PATH)
    conn = get_initialized_connection(args.db)

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    insert_run(conn, run_id=run_id, scope_type="cert", scope_id=args.cert_id,
               graph_id="certification_graph", started_at=now)

    # Load previous snapshot for delta computation
    prev_snapshot = get_latest_snapshot(conn, "cert", args.cert_id)

    # Load seed data from JSON file if provided
    seed = {}
    if args.sources:
        with open(args.sources) as f:
            seed = json.load(f)

    state = create_initial_state(
        scope_type="cert", scope_id=args.cert_id,
        run_id=run_id, graph_id="certification_graph",
        extra={
            "sources": seed.get("sources", []),
            "previous_snapshot": prev_snapshot,
            "existing_claims": seed.get("existing_claims", []),
            "objectives": seed.get("objectives", []),
            "metrics": seed.get("metrics", []),
        },
    )

    budget = BudgetLedger()

    logger.info("Starting certification run %s for cert_id=%s", run_id, args.cert_id)
    if args.router_config:
        router = make_router_from_config(args.router_config)
        result = execute_graph(graph, state, router=router, budget=budget)
    else:
        model_call = make_model_call(args.model_call)
        result = execute_graph(graph, state, model_call=model_call, budget=budget)

    end_time = datetime.now(timezone.utc).isoformat()
    finish_run(conn, run_id, ended_at=end_time, status=result.status, cost=budget.to_dict())

    logger.info("Run %s completed with status=%s", run_id, result.status)
    if result.status == "completed":
        logger.info("Published to: %s", result.state.get("publish_dir", "N/A"))
    else:
        for event in result.events:
            if event.get("status") == "failed":
                logger.error("Failed at node %s: %s", event["node_id"], event.get("error"))

    conn.close()
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
