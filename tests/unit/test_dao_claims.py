"""Tests for data.dao_claims."""

import pytest
from data.db import get_initialized_connection
from data.dao_claims import (
    insert_claim,
    get_claim,
    list_claims_for_scope,
    update_claim_status,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


def test_insert_and_get_claim(conn):
    insert_claim(
        conn,
        claim_id="c1",
        scope_type="cert",
        scope_id="cert-100",
        statement="Cloud is scalable",
        claim_type="factual",
        citations=[{"doc_id": "d1", "segment_id": "s1"}],
        confidence=0.95,
        first_seen_at="2026-01-01T00:00:00Z",
    )
    c = get_claim(conn, "c1")
    assert c is not None
    assert c["statement"] == "Cloud is scalable"
    assert c["citations_json"] == [{"doc_id": "d1", "segment_id": "s1"}]
    assert c["confidence"] == 0.95
    assert c["status"] == "active"


def test_list_claims_for_scope(conn):
    insert_claim(conn, claim_id="c1", scope_type="cert", scope_id="x", statement="A", claim_type="f", first_seen_at="2026-01-01")
    insert_claim(conn, claim_id="c2", scope_type="cert", scope_id="x", statement="B", claim_type="f", first_seen_at="2026-01-02")
    insert_claim(conn, claim_id="c3", scope_type="cert", scope_id="y", statement="C", claim_type="f", first_seen_at="2026-01-01")
    claims = list_claims_for_scope(conn, "cert", "x")
    assert len(claims) == 2


def test_update_claim_status(conn):
    insert_claim(conn, claim_id="c1", scope_type="cert", scope_id="x", statement="A", claim_type="f", first_seen_at="2026-01-01")
    update_claim_status(conn, "c1", "disputed", last_confirmed_at="2026-02-01")
    c = get_claim(conn, "c1")
    assert c["status"] == "disputed"
    assert c["last_confirmed_at"] == "2026-02-01"
