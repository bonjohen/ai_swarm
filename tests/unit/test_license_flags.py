"""Tests for license flags on SourceDoc."""

import sqlite3

import pytest

from data.dao_sources import (
    get_restricted_doc_ids,
    get_source_doc,
    insert_source_doc,
    update_license_flag,
)
from data.db import init_schema


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    return c


class TestLicenseFlag:
    def test_default_is_open(self, conn):
        insert_source_doc(
            conn, doc_id="d1", uri="http://example.com", source_type="web",
            retrieved_at="2026-01-01T00:00:00Z",
        )
        doc = get_source_doc(conn, "d1")
        assert doc["license_flag"] == "open"

    def test_insert_with_flag(self, conn):
        insert_source_doc(
            conn, doc_id="d1", uri="http://example.com", source_type="web",
            retrieved_at="2026-01-01T00:00:00Z", license_flag="restricted",
        )
        doc = get_source_doc(conn, "d1")
        assert doc["license_flag"] == "restricted"

    def test_update_flag(self, conn):
        insert_source_doc(
            conn, doc_id="d1", uri="http://example.com", source_type="web",
            retrieved_at="2026-01-01T00:00:00Z",
        )
        update_license_flag(conn, "d1", "no_republish")
        doc = get_source_doc(conn, "d1")
        assert doc["license_flag"] == "no_republish"

    def test_invalid_flag(self, conn):
        insert_source_doc(
            conn, doc_id="d1", uri="http://example.com", source_type="web",
            retrieved_at="2026-01-01T00:00:00Z",
        )
        with pytest.raises(ValueError, match="Invalid license_flag"):
            update_license_flag(conn, "d1", "invalid")

    def test_get_restricted_ids(self, conn):
        insert_source_doc(conn, doc_id="d1", uri="u1", source_type="web",
                          retrieved_at="2026-01-01T00:00:00Z", license_flag="open")
        insert_source_doc(conn, doc_id="d2", uri="u2", source_type="web",
                          retrieved_at="2026-01-01T00:00:00Z", license_flag="restricted")
        insert_source_doc(conn, doc_id="d3", uri="u3", source_type="web",
                          retrieved_at="2026-01-01T00:00:00Z", license_flag="no_republish")
        restricted = get_restricted_doc_ids(conn)
        assert restricted == {"d2", "d3"}

    def test_no_restricted(self, conn):
        insert_source_doc(conn, doc_id="d1", uri="u1", source_type="web",
                          retrieved_at="2026-01-01T00:00:00Z")
        assert get_restricted_doc_ids(conn) == set()


class TestPublisherLicenseCheck:
    """Test that publisher marks restricted claims."""

    def test_restricted_claims_flagged(self):
        from agents.publisher_agent import PublisherAgent

        agent = PublisherAgent()
        state = {
            "scope_type": "topic",
            "scope_id": "test-topic",
            "snapshot_id": "snap-123",
            "delta_id": "delta-123",
            "claims": [
                {"claim_id": "c1", "statement": "Claim 1",
                 "citations": [{"doc_id": "d1"}]},
                {"claim_id": "c2", "statement": "Claim 2",
                 "citations": [{"doc_id": "d2"}]},
            ],
            "_restricted_doc_ids": ["d1"],
            "qa_passed": True,
        }
        result = agent.run(state)
        # After publish, the claim citing restricted doc should be flagged
        claims = state["claims"]
        flagged = [c for c in claims if c.get("_license_restricted")]
        assert len(flagged) == 1
        assert flagged[0]["claim_id"] == "c1"
