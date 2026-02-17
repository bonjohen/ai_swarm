"""DAO for learner telemetry events."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def insert_learner_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    cert_id: str,
    learner_id: str,
    event_type: str,
    objective_id: str | None = None,
    question_id: str | None = None,
    score: float | None = None,
    t: str,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO learner_events
           (event_id, cert_id, learner_id, event_type, objective_id, question_id, score, t, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, cert_id, learner_id, event_type, objective_id, question_id,
         score, t, json.dumps(meta or {})),
    )
    conn.commit()


def get_learner_events(
    conn: sqlite3.Connection,
    cert_id: str,
    learner_id: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Query learner events with optional filters."""
    query = "SELECT * FROM learner_events WHERE cert_id = ?"
    params: list[Any] = [cert_id]

    if learner_id:
        query += " AND learner_id = ?"
        params.append(learner_id)
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)

    query += " ORDER BY t DESC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_learner_summary(
    conn: sqlite3.Connection,
    cert_id: str,
    learner_id: str,
) -> dict[str, Any]:
    """Aggregate learner performance for a certification."""
    events = get_learner_events(conn, cert_id, learner_id)

    quiz_attempts = [e for e in events if e["event_type"] == "quiz_attempt"]
    module_views = [e for e in events if e["event_type"] == "module_view"]
    completions = [e for e in events if e["event_type"] == "lesson_complete"]

    scores = [e["score"] for e in quiz_attempts if e.get("score") is not None]

    return {
        "cert_id": cert_id,
        "learner_id": learner_id,
        "total_events": len(events),
        "quiz_attempts": len(quiz_attempts),
        "module_views": len(module_views),
        "lessons_completed": len(completions),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "objectives_attempted": list({
            e["objective_id"] for e in quiz_attempts if e.get("objective_id")
        }),
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if "meta_json" in d and isinstance(d["meta_json"], str):
        d["meta_json"] = json.loads(d["meta_json"])
    return d
