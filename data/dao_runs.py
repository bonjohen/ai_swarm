"""DAO for runs and run_events."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    scope_type: str,
    scope_id: str,
    graph_id: str,
    started_at: str,
    status: str = "running",
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO runs
           (run_id, scope_type, scope_id, graph_id, started_at, status, cost_json, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, '{}', ?)""",
        (run_id, scope_type, scope_id, graph_id, started_at, status, json.dumps(meta or {})),
    )
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return _run_row(row)


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    ended_at: str,
    status: str,
    cost: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "UPDATE runs SET ended_at = ?, status = ?, cost_json = ? WHERE run_id = ?",
        (ended_at, status, json.dumps(cost or {}), run_id),
    )
    conn.commit()


def insert_run_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    run_id: str,
    t: str,
    node_id: str,
    agent_id: str,
    status: str,
    cost: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO run_events
           (event_id, run_id, t, node_id, agent_id, status, cost_json, payload_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, run_id, t, node_id, agent_id, status, json.dumps(cost or {}), json.dumps(payload or {})),
    )
    conn.commit()


def get_events_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM run_events WHERE run_id = ? ORDER BY t", (run_id,)
    ).fetchall()
    return [_event_row(r) for r in rows]


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    """List recent runs, newest first."""
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_run_row(r) for r in rows]


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("cost_json", "meta_json"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("cost_json", "payload_json"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d
