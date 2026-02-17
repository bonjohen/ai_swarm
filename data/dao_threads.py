"""DAO for narrative_threads."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_thread(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    world_id: str,
    title: str,
    status: str = "open",
    introduced_in_episode: int,
    resolved_in_episode: int | None = None,
    thematic_tag: str = "",
    related_character_ids: list[str] | None = None,
    escalation_points: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO narrative_threads
           (thread_id, world_id, title, status, introduced_in_episode,
            resolved_in_episode, thematic_tag, related_character_ids_json,
            escalation_points_json, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            thread_id, world_id, title, status, introduced_in_episode,
            resolved_in_episode, thematic_tag,
            json.dumps(related_character_ids or []),
            json.dumps(escalation_points or []),
            json.dumps(meta or {}),
        ),
    )
    conn.commit()


def get_threads_for_world(
    conn: sqlite3.Connection, world_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM narrative_threads WHERE world_id = ? ORDER BY introduced_in_episode",
        (world_id,),
    ).fetchall()
    return [_thread_row(r) for r in rows]


def get_open_threads(
    conn: sqlite3.Connection, world_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM narrative_threads WHERE world_id = ? AND status != 'resolved' ORDER BY introduced_in_episode",
        (world_id,),
    ).fetchall()
    return [_thread_row(r) for r in rows]


def get_thread(
    conn: sqlite3.Connection, thread_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM narrative_threads WHERE thread_id = ?", (thread_id,)
    ).fetchone()
    if row is None:
        return None
    return _thread_row(row)


def resolve_thread(
    conn: sqlite3.Connection, thread_id: str, *, resolved_in_episode: int
) -> None:
    conn.execute(
        "UPDATE narrative_threads SET status = 'resolved', resolved_in_episode = ? WHERE thread_id = ?",
        (resolved_in_episode, thread_id),
    )
    conn.commit()


def add_escalation_point(
    conn: sqlite3.Connection,
    thread_id: str,
    *,
    escalation_point: dict[str, Any],
) -> None:
    row = conn.execute(
        "SELECT escalation_points_json FROM narrative_threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Thread not found: {thread_id!r}")
    points = json.loads(row["escalation_points_json"])
    points.append(escalation_point)
    conn.execute(
        "UPDATE narrative_threads SET escalation_points_json = ? WHERE thread_id = ?",
        (json.dumps(points), thread_id),
    )
    conn.commit()


def update_thread_status(
    conn: sqlite3.Connection, thread_id: str, *, status: str
) -> None:
    conn.execute(
        "UPDATE narrative_threads SET status = ? WHERE thread_id = ?",
        (status, thread_id),
    )
    conn.commit()


def _thread_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("related_character_ids_json", "escalation_points_json"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    if "meta_json" in d and isinstance(d["meta_json"], str):
        d["meta_json"] = json.loads(d["meta_json"])
    return d
