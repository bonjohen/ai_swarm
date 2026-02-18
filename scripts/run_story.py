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
from core.adapters import make_model_call, make_router_from_config, OllamaAdapter, AnthropicAdapter, make_ollama_adapter
from core.routing import ModelRouter, RoutingDecision
from data.db import get_initialized_connection
from data.dao_runs import insert_run, finish_run
from data.dao_story_worlds import insert_world, get_world, increment_episode_number
from data.dao_characters import insert_character, update_character, update_arc_stage
from data.dao_threads import insert_thread, resolve_thread
from data.dao_claims import insert_claim
from data.dao_entities import insert_entity
from data.dao_episodes import insert_episode
from data.dao_snapshots import insert_snapshot
from graphs.graph_types import load_graph

logger = logging.getLogger(__name__)
GRAPH_PATH = Path(__file__).parent.parent / "graphs" / "story_graph.yaml"

# Agent IDs that need frontier (Haiku) for creative work
CREATIVE_AGENTS = {"premise_architect", "plot_architect", "scene_writer", "narration_formatter"}


class StoryTieredRouter(ModelRouter):
    """Routes creative agents to Anthropic Haiku, extraction agents to local Ollama."""

    def __init__(self, local: OllamaAdapter, frontier: AnthropicAdapter):
        super().__init__()
        self._local = local
        self._frontier = frontier
        self.register_local(local)
        self.register_frontier(frontier)

    def select_model(self, agent_policy, state):
        agent_id = state.get("_current_agent_id", "")
        if agent_id in CREATIVE_AGENTS:
            return RoutingDecision(
                model_name=self._frontier.name,
                reason=f"creative agent '{agent_id}' → frontier",
                escalated=True,
            )
        return RoutingDecision(
            model_name=self._local.name,
            reason=f"extraction/tier0 agent '{agent_id}' → local",
            escalated=False,
        )


def _print_token_summary(local: OllamaAdapter, frontier: AnthropicAdapter) -> None:
    """Print per-adapter token usage summary."""
    print("\n=== Token Usage Summary ===")
    print(f"  Ollama ({local.model}):")
    print(f"    Calls:         {local.call_count}")
    print(f"    Input tokens:  {local.total_input_tokens:,}")
    print(f"    Output tokens: {local.total_output_tokens:,}")
    print(f"  Anthropic ({frontier.model}):")
    print(f"    Calls:         {frontier.call_count}")
    print(f"    Input tokens:  {frontier.total_input_tokens:,}")
    print(f"    Output tokens: {frontier.total_output_tokens:,}")
    total_in = local.total_input_tokens + frontier.total_input_tokens
    total_out = local.total_output_tokens + frontier.total_output_tokens
    print(f"  Total:")
    print(f"    Calls:         {local.call_count + frontier.call_count}")
    print(f"    Input tokens:  {total_in:,}")
    print(f"    Output tokens: {total_out:,}")
    print("===========================\n")


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


def _persist_world_state(conn, world_id: str, episode_number: int, state: dict, now: str) -> None:
    """Write canon changes back to DB after a successful graph run.

    Persists: claims, character updates, new/resolved threads, entities,
    snapshot, episode record, and increments the world episode counter.
    """
    # 1. Write new claims
    for claim in state.get("new_claims", []):
        insert_claim(
            conn,
            claim_id=claim["claim_id"],
            scope_type="story",
            scope_id=world_id,
            statement=claim["statement"],
            claim_type=claim["claim_type"],
            entities=claim.get("entities"),
            citations=claim.get("citations"),
            evidence_strength=claim.get("evidence_strength"),
            confidence=claim.get("confidence"),
            status="active",
            first_seen_at=now,
        )

    # 2. Update characters (beliefs, goals, traits, arc_stage)
    # Valid keyword args for update_character()
    _VALID_CHAR_FIELDS = {"name", "role", "alive", "traits", "goals", "fears", "beliefs", "voice_notes", "meta"}
    for update in state.get("updated_characters", []):
        cid = update.get("character_id")
        if not cid:
            continue
        changes = update.get("changes", {})
        # Normalize: LLMs sometimes return DB column names (e.g. traits_json)
        # instead of the API names (traits). Strip the _json suffix.
        normalized = {}
        for k, v in changes.items():
            key = k.removesuffix("_json")
            normalized[key] = v
        changes = normalized
        # Separate arc_stage (requires sequential enforcement) from other fields
        arc_stage = changes.pop("arc_stage", None)
        # Filter to only valid fields to guard against unexpected LLM keys
        safe_changes = {k: v for k, v in changes.items() if k in _VALID_CHAR_FIELDS}
        if safe_changes:
            update_character(conn, cid, **safe_changes)
        if arc_stage:
            try:
                update_arc_stage(conn, cid, arc_stage)
            except ValueError as e:
                logger.warning("Skipping arc_stage update for %s: %s", cid, e)

    # 3. Insert new threads
    for thread in state.get("new_threads", []):
        tid = thread.get("thread_id", str(uuid.uuid4()))
        insert_thread(
            conn,
            thread_id=tid,
            world_id=world_id,
            title=thread.get("title", "Untitled Thread"),
            introduced_in_episode=episode_number,
            thematic_tag=thread.get("thematic_tag", ""),
            related_character_ids=thread.get("related_character_ids"),
        )

    # 4. Resolve threads
    for tid in state.get("resolved_threads", []):
        resolve_thread(conn, tid, resolved_in_episode=episode_number)

    # 5. Insert new entities
    for entity in state.get("new_entities", []):
        insert_entity(
            conn,
            entity_id=entity["entity_id"],
            type=entity.get("type", "unknown"),
            names=[entity["name"]] if entity.get("name") else None,
            props={k: v for k, v in entity.items() if k not in ("entity_id", "type", "name")},
        )

    # 6. Insert snapshot record (so next episode can find it)
    snapshot_id = state.get("snapshot_id")
    if snapshot_id:
        insert_snapshot(
            conn,
            snapshot_id=snapshot_id,
            scope_type="story",
            scope_id=world_id,
            created_at=now,
            hash=state.get("snapshot_hash", ""),
            included_claim_ids=[c["claim_id"] for c in state.get("new_claims", [])],
        )

    # 7. Insert episode record
    episode_id = f"{world_id}-E{episode_number:03d}"
    insert_episode(
        conn,
        episode_id=episode_id,
        world_id=world_id,
        episode_number=episode_number,
        title=state.get("episode_title", ""),
        act_structure=state.get("act_structure"),
        scene_count=len(state.get("scenes", [])),
        word_count=len(state.get("episode_text", "").split()),
        snapshot_id=snapshot_id,
        run_id=state.get("run_id", ""),
        status="final",
        created_at=now,
    )

    # 8. Increment world episode counter
    increment_episode_number(conn, world_id)

    logger.info("Persisted world state: %d claims, %d character updates, "
                "%d new threads, %d resolved threads, %d entities",
                len(state.get("new_claims", [])),
                len(state.get("updated_characters", [])),
                len(state.get("new_threads", [])),
                len(state.get("resolved_threads", [])),
                len(state.get("new_entities", [])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the story graph")
    parser.add_argument("--world_id", required=True, help="World ID to process")
    parser.add_argument("--db", default="ai_swarm.db", help="SQLite database path")
    parser.add_argument("--sources", default=None,
                        help="Path to a JSON file with seed data (world, characters, threads)")
    parser.add_argument("--model-call", default="stub",
                        help="Model call mode: stub, ollama, ollama:<model>")
    parser.add_argument("--frontier-model", default=None,
                        help="Frontier model for escalation on retry (e.g., ollama:llama3:70b)")
    parser.add_argument("--tiered", action="store_true",
                        help="Tiered routing: creative agents on Anthropic Haiku, "
                             "extraction on local Ollama")
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

    budget = BudgetLedger(max_tokens=32768)
    local_adapter = None
    frontier_adapter = None

    if args.tiered:
        local_adapter = make_ollama_adapter()
        frontier_adapter = AnthropicAdapter(
            name="haiku",
            model="claude-haiku-4-5-20251001",
            max_tokens=8192,
            min_interval=1.0,  # 1s between calls to stay within free tier
        )
        router = StoryTieredRouter(local=local_adapter, frontier=frontier_adapter)
        logger.info("Tiered mode: creative → %s, extraction → %s",
                     frontier_adapter.model, local_adapter.model)
        logger.info("Starting story run %s for world_id=%s", run_id, args.world_id)
        result = execute_graph(graph, state, router=router, budget=budget)
    elif args.router_config:
        router = make_router_from_config(args.router_config)
        logger.info("Starting story run %s for world_id=%s (router-config)", run_id, args.world_id)
        result = execute_graph(graph, state, router=router, budget=budget)
    else:
        model_call = make_model_call(args.model_call)
        frontier_model_call = make_model_call(args.frontier_model) if args.frontier_model else None
        logger.info("Starting story run %s for world_id=%s", run_id, args.world_id)
        result = execute_graph(
            graph, state, model_call=model_call,
            frontier_model_call=frontier_model_call, budget=budget,
        )

    end_time = datetime.now(timezone.utc).isoformat()
    finish_run(conn, run_id, ended_at=end_time, status=result.status, cost=budget.to_dict())

    if result.status == "completed":
        episode_number = result.state.get("episode_number", 1)
        _persist_world_state(conn, args.world_id, episode_number, result.state, now)
        logger.info("Run %s completed. Episode E%03d published to: %s",
                     run_id, episode_number, result.state.get("publish_dir", "N/A"))
    else:
        for event in result.events:
            if event.get("status") == "failed":
                logger.error("Failed at node %s: %s", event["node_id"], event.get("error"))

    if args.tiered and local_adapter and frontier_adapter:
        _print_token_summary(local_adapter, frontier_adapter)

    conn.close()
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
