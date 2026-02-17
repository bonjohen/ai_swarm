"""DAO for characters."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

VALID_ARC_STAGES = ("introduction", "rising", "crisis", "resolution", "transformed")

_ARC_ORDER = {stage: i for i, stage in enumerate(VALID_ARC_STAGES)}


def insert_character(
    conn: sqlite3.Connection,
    *,
    character_id: str,
    world_id: str,
    name: str,
    role: str,
    arc_stage: str = "introduction",
    alive: bool = True,
    traits: list[str] | None = None,
    goals: list[str] | None = None,
    fears: list[str] | None = None,
    beliefs: list[str] | None = None,
    voice_notes: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    if arc_stage not in VALID_ARC_STAGES:
        raise ValueError(f"Invalid arc_stage: {arc_stage!r}")
    conn.execute(
        """INSERT INTO characters
           (character_id, world_id, name, role, arc_stage, alive,
            traits_json, goals_json, fears_json, beliefs_json, voice_notes, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            character_id, world_id, name, role, arc_stage, int(alive),
            json.dumps(traits or []),
            json.dumps(goals or []),
            json.dumps(fears or []),
            json.dumps(beliefs or []),
            voice_notes,
            json.dumps(meta or {}),
        ),
    )
    conn.commit()


def get_characters_for_world(
    conn: sqlite3.Connection, world_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM characters WHERE world_id = ? ORDER BY name", (world_id,)
    ).fetchall()
    return [_char_row(r) for r in rows]


def get_character(
    conn: sqlite3.Connection, character_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM characters WHERE character_id = ?", (character_id,)
    ).fetchone()
    if row is None:
        return None
    return _char_row(row)


def update_character(
    conn: sqlite3.Connection,
    character_id: str,
    *,
    name: str | None = None,
    role: str | None = None,
    alive: bool | None = None,
    traits: list[str] | None = None,
    goals: list[str] | None = None,
    fears: list[str] | None = None,
    beliefs: list[str] | None = None,
    voice_notes: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    parts: list[str] = []
    params: list[Any] = []
    if name is not None:
        parts.append("name = ?")
        params.append(name)
    if role is not None:
        parts.append("role = ?")
        params.append(role)
    if alive is not None:
        parts.append("alive = ?")
        params.append(int(alive))
    if traits is not None:
        parts.append("traits_json = ?")
        params.append(json.dumps(traits))
    if goals is not None:
        parts.append("goals_json = ?")
        params.append(json.dumps(goals))
    if fears is not None:
        parts.append("fears_json = ?")
        params.append(json.dumps(fears))
    if beliefs is not None:
        parts.append("beliefs_json = ?")
        params.append(json.dumps(beliefs))
    if voice_notes is not None:
        parts.append("voice_notes = ?")
        params.append(voice_notes)
    if meta is not None:
        parts.append("meta_json = ?")
        params.append(json.dumps(meta))
    if not parts:
        return
    params.append(character_id)
    conn.execute(
        f"UPDATE characters SET {', '.join(parts)} WHERE character_id = ?", params
    )
    conn.commit()


def update_arc_stage(
    conn: sqlite3.Connection, character_id: str, new_stage: str
) -> None:
    if new_stage not in VALID_ARC_STAGES:
        raise ValueError(f"Invalid arc_stage: {new_stage!r}")
    row = conn.execute(
        "SELECT arc_stage FROM characters WHERE character_id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Character not found: {character_id!r}")
    current = row["arc_stage"]
    if _ARC_ORDER[new_stage] != _ARC_ORDER[current] + 1:
        raise ValueError(
            f"Invalid arc transition: {current!r} -> {new_stage!r} "
            f"(must advance exactly one stage)"
        )
    conn.execute(
        "UPDATE characters SET arc_stage = ? WHERE character_id = ?",
        (new_stage, character_id),
    )
    conn.commit()


def _char_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["alive"] = bool(d["alive"])
    for key in ("traits_json", "goals_json", "fears_json", "beliefs_json"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    if "meta_json" in d and isinstance(d["meta_json"], str):
        d["meta_json"] = json.loads(d["meta_json"])
    return d
