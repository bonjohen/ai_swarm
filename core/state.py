"""Run state management — dict-based state persisted between nodes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_KEYS = {"scope_type", "scope_id", "run_id", "graph_id"}


def create_initial_state(
    *,
    scope_type: str,
    scope_id: str,
    run_id: str,
    graph_id: str,
    budget: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the initial state dict for a graph run."""
    state: dict[str, Any] = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "run_id": run_id,
        "graph_id": graph_id,
        "budget": budget or {},
        "artifacts": [],
    }
    if extra:
        state.update(extra)
    return state


def validate_state(state: dict[str, Any]) -> list[str]:
    """Return list of missing required keys (empty if valid)."""
    return [k for k in REQUIRED_KEYS if k not in state]


def merge_delta(state: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """Merge delta_state into state (shallow merge). Returns updated state."""
    state.update(delta)
    return state


def save_state(state: dict[str, Any], path: Path | str) -> None:
    """Persist state to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))


def load_state(path: Path | str) -> dict[str, Any]:
    """Load state from a JSON file."""
    return json.loads(Path(path).read_text())
