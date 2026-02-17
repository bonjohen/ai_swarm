"""CLI entrypoint: run the story graph.

Usage: python -m scripts.run_story --world_id <id> [--sources <seed_json>] [--db <path>]
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
from agents.story_memory_loader_agent import StoryMemoryLoaderAgent
from agents.premise_architect_agent import PremiseArchitectAgent
from agents.plot_architect_agent import PlotArchitectAgent
from agents.scene_writer_agent import SceneWriterAgent
from agents.canon_updater_agent import CanonUpdaterAgent
from agents.audience_compliance_agent import AudienceComplianceAgent
from agents.narration_formatter_agent import NarrationFormatterAgent
from agents.contradiction_agent import ContradictionAgent
from agents.qa_validator_agent import QAValidatorAgent
from agents.delta_agent import DeltaAgent
from agents.publisher_agent import PublisherAgent
from core.budgets import BudgetLedger
from core.orchestrator import execute_graph
from core.state import create_initial_state
from core.adapters import make_model_call
from data.db import get_initialized_connection
from data.dao_runs import insert_run, finish_run
from data.dao_story_worlds import insert_world, get_world, increment_episode_number
from data.dao_characters import insert_character
from data.dao_threads import insert_thread
from data.dao_episodes import insert_episode
from graphs.graph_types import load_graph

logger = logging.getLogger(__name__)
GRAPH_PATH = Path(__file__).parent.parent / "graphs" / "story_graph.yaml"


def _register_agents() -> None:
    registry.clear()
    # Story-specific agents
    registry.register(StoryMemoryLoaderAgent())
    registry.register(PremiseArchitectAgent())
    registry.register(PlotArchitectAgent())
    registry.register(SceneWriterAgent())
    registry.register(CanonUpdaterAgent())
    registry.register(AudienceComplianceAgent())
    registry.register(NarrationFormatterAgent())
    # Reused agents
    registry.register(ContradictionAgent())
    registry.register(QAValidatorAgent())
    registry.register(DeltaAgent())
    registry.register(PublisherAgent())


def _seed_world(conn, seed: dict) -> str:
    """Create world, characters, and initial threads from seed JSON. Returns world_id."""
    now = datetime.now(timezone.utc).isoformat()
    world_data = seed["world"]
    world_id = world_data["world_id"]

    # Insert world
    insert_world(
        conn,
        world_id=world_id,
        name=world_data["name"],
        genre=world_data["genre"],
        tone=world_data["tone"],
        setting=world_data.get("setting"),
        thematic_constraints=world_data.get("thematic_constraints"),
        audience_profile=world_data.get("audience_profile"),
        created_at=now,
        updated_at=now,
    )

    # Insert characters
    for char in seed.get("characters", []):
        insert_character(
            conn,
            character_id=char["character_id"],
            world_id=world_id,
            name=char["name"],
            role=char["role"],
            traits=char.get("traits"),
            goals=char.get("goals"),
            fears=char.get("fears"),
            beliefs=char.get("beliefs"),
            voice_notes=char.get("voice_notes", ""),
        )

    # Insert initial threads
    for thread in seed.get("threads", []):
        insert_thread(
            conn,
            thread_id=thread["thread_id"],
            world_id=world_id,
            title=thread["title"],
            introduced_in_episode=0,
            thematic_tag=thread.get("thematic_tag", ""),
            related_character_ids=thread.get("related_character_ids"),
        )

    return world_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the story graph")
    parser.add_argument("--world_id", required=True, help="World ID to process")
    parser.add_argument("--db", default="ai_swarm.db", help="SQLite database path")
    parser.add_argument("--sources", default=None,
                        help="Path to a JSON file with seed data (world, characters, threads)")
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

    # Seed world from JSON if provided and world doesn't exist yet
    if args.sources and get_world(conn, args.world_id) is None:
        with open(args.sources) as f:
            seed = json.load(f)
        _seed_world(conn, seed)
        logger.info("Seeded world '%s' from %s", args.world_id, args.sources)

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    insert_run(conn, run_id=run_id, scope_type="story", scope_id=args.world_id,
               graph_id="story_graph", started_at=now)

    state = create_initial_state(
        scope_type="story", scope_id=args.world_id,
        run_id=run_id, graph_id="story_graph",
        extra={
            "world_id": args.world_id,
            "conn": conn,
            "claims": [],
            "metrics": [],
            "doc_ids": [],
            "segment_ids": [],
            "violations": [],
        },
    )

    model_call = make_model_call(args.model_call)
    budget = BudgetLedger()

    logger.info("Starting story run %s for world_id=%s", run_id, args.world_id)
    result = execute_graph(graph, state, model_call=model_call, budget=budget)

    end_time = datetime.now(timezone.utc).isoformat()
    finish_run(conn, run_id, ended_at=end_time, status=result.status, cost=budget.to_dict())

    if result.status == "completed":
        # Post-run: insert episode record and increment world episode number
        episode_number = result.state.get("episode_number", 1)
        episode_id = f"{args.world_id}-E{episode_number:03d}"
        insert_episode(
            conn,
            episode_id=episode_id,
            world_id=args.world_id,
            episode_number=episode_number,
            title=result.state.get("episode_title", ""),
            act_structure=result.state.get("act_structure"),
            scene_count=len(result.state.get("scenes", [])),
            word_count=len(result.state.get("episode_text", "").split()),
            snapshot_id=result.state.get("snapshot_id"),
            run_id=run_id,
            status="final",
            created_at=now,
        )
        increment_episode_number(conn, args.world_id)
        logger.info("Run %s completed. Episode %s published to: %s",
                     run_id, episode_id, result.state.get("publish_dir", "N/A"))
    else:
        for event in result.events:
            if event.get("status") == "failed":
                logger.error("Failed at node %s: %s", event["node_id"], event.get("error"))

    conn.close()
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
