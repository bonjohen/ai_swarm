"""DAO for story_worlds."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_world(
    conn: sqlite3.Connection,
    *,
    world_id: str,
    name: str,
    genre: str,
    tone: str,
    setting: dict[str, Any] | None = None,
    thematic_constraints: list[str] | None = None,
    audience_profile: dict[str, Any] | None = None,
    current_episode_number: int = 0,
    current_timeline_position: str = "start",
    created_at: str,
    updated_at: str,
) -> None:
    conn.execute(
        """INSERT INTO story_worlds
           (world_id, name, genre, tone, setting_json, thematic_constraints_json,
            audience_profile_json, current_episode_number, current_timeline_position,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            world_id, name, genre, tone,
            json.dumps(setting or {}),
            json.dumps(thematic_constraints or []),
            json.dumps(audience_profile or {}),
            current_episode_number,
            current_timeline_position,
            created_at, updated_at,
        ),
    )
    conn.commit()


def get_world(conn: sqlite3.Connection, world_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM story_worlds WHERE world_id = ?", (world_id,)
    ).fetchone()
    if row is None:
        return None
    return _world_row(row)


def update_world(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    name: str | None = None,
    genre: str | None = None,
    tone: str | None = None,
    setting: dict[str, Any] | None = None,
    thematic_constraints: list[str] | None = None,
    audience_profile: dict[str, Any] | None = None,
    current_timeline_position: str | None = None,
    updated_at: str | None = None,
) -> None:
    parts: list[str] = []
    params: list[Any] = []
    if name is not None:
        parts.append("name = ?")
        params.append(name)
    if genre is not None:
        parts.append("genre = ?")
        params.append(genre)
    if tone is not None:
        parts.append("tone = ?")
        params.append(tone)
    if setting is not None:
        parts.append("setting_json = ?")
        params.append(json.dumps(setting))
    if thematic_constraints is not None:
        parts.append("thematic_constraints_json = ?")
        params.append(json.dumps(thematic_constraints))
    if audience_profile is not None:
        parts.append("audience_profile_json = ?")
        params.append(json.dumps(audience_profile))
    if current_timeline_position is not None:
        parts.append("current_timeline_position = ?")
        params.append(current_timeline_position)
    if updated_at is not None:
        parts.append("updated_at = ?")
        params.append(updated_at)
    if not parts:
        return
    params.append(world_id)
    conn.execute(
        f"UPDATE story_worlds SET {', '.join(parts)} WHERE world_id = ?", params
    )
    conn.commit()


def increment_episode_number(conn: sqlite3.Connection, world_id: str) -> int:
    conn.execute(
        "UPDATE story_worlds SET current_episode_number = current_episode_number + 1 WHERE world_id = ?",
        (world_id,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT current_episode_number FROM story_worlds WHERE world_id = ?",
        (world_id,),
    ).fetchone()
    return row["current_episode_number"]


def _world_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("setting_json", "audience_profile_json"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    for key in ("thematic_constraints_json",):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d
