"""Graph Runner — executes graph definitions, manages state, enforces budgets."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from agents.registry import get_agent
from core.budgets import BudgetLedger
from core.errors import (
    AgentValidationError,
    BudgetExceededError,
    GraphError,
    MissingStateError,
    ModelAPIError,
    NodeError,
    RoutingFailure,
)
from core.logging import get_metrics_collector
from core.routing import ModelRouter
from core.state import merge_delta, validate_state
from graphs.graph_types import Graph, GraphNode

logger = logging.getLogger(__name__)

CHECKPOINT_DIR = Path(".checkpoints")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunResult:
    """Outcome of a graph run."""

    def __init__(
        self,
        run_id: str,
        status: str,
        state: dict[str, Any],
        events: list[dict[str, Any]],
        budget: BudgetLedger,
    ):
        self.run_id = run_id
        self.status = status
        self.state = state
        self.events = events
        self.budget = budget


def _save_checkpoint(run_id: str, node_name: str, state: dict[str, Any]) -> Path:
    """Save a state checkpoint after successful node execution."""
    cp_dir = CHECKPOINT_DIR / run_id
    cp_dir.mkdir(parents=True, exist_ok=True)
    cp_path = cp_dir / f"{node_name}.json"
    cp_path.write_bytes(json.dumps(state, indent=2, default=str).encode("utf-8"))
    return cp_path


def load_checkpoint(run_id: str) -> tuple[str, dict[str, Any]] | None:
    """Load the latest checkpoint for a run, returns (last_completed_node, state) or None."""
    cp_dir = CHECKPOINT_DIR / run_id
    if not cp_dir.exists():
        return None
    # Find the most recent checkpoint by file modification time
    checkpoints = sorted(cp_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not checkpoints:
        return None
    latest = checkpoints[-1]
    node_name = latest.stem
    state = json.loads(latest.read_bytes())
    return node_name, state


def execute_graph(
    graph: Graph,
    state: dict[str, Any],
    *,
    model_call: Any = None,
    frontier_model_call: Any = None,
    router: ModelRouter | None = None,
    budget: BudgetLedger | None = None,
    on_event: Any = None,
    checkpoint: bool = False,
    resume_from: str | None = None,
) -> RunResult:
    """Run a full graph to completion.

    Args:
        graph: The graph definition to execute.
        state: Initial run state dict (must contain required keys).
        model_call: callable(system_prompt, user_message) -> str
        frontier_model_call: Optional frontier model for escalation on retry.
            When a node is re-executed via on_fail routing and the agent allows
            frontier models, this callable is used instead of model_call.
        router: Optional ModelRouter for per-node model selection.
            When provided, overrides model_call with router-selected callable.
            Backward compatible: if model_call is provided and no router,
            uses model_call directly (existing behavior).
        budget: Optional BudgetLedger for cost tracking/enforcement.
        on_event: Optional callable(event_dict) for observability.
        checkpoint: If True, save state after each successful node.
        resume_from: Node name to resume from (skip nodes before this one).

    Returns:
        RunResult with final state, events, and status.
    """
    missing = validate_state(state)
    if missing:
        raise GraphError(f"Initial state missing required keys: {missing}")

    if budget is None:
        budget = BudgetLedger()

    run_id = state["run_id"]
    events: list[dict[str, Any]] = []
    current_node_name = graph.entry
    max_on_fail_cycles = 3  # prevent infinite on_fail loops
    on_fail_counts: dict[str, int] = {}  # node_name -> on_fail trigger count

    # If resuming, skip to the node after resume_from
    if resume_from:
        found = False
        skip_node = graph.entry
        while skip_node is not None:
            node = graph.get_node(skip_node)
            if skip_node == resume_from:
                current_node_name = node.next
                found = True
                break
            if node.end:
                break
            skip_node = node.next
        if not found:
            raise GraphError(f"Cannot resume: node '{resume_from}' not found in graph")

    step_number = 0
    while current_node_name is not None:
        step_number += 1
        node = graph.get_node(current_node_name)
        logger.info(
            "[step %d] >>> Node '%s' (agent=%s) starting",
            step_number, node.name, node.agent,
        )

        # Inject degradation hints into state if budget is under pressure
        hint = budget.get_degradation_hint()
        if hint:
            state["_degradation"] = {
                "active": True,
                "max_sources": hint.max_sources,
                "max_questions": hint.max_questions,
                "skip_deep_synthesis": hint.skip_deep_synthesis,
                "reason": hint.reason,
            }

        event = _execute_node(
            node=node,
            graph=graph,
            state=state,
            model_call=model_call,
            frontier_model_call=frontier_model_call,
            router=router,
            budget=budget,
            run_id=run_id,
        )
        events.append(event)
        if on_event:
            on_event(event)

        if event["status"] == "success":
            # Save checkpoint after successful node execution
            if checkpoint:
                _save_checkpoint(run_id, node.name, state)

            if node.end:
                logger.info(
                    "[step %d] <<< Node '%s' (agent=%s) completed [END]",
                    step_number, node.name, node.agent,
                )
                current_node_name = None
            else:
                logger.info(
                    "[step %d] <<< Node '%s' (agent=%s) completed → next '%s'",
                    step_number, node.name, node.agent, node.next,
                )
                current_node_name = node.next

        elif event["status"] == "budget_degraded":
            # Budget exceeded but degradation was applied — continue with degraded state
            budget.flag_human_review(f"Budget degraded at node '{node.name}': {event.get('error', '')}")
            if checkpoint:
                _save_checkpoint(run_id, node.name, state)
            if node.end:
                current_node_name = None
            else:
                current_node_name = node.next

        elif event["status"] == "failed":
            if node.on_fail:
                # Track on_fail cycle count to prevent infinite loops
                on_fail_counts[node.name] = on_fail_counts.get(node.name, 0) + 1
                if on_fail_counts[node.name] > max_on_fail_cycles:
                    logger.error(
                        "Node '%s' exceeded max on_fail cycles (%d), aborting graph",
                        node.name, max_on_fail_cycles,
                    )
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        state=state,
                        events=events,
                        budget=budget,
                    )
                logger.warning(
                    "Node '%s' failed (cycle %d/%d), routing to on_fail '%s'",
                    node.name, on_fail_counts[node.name], max_on_fail_cycles, node.on_fail,
                )
                # Track escalation: mark the on_fail target for frontier escalation
                escalated = state.setdefault("_escalated_nodes", set())
                escalated.add(node.on_fail)
                current_node_name = node.on_fail
            else:
                logger.error("Node '%s' failed with no on_fail, aborting graph", node.name)
                return RunResult(
                    run_id=run_id,
                    status="failed",
                    state=state,
                    events=events,
                    budget=budget,
                )

    return RunResult(
        run_id=run_id,
        status="completed",
        state=state,
        events=events,
        budget=budget,
    )


def _execute_node(
    *,
    node: GraphNode,
    graph: Graph,
    state: dict[str, Any],
    model_call: Any,
    frontier_model_call: Any = None,
    router: ModelRouter | None = None,
    budget: BudgetLedger,
    run_id: str,
) -> dict[str, Any]:
    """Execute a single graph node with retry logic.

    Returns an event dict describing the outcome.
    """
    agent: BaseAgent = get_agent(node.agent)
    attempts = max(node.retry.max_attempts, 1)

    state["_current_agent_id"] = agent.AGENT_ID

    # Per-node model selection via router (when available)
    routing_decision = None
    if router is not None and hasattr(agent, "POLICY"):
        routing_decision = router.select_model(agent.POLICY, state)
        try:
            effective_model_call = router.get_model_callable(routing_decision)
        except RuntimeError:
            # Adapter not registered — fall back to provided model_call
            effective_model_call = model_call
        logger.info("Router selected '%s' for node '%s' (escalated=%s, reason=%s)",
                     routing_decision.model_name, node.name,
                     routing_decision.escalated, routing_decision.reason)
    else:
        # Frontier escalation: use frontier model if this node was routed to via on_fail
        # and the agent allows frontier models and a frontier callable is available
        escalated_nodes = state.get("_escalated_nodes", set())
        use_frontier = (
            frontier_model_call is not None
            and node.name in escalated_nodes
            and getattr(agent, "POLICY", None)
            and agent.POLICY.allowed_frontier_models
        )
        effective_model_call = frontier_model_call if use_frontier else model_call
        if use_frontier:
            logger.info("Escalating node '%s' to frontier model", node.name)

    for attempt in range(1, attempts + 1):
        event_id = str(uuid.uuid4())
        started = _utcnow()

        try:
            # 1. Validate inputs exist in state
            missing = [k for k in node.inputs if k not in state]
            if missing:
                raise MissingStateError(node.name, missing)

            # 2. Check budget (with per-node caps if defined)
            budget.check(node.budget)

            # 3. Execute agent (use frontier model if escalated)
            t0 = time.monotonic()
            delta_state = agent.run(state, model_call=effective_model_call)
            latency_ms = (time.monotonic() - t0) * 1000

            # 4. Output schema validation is done inside agent.run() via validate()

            # 5. Merge delta_state into state
            merge_delta(state, delta_state)

            # 5b. Check for QA gate failure — qa_validator returns FAIL as data,
            # not as an exception. If on_fail is defined, raise so the fail path
            # routes to the recovery node.
            if (delta_state.get("gate_status") == "FAIL" and node.on_fail):
                violations = delta_state.get("violations", [])
                for v in violations:
                    logger.warning(
                        "  QA violation: %s — %s",
                        v.get("rule", "?"), v.get("message", "?"),
                    )
                raise ValueError(
                    f"QA gate FAIL: {len(violations)} violation(s)"
                )

            # 6. Log routing telemetry
            if routing_decision is not None:
                metrics = get_metrics_collector()
                chosen_tier = 3 if routing_decision.escalated else getattr(agent.POLICY, "preferred_tier", 2)
                metrics.record_routing_decision(
                    chosen_tier=chosen_tier,
                    provider=routing_decision.model_name,
                    escalated=routing_decision.escalated,
                    request_tier=getattr(agent.POLICY, "preferred_tier", 2),
                    latency_ms=latency_ms,
                )
                metrics.record_model_call(escalated=routing_decision.escalated)
                # Persist to DB if connection available
                conn = state.get("conn")
                if conn is not None:
                    try:
                        from data.dao_routing import insert_routing_decision
                        insert_routing_decision(
                            conn,
                            decision_id=str(uuid.uuid4()),
                            run_id=run_id,
                            node_id=node.name,
                            agent_id=agent.AGENT_ID,
                            request_tier=getattr(agent.POLICY, "preferred_tier", 2),
                            chosen_tier=chosen_tier,
                            provider=routing_decision.model_name,
                            escalation_reason=routing_decision.reason if routing_decision.escalated else None,
                            latency_ms=latency_ms,
                            created_at=_utcnow(),
                        )
                    except Exception as db_exc:
                        logger.debug("Failed to persist routing decision: %s", db_exc)

            # 7. Emit success event
            evt = {
                "event_id": event_id,
                "run_id": run_id,
                "t": started,
                "node_id": node.name,
                "agent_id": agent.AGENT_ID,
                "status": "success",
                "attempt": attempt,
                "latency_ms": round(latency_ms, 1),
                "cost": budget.to_dict(),
            }
            if routing_decision is not None:
                evt["routing"] = {
                    "model": routing_decision.model_name,
                    "escalated": routing_decision.escalated,
                    "reason": routing_decision.reason,
                }
            elif router is None:
                # Legacy escalation tracking
                escalated_nodes = state.get("_escalated_nodes", set())
                if node.name in escalated_nodes and frontier_model_call is not None:
                    evt["escalated"] = True
            return evt

        except BudgetExceededError as exc:
            logger.warning("Node '%s' budget exceeded: %s", node.name, exc)
            # Try degradation instead of hard failure
            if not budget.degradation_active:
                budget.degradation_active = True
                budget.flag_human_review(
                    f"Budget exceeded at node '{node.name}': {exc}"
                )
            return {
                "event_id": event_id,
                "run_id": run_id,
                "t": started,
                "node_id": node.name,
                "agent_id": agent.AGENT_ID,
                "status": "budget_degraded",
                "attempt": attempt,
                "error": str(exc),
                "cost": budget.to_dict(),
            }

        except RoutingFailure as exc:
            logger.error("Node '%s' routing failure: %s", node.name, exc)
            return {
                "event_id": event_id,
                "run_id": run_id,
                "t": started,
                "node_id": node.name,
                "agent_id": agent.AGENT_ID,
                "status": "failed",
                "attempt": attempt,
                "error": f"routing_failure: {exc}",
                "tried_providers": exc.tried_providers,
                "cost": budget.to_dict(),
            }

        except ModelAPIError as exc:
            # Model API failures (timeouts, rate limits) get retried
            logger.warning(
                "Node '%s' model API error attempt %d/%d: %s",
                node.name, attempt, attempts, exc,
            )
            if attempt < attempts:
                time.sleep(node.retry.backoff_seconds)
                continue
            return {
                "event_id": event_id,
                "run_id": run_id,
                "t": started,
                "node_id": node.name,
                "agent_id": agent.AGENT_ID,
                "status": "failed",
                "attempt": attempt,
                "error": f"model_api_error: {exc}",
                "cost": budget.to_dict(),
            }

        except (AgentValidationError, MissingStateError, ValueError) as exc:
            logger.warning(
                "Node '%s' attempt %d/%d failed: %s", node.name, attempt, attempts, exc
            )
            if attempt < attempts:
                time.sleep(node.retry.backoff_seconds)
                continue
            return {
                "event_id": event_id,
                "run_id": run_id,
                "t": started,
                "node_id": node.name,
                "agent_id": agent.AGENT_ID,
                "status": "failed",
                "attempt": attempt,
                "error": str(exc),
                "cost": budget.to_dict(),
            }

        except Exception as exc:
            logger.error("Node '%s' unexpected error: %s", node.name, exc, exc_info=True)
            return {
                "event_id": event_id,
                "run_id": run_id,
                "t": started,
                "node_id": node.name,
                "agent_id": agent.AGENT_ID,
                "status": "failed",
                "attempt": attempt,
                "error": str(exc),
                "cost": budget.to_dict(),
            }

    # Should not reach here, but just in case
    return {
        "event_id": str(uuid.uuid4()),
        "run_id": run_id,
        "t": _utcnow(),
        "node_id": node.name,
        "agent_id": agent.AGENT_ID,
        "status": "failed",
        "error": "exhausted retries",
        "cost": budget.to_dict(),
    }
