"""Graph Runner — executes graph definitions, manages state, enforces budgets."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from agents.base_agent import BaseAgent
from agents.registry import get_agent
from core.budgets import BudgetLedger
from core.errors import (
    AgentValidationError,
    GraphError,
    MissingStateError,
    NodeError,
)
from core.state import merge_delta, validate_state
from graphs.graph_types import Graph, GraphNode

logger = logging.getLogger(__name__)


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


def execute_graph(
    graph: Graph,
    state: dict[str, Any],
    *,
    model_call: Any = None,
    budget: BudgetLedger | None = None,
    on_event: Any = None,
) -> RunResult:
    """Run a full graph to completion.

    Args:
        graph: The graph definition to execute.
        state: Initial run state dict (must contain required keys).
        model_call: callable(system_prompt, user_message) -> str
        budget: Optional BudgetLedger for cost tracking/enforcement.
        on_event: Optional callable(event_dict) for observability.

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

    while current_node_name is not None:
        node = graph.get_node(current_node_name)
        event = _execute_node(
            node=node,
            graph=graph,
            state=state,
            model_call=model_call,
            budget=budget,
            run_id=run_id,
        )
        events.append(event)
        if on_event:
            on_event(event)

        if event["status"] == "success":
            if node.end:
                current_node_name = None
            else:
                current_node_name = node.next
        elif event["status"] == "failed":
            if node.on_fail:
                logger.warning("Node '%s' failed, routing to on_fail '%s'", node.name, node.on_fail)
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
    budget: BudgetLedger,
    run_id: str,
) -> dict[str, Any]:
    """Execute a single graph node with retry logic.

    Returns an event dict describing the outcome.
    """
    agent: BaseAgent = get_agent(node.agent)
    attempts = max(node.retry.max_attempts, 1)

    for attempt in range(1, attempts + 1):
        event_id = str(uuid.uuid4())
        started = _utcnow()

        try:
            # 1. Validate inputs exist in state
            missing = [k for k in node.inputs if k not in state]
            if missing:
                raise MissingStateError(node.name, missing)

            # 2. Check budget
            budget.check()

            # 3. Execute agent
            delta_state = agent.run(state, model_call=model_call)

            # 4. Output schema validation is done inside agent.run() via validate()

            # 5. Merge delta_state into state
            merge_delta(state, delta_state)

            # 6. Emit success event
            return {
                "event_id": event_id,
                "run_id": run_id,
                "t": started,
                "node_id": node.name,
                "agent_id": agent.AGENT_ID,
                "status": "success",
                "attempt": attempt,
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
