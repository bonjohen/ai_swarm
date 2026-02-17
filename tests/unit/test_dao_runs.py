"""Tests for data.dao_runs."""

import pytest
from data.db import get_initialized_connection
from data.dao_runs import (
    insert_run,
    get_run,
    finish_run,
    insert_run_event,
    get_events_for_run,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


def test_insert_and_get_run(conn):
    insert_run(
        conn, run_id="r1", scope_type="cert", scope_id="cert-1",
        graph_id="certification_graph", started_at="2026-01-01T00:00:00Z",
    )
    r = get_run(conn, "r1")
    assert r is not None
    assert r["status"] == "running"
    assert r["graph_id"] == "certification_graph"


def test_finish_run(conn):
    insert_run(conn, run_id="r1", scope_type="cert", scope_id="x", graph_id="g", started_at="2026-01-01")
    finish_run(conn, "r1", ended_at="2026-01-01T01:00:00Z", status="completed", cost={"tokens": 1000})
    r = get_run(conn, "r1")
    assert r["status"] == "completed"
    assert r["cost_json"]["tokens"] == 1000


def test_run_events(conn):
    insert_run(conn, run_id="r1", scope_type="cert", scope_id="x", graph_id="g", started_at="2026-01-01")
    insert_run_event(
        conn, event_id="ev1", run_id="r1", t="2026-01-01T00:01:00Z",
        node_id="ingest", agent_id="ingestor", status="success",
    )
    insert_run_event(
        conn, event_id="ev2", run_id="r1", t="2026-01-01T00:02:00Z",
        node_id="normalize", agent_id="normalizer", status="success",
    )
    events = get_events_for_run(conn, "r1")
    assert len(events) == 2
    assert events[0]["node_id"] == "ingest"
    assert events[1]["node_id"] == "normalize"
