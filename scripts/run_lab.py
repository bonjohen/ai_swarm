"""CLI entrypoint: run the lab benchmark graph.

Usage: python -m scripts.run_lab --suite_id <id> [--db <path>]
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
from agents.metric_extractor_agent import MetricExtractorAgent
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
GRAPH_PATH = Path(__file__).parent.parent / "graphs" / "lab_graph.yaml"


def _register_agents() -> None:
    registry.clear()
    registry.register(IngestorAgent())
    registry.register(MetricExtractorAgent())
    registry.register(DeltaAgent())
    registry.register(SynthesizerAgent())
    registry.register(PublisherAgent())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the lab benchmark graph")
    parser.add_argument("--suite_id", required=True, help="Suite ID to benchmark")
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

    insert_run(conn, run_id=run_id, scope_type="lab", scope_id=args.suite_id,
               graph_id="lab_graph", started_at=now)

    prev_snapshot = get_latest_snapshot(conn, "lab", args.suite_id)

    state = create_initial_state(
        scope_type="lab", scope_id=args.suite_id,
        run_id=run_id, graph_id="lab_graph",
        extra={
            "suite_config": {},
            "previous_snapshot": prev_snapshot,
            "claims": [],
            "metrics": [],
        },
    )

    model_call = make_model_call(args.model_call)
    budget = BudgetLedger()

    logger.info("Starting lab run %s for suite_id=%s", run_id, args.suite_id)
    result = execute_graph(graph, state, model_call=model_call, budget=budget)

    end_time = datetime.now(timezone.utc).isoformat()
    finish_run(conn, run_id, ended_at=end_time, status=result.status, cost=budget.to_dict())

    logger.info("Run %s completed with status=%s", run_id, result.status)
    conn.close()
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
