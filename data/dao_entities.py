"""DAO for entities and relationships."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_entity(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    type: str,
    names: list[str] | None = None,
    props: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO entities (entity_id, type, names_json, props_json)
           VALUES (?, ?, ?, ?)""",
        (entity_id, type, json.dumps(names or []), json.dumps(props or {})),
    )
    conn.commit()


def get_entity(conn: sqlite3.Connection, entity_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
    if row is None:
        return None
    return _entity_row(row)


def list_entities(conn: sqlite3.Connection, type: str | None = None) -> list[dict[str, Any]]:
    if type:
        rows = conn.execute("SELECT * FROM entities WHERE type = ?", (type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM entities").fetchall()
    return [_entity_row(r) for r in rows]


def update_entity(
    conn: sqlite3.Connection,
    entity_id: str,
    *,
    names: list[str] | None = None,
    props: dict[str, Any] | None = None,
) -> None:
    parts, params = [], []
    if names is not None:
        parts.append("names_json = ?")
        params.append(json.dumps(names))
    if props is not None:
        parts.append("props_json = ?")
        params.append(json.dumps(props))
    if not parts:
        return
    params.append(entity_id)
    conn.execute(f"UPDATE entities SET {', '.join(parts)} WHERE entity_id = ?", params)
    conn.commit()


def insert_relationship(
    conn: sqlite3.Connection,
    *,
    rel_id: str,
    type: str,
    from_id: str,
    to_id: str,
    confidence: float | None = None,
    citations: list[dict] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO relationships (rel_id, type, from_id, to_id, confidence, citations_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rel_id, type, from_id, to_id, confidence, json.dumps(citations or [])),
    )
    conn.commit()


def get_relationships_for_entity(conn: sqlite3.Connection, entity_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM relationships WHERE from_id = ? OR to_id = ?",
        (entity_id, entity_id),
    ).fetchall()
    return [_rel_row(r) for r in rows]


def _entity_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["names_json"] = json.loads(d["names_json"])
    d["props_json"] = json.loads(d["props_json"])
    return d


def _rel_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["citations_json"] = json.loads(d["citations_json"])
    return d
