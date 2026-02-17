"""DAO for episodes."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_episode(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    world_id: str,
    episode_number: int,
    title: str = "",
    act_structure: list[dict[str, Any]] | None = None,
    scene_count: int = 0,
    word_count: int = 0,
    tension_curve: list[dict[str, Any]] | None = None,
    snapshot_id: str | None = None,
    run_id: str | None = None,
    status: str = "draft",
    created_at: str,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO episodes
           (episode_id, world_id, episode_number, title, act_structure_json,
            scene_count, word_count, tension_curve_json, snapshot_id, run_id,
            status, created_at, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            episode_id, world_id, episode_number, title,
            json.dumps(act_structure or []),
            scene_count, word_count,
            json.dumps(tension_curve or []),
            snapshot_id, run_id, status, created_at,
            json.dumps(meta or {}),
        ),
    )
    conn.commit()


def get_episodes_for_world(
    conn: sqlite3.Connection, world_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM episodes WHERE world_id = ? ORDER BY episode_number",
        (world_id,),
    ).fetchall()
    return [_episode_row(r) for r in rows]


def get_latest_episode(
    conn: sqlite3.Connection, world_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM episodes WHERE world_id = ? ORDER BY episode_number DESC LIMIT 1",
        (world_id,),
    ).fetchone()
    if row is None:
        return None
    return _episode_row(row)


def get_episode(
    conn: sqlite3.Connection, episode_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)
    ).fetchone()
    if row is None:
        return None
    return _episode_row(row)


def update_episode_status(
    conn: sqlite3.Connection, episode_id: str, *, status: str
) -> None:
    conn.execute(
        "UPDATE episodes SET status = ? WHERE episode_id = ?",
        (status, episode_id),
    )
    conn.commit()


def update_episode(
    conn: sqlite3.Connection,
    episode_id: str,
    *,
    title: str | None = None,
    act_structure: list[dict[str, Any]] | None = None,
    scene_count: int | None = None,
    word_count: int | None = None,
    tension_curve: list[dict[str, Any]] | None = None,
    snapshot_id: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    parts: list[str] = []
    params: list[Any] = []
    if title is not None:
        parts.append("title = ?")
        params.append(title)
    if act_structure is not None:
        parts.append("act_structure_json = ?")
        params.append(json.dumps(act_structure))
    if scene_count is not None:
        parts.append("scene_count = ?")
        params.append(scene_count)
    if word_count is not None:
        parts.append("word_count = ?")
        params.append(word_count)
    if tension_curve is not None:
        parts.append("tension_curve_json = ?")
        params.append(json.dumps(tension_curve))
    if snapshot_id is not None:
        parts.append("snapshot_id = ?")
        params.append(snapshot_id)
    if run_id is not None:
        parts.append("run_id = ?")
        params.append(run_id)
    if status is not None:
        parts.append("status = ?")
        params.append(status)
    if meta is not None:
        parts.append("meta_json = ?")
        params.append(json.dumps(meta))
    if not parts:
        return
    params.append(episode_id)
    conn.execute(
        f"UPDATE episodes SET {', '.join(parts)} WHERE episode_id = ?", params
    )
    conn.commit()


def _episode_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("act_structure_json", "tension_curve_json"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    if "meta_json" in d and isinstance(d["meta_json"], str):
        d["meta_json"] = json.loads(d["meta_json"])
    return d
