"""CLI entrypoint: run the cron-based scheduler.

Usage: python -m scripts.run_scheduler [--config <path>] [--once] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
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
from agents.metric_extractor_agent import MetricExtractorAgent
from agents.contradiction_agent import ContradictionAgent
from agents.synthesizer_agent import SynthesizerAgent
from core.budgets import BudgetLedger
from core.notifications import dispatch_notifications, load_hooks
from core.orchestrator import execute_graph
from core.routing import make_stub_model_call
from core.scheduler import ScheduleEntry, load_schedule_config, run_scheduler
from core.state import create_initial_state
from graphs.graph_types import load_graph

logger = logging.getLogger(__name__)

GRAPH_DIR = Path(__file__).parent.parent / "graphs"
GRAPH_MAP = {
    "certification": GRAPH_DIR / "certification_graph.yaml",
    "dossier": GRAPH_DIR / "dossier_graph.yaml",
    "lab": GRAPH_DIR / "lab_graph.yaml",
}
SCOPE_TYPE_MAP = {
    "certification": "cert",
    "dossier": "topic",
    "lab": "lab",
}

DEFAULT_CONFIG = Path(__file__).parent.parent / "schedule_config.yaml"


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
    registry.register(MetricExtractorAgent())
    registry.register(ContradictionAgent())
    registry.register(SynthesizerAgent())


def _dispatch_entry(entry: ScheduleEntry) -> None:
    """Execute a single scheduled graph run."""
    graph_path = GRAPH_MAP.get(entry.graph)
    if not graph_path or not graph_path.exists():
        raise ValueError(f"Unknown graph: {entry.graph}")

    graph = load_graph(graph_path)
    scope_type = SCOPE_TYPE_MAP.get(entry.graph, entry.graph)

    import uuid
    run_id = str(uuid.uuid4())

    state = create_initial_state(
        scope_type=scope_type,
        scope_id=entry.scope_id,
        run_id=run_id,
        graph_id=f"{entry.graph}_graph",
        extra={
            "sources": [],
            "previous_snapshot": None,
            "existing_claims": [],
        },
    )

    budget = BudgetLedger(
        max_tokens=entry.budget.get("max_tokens", 50000),
        max_cost=entry.budget.get("max_cost", 5.0),
    )

    model_call = make_stub_model_call()
    result = execute_graph(graph, state, model_call=model_call, budget=budget)

    logger.info("Scheduled run '%s' completed: status=%s", entry.name, result.status)

    # Send notifications
    hooks = load_hooks(entry.notify)
    dispatch_notifications(
        hooks,
        subject=f"Scheduled run '{entry.name}' {result.status}",
        body=f"Graph: {entry.graph}, Scope: {entry.scope_id}, Status: {result.status}",
        metadata={"run_id": run_id, "status": result.status, "schedule": entry.name},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the cron-based scheduler")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="Path to schedule_config.yaml")
    parser.add_argument("--once", action="store_true",
                        help="Run one check cycle then exit")
    parser.add_argument("--interval", type=int, default=60,
                        help="Check interval in seconds (default: 60)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    _register_agents()
    config = load_schedule_config(args.config)

    logger.info("Loaded %d schedule entries from %s", len(config.entries), args.config)

    state = run_scheduler(
        config,
        dispatch_fn=_dispatch_entry,
        check_interval_seconds=args.interval,
        max_iterations=1 if args.once else 0,
        on_error=lambda entry, exc: logger.error(
            "Schedule '%s' error: %s", entry.name, exc
        ),
    )

    logger.info("Scheduler stopped: %d runs dispatched, %d errors",
                state.runs_dispatched, len(state.errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
