"""DAO for metrics and metric_points."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_metric(
    conn: sqlite3.Connection,
    *,
    metric_id: str,
    name: str,
    unit: str,
    scope_type: str,
    scope_id: str,
    dimensions: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO metrics (metric_id, name, unit, scope_type, scope_id, dimensions_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (metric_id, name, unit, scope_type, scope_id, json.dumps(dimensions or {})),
    )
    conn.commit()


def get_metric(conn: sqlite3.Connection, metric_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM metrics WHERE metric_id = ?", (metric_id,)).fetchone()
    if row is None:
        return None
    return _metric_row(row)


def list_metrics_for_scope(
    conn: sqlite3.Connection, scope_type: str, scope_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM metrics WHERE scope_type = ? AND scope_id = ?",
        (scope_type, scope_id),
    ).fetchall()
    return [_metric_row(r) for r in rows]


def insert_metric_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    metric_id: str,
    t: str,
    value: float,
    doc_id: str | None = None,
    segment_id: str | None = None,
    confidence: float | None = None,
    notes: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO metric_points
           (point_id, metric_id, t, value, doc_id, segment_id, confidence, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (point_id, metric_id, t, value, doc_id, segment_id, confidence, notes),
    )
    conn.commit()


def get_points_for_metric(conn: sqlite3.Connection, metric_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM metric_points WHERE metric_id = ? ORDER BY t", (metric_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _metric_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["dimensions_json"] = json.loads(d["dimensions_json"])
    return d
