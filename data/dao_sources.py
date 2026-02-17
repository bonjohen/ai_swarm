"""DAO for source_docs and source_segments."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_source_doc(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    uri: str,
    source_type: str,
    retrieved_at: str,
    published_at: str | None = None,
    title: str | None = None,
    content_hash: str | None = None,
    text_path: str | None = None,
    license_flag: str = "open",
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO source_docs
           (doc_id, uri, source_type, retrieved_at, published_at, title, content_hash, text_path, license_flag, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (doc_id, uri, source_type, retrieved_at, published_at, title, content_hash,
         text_path, license_flag, json.dumps(meta or {})),
    )
    conn.commit()


def update_license_flag(
    conn: sqlite3.Connection,
    doc_id: str,
    license_flag: str,
) -> None:
    """Update the license flag for a source document.

    Valid flags: 'open', 'restricted', 'no_republish'
    """
    if license_flag not in ("open", "restricted", "no_republish"):
        raise ValueError(f"Invalid license_flag: {license_flag!r}")
    conn.execute(
        "UPDATE source_docs SET license_flag = ? WHERE doc_id = ?",
        (license_flag, doc_id),
    )
    conn.commit()


def get_restricted_doc_ids(conn: sqlite3.Connection) -> set[str]:
    """Return doc_ids that have a restrictive license flag."""
    rows = conn.execute(
        "SELECT doc_id FROM source_docs WHERE license_flag IN ('restricted', 'no_republish')"
    ).fetchall()
    return {row["doc_id"] for row in rows}


def get_source_doc(conn: sqlite3.Connection, doc_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM source_docs WHERE doc_id = ?", (doc_id,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_source_docs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM source_docs ORDER BY retrieved_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def insert_source_segment(
    conn: sqlite3.Connection,
    *,
    segment_id: str,
    doc_id: str,
    idx: int,
    text_path: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO source_segments (segment_id, doc_id, idx, text_path, meta_json)
           VALUES (?, ?, ?, ?, ?)""",
        (segment_id, doc_id, idx, text_path, json.dumps(meta or {})),
    )
    conn.commit()


def get_segments_for_doc(conn: sqlite3.Connection, doc_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM source_segments WHERE doc_id = ? ORDER BY idx", (doc_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("meta_json",):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d
