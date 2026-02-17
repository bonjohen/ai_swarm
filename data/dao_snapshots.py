"""DAO for snapshots and deltas."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    scope_type: str,
    scope_id: str,
    created_at: str,
    hash: str,
    included_claim_ids: list[str] | None = None,
    included_metric_ids: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO snapshots
           (snapshot_id, scope_type, scope_id, created_at, hash,
            included_claim_ids_json, included_metric_ids_json, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id, scope_type, scope_id, created_at, hash,
            json.dumps(included_claim_ids or []),
            json.dumps(included_metric_ids or []),
            json.dumps(meta or {}),
        ),
    )
    conn.commit()


def get_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
    if row is None:
        return None
    return _snapshot_row(row)


def get_latest_snapshot(
    conn: sqlite3.Connection, scope_type: str, scope_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM snapshots WHERE scope_type = ? AND scope_id = ? ORDER BY created_at DESC LIMIT 1",
        (scope_type, scope_id),
    ).fetchone()
    if row is None:
        return None
    return _snapshot_row(row)


def insert_delta(
    conn: sqlite3.Connection,
    *,
    delta_id: str,
    scope_type: str,
    scope_id: str,
    from_snapshot_id: str | None,
    to_snapshot_id: str,
    created_at: str,
    delta_json: dict[str, Any],
    stability_score: float | None = None,
    summary: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO deltas
           (delta_id, scope_type, scope_id, from_snapshot_id, to_snapshot_id,
            created_at, delta_json, stability_score, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            delta_id, scope_type, scope_id, from_snapshot_id, to_snapshot_id,
            created_at, json.dumps(delta_json), stability_score, summary,
        ),
    )
    conn.commit()


def get_delta(conn: sqlite3.Connection, delta_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM deltas WHERE delta_id = ?", (delta_id,)).fetchone()
    if row is None:
        return None
    return _delta_row(row)


def _snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("included_claim_ids_json", "included_metric_ids_json", "meta_json"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d


def _delta_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if isinstance(d.get("delta_json"), str):
        d["delta_json"] = json.loads(d["delta_json"])
    return d
