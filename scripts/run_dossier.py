"""CLI entrypoint: run the dossier graph.

Usage: python -m scripts.run_dossier --topic_id <id> [--db <path>]
"""

from __future__ import annotations

import argparse
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
from agents.metric_extractor_agent import MetricExtractorAgent
from agents.contradiction_agent import ContradictionAgent
from agents.delta_agent import DeltaAgent
from agents.synthesizer_agent import SynthesizerAgent
from agents.publisher_agent import PublisherAgent
from core.budgets import BudgetLedger
from core.orchestrator import execute_graph
from core.adapters import make_model_call
from core.state import create_initial_state
from data.db import get_initialized_connection
from data.dao_runs import insert_run, finish_run
from data.dao_snapshots import get_latest_snapshot
from graphs.graph_types import load_graph

logger = logging.getLogger(__name__)
GRAPH_PATH = Path(__file__).parent.parent / "graphs" / "dossier_graph.yaml"


def _register_agents() -> None:
    registry.clear()
    registry.register(IngestorAgent())
    registry.register(NormalizerAgent())
    registry.register(EntityResolverAgent())
    registry.register(ClaimExtractorAgent())
    registry.register(MetricExtractorAgent())
    registry.register(ContradictionAgent())
    registry.register(DeltaAgent())
    registry.register(SynthesizerAgent())
    registry.register(PublisherAgent())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the dossier graph")
    parser.add_argument("--topic_id", required=True, help="Topic ID to process")
    parser.add_argument("--db", default="ai_swarm.db", help="SQLite database path")
    parser.add_argument("--model-call", default="stub",
                        help="Model call mode: stub, ollama, ollama:<model>")
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

    insert_run(conn, run_id=run_id, scope_type="topic", scope_id=args.topic_id,
               graph_id="dossier_graph", started_at=now)

    prev_snapshot = get_latest_snapshot(conn, "topic", args.topic_id)

    state = create_initial_state(
        scope_type="topic", scope_id=args.topic_id,
        run_id=run_id, graph_id="dossier_graph",
        extra={
            "sources": [],
            "previous_snapshot": prev_snapshot,
            "existing_claims": [],
        },
    )

    model_call = make_model_call(args.model_call)
    budget = BudgetLedger()

    logger.info("Starting dossier run %s for topic_id=%s", run_id, args.topic_id)
    result = execute_graph(graph, state, model_call=model_call, budget=budget)

    end_time = datetime.now(timezone.utc).isoformat()
    finish_run(conn, run_id, ended_at=end_time, status=result.status, cost=budget.to_dict())

    logger.info("Run %s completed with status=%s", run_id, result.status)
    conn.close()
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
