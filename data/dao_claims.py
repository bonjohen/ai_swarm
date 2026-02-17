"""DAO for claims."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

_JSON_FIELDS = ("entities_json", "citations_json", "supersedes_json", "meta_json")


def insert_claim(
    conn: sqlite3.Connection,
    *,
    claim_id: str,
    scope_type: str,
    scope_id: str,
    statement: str,
    claim_type: str,
    entities: list | None = None,
    citations: list | None = None,
    evidence_strength: float | None = None,
    confidence: float | None = None,
    status: str = "active",
    first_seen_at: str,
    last_confirmed_at: str | None = None,
    supersedes: list | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO claims
           (claim_id, scope_type, scope_id, statement, claim_type,
            entities_json, citations_json, evidence_strength, confidence, status,
            first_seen_at, last_confirmed_at, supersedes_json, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            claim_id, scope_type, scope_id, statement, claim_type,
            json.dumps(entities or []), json.dumps(citations or []),
            evidence_strength, confidence, status,
            first_seen_at, last_confirmed_at,
            json.dumps(supersedes or []), json.dumps(meta or {}),
        ),
    )
    conn.commit()


def get_claim(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    if row is None:
        return None
    return _claim_row(row)


def list_claims_for_scope(
    conn: sqlite3.Connection, scope_type: str, scope_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM claims WHERE scope_type = ? AND scope_id = ? ORDER BY first_seen_at",
        (scope_type, scope_id),
    ).fetchall()
    return [_claim_row(r) for r in rows]


def update_claim_status(
    conn: sqlite3.Connection, claim_id: str, status: str, last_confirmed_at: str | None = None
) -> None:
    if last_confirmed_at:
        conn.execute(
            "UPDATE claims SET status = ?, last_confirmed_at = ? WHERE claim_id = ?",
            (status, last_confirmed_at, claim_id),
        )
    else:
        conn.execute("UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id))
    conn.commit()


def _claim_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in _JSON_FIELDS:
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d
