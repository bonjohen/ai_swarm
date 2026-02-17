"""Tests for data.dao_snapshots."""

import pytest
from data.db import get_initialized_connection
from data.dao_snapshots import (
    insert_snapshot,
    get_snapshot,
    get_latest_snapshot,
    insert_delta,
    get_delta,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


def test_insert_and_get_snapshot(conn):
    insert_snapshot(
        conn, snapshot_id="snap-1", scope_type="cert", scope_id="x",
        created_at="2026-01-01", hash="abc123",
        included_claim_ids=["c1", "c2"],
    )
    s = get_snapshot(conn, "snap-1")
    assert s is not None
    assert s["hash"] == "abc123"
    assert s["included_claim_ids_json"] == ["c1", "c2"]


def test_get_latest_snapshot(conn):
    insert_snapshot(conn, snapshot_id="s1", scope_type="cert", scope_id="x", created_at="2026-01-01", hash="a")
    insert_snapshot(conn, snapshot_id="s2", scope_type="cert", scope_id="x", created_at="2026-02-01", hash="b")
    latest = get_latest_snapshot(conn, "cert", "x")
    assert latest["snapshot_id"] == "s2"


def test_get_latest_snapshot_none(conn):
    assert get_latest_snapshot(conn, "cert", "nonexistent") is None


def test_insert_and_get_delta(conn):
    insert_snapshot(conn, snapshot_id="s1", scope_type="cert", scope_id="x", created_at="2026-01-01", hash="a")
    insert_snapshot(conn, snapshot_id="s2", scope_type="cert", scope_id="x", created_at="2026-02-01", hash="b")
    insert_delta(
        conn, delta_id="d1", scope_type="cert", scope_id="x",
        from_snapshot_id="s1", to_snapshot_id="s2",
        created_at="2026-02-01",
        delta_json={"added_claims": ["c3"], "removed_claims": []},
        stability_score=0.85,
        summary="One claim added",
    )
    d = get_delta(conn, "d1")
    assert d is not None
    assert d["delta_json"]["added_claims"] == ["c3"]
    assert d["stability_score"] == 0.85
