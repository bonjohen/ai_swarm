"""Tests for data.dao_sources."""

import pytest
from data.db import get_initialized_connection
from data.dao_sources import (
    insert_source_doc,
    get_source_doc,
    list_source_docs,
    insert_source_segment,
    get_segments_for_doc,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


def test_insert_and_get_source_doc(conn):
    insert_source_doc(
        conn,
        doc_id="doc-1",
        uri="https://example.com/a",
        source_type="web",
        retrieved_at="2026-01-01T00:00:00Z",
        title="Test Doc",
    )
    doc = get_source_doc(conn, "doc-1")
    assert doc is not None
    assert doc["doc_id"] == "doc-1"
    assert doc["uri"] == "https://example.com/a"
    assert doc["source_type"] == "web"
    assert doc["title"] == "Test Doc"
    assert doc["meta_json"] == {}


def test_get_missing_doc_returns_none(conn):
    assert get_source_doc(conn, "nonexistent") is None


def test_list_source_docs(conn):
    insert_source_doc(conn, doc_id="d1", uri="u1", source_type="web", retrieved_at="2026-01-01T00:00:00Z")
    insert_source_doc(conn, doc_id="d2", uri="u2", source_type="rss", retrieved_at="2026-01-02T00:00:00Z")
    docs = list_source_docs(conn)
    assert len(docs) == 2
    assert docs[0]["doc_id"] == "d2"  # most recent first


def test_insert_and_get_segments(conn):
    insert_source_doc(conn, doc_id="doc-1", uri="u", source_type="web", retrieved_at="2026-01-01T00:00:00Z")
    insert_source_segment(conn, segment_id="seg-1", doc_id="doc-1", idx=0, text_path="/tmp/seg1.txt")
    insert_source_segment(conn, segment_id="seg-2", doc_id="doc-1", idx=1, text_path="/tmp/seg2.txt")
    segs = get_segments_for_doc(conn, "doc-1")
    assert len(segs) == 2
    assert segs[0]["idx"] == 0
    assert segs[1]["idx"] == 1


def test_source_doc_with_meta(conn):
    insert_source_doc(
        conn, doc_id="d1", uri="u", source_type="web", retrieved_at="2026-01-01T00:00:00Z",
        meta={"key": "value"},
    )
    doc = get_source_doc(conn, "d1")
    assert doc["meta_json"] == {"key": "value"}
