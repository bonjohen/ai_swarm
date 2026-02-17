"""Tests for data.dao_entities."""

import pytest
from data.db import get_initialized_connection
from data.dao_entities import (
    insert_entity,
    get_entity,
    list_entities,
    update_entity,
    insert_relationship,
    get_relationships_for_entity,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


def test_insert_and_get_entity(conn):
    insert_entity(conn, entity_id="e1", type="vendor", names=["Acme", "ACME Corp"])
    e = get_entity(conn, "e1")
    assert e is not None
    assert e["type"] == "vendor"
    assert e["names_json"] == ["Acme", "ACME Corp"]


def test_get_missing_entity(conn):
    assert get_entity(conn, "nope") is None


def test_list_entities_by_type(conn):
    insert_entity(conn, entity_id="e1", type="vendor")
    insert_entity(conn, entity_id="e2", type="product")
    insert_entity(conn, entity_id="e3", type="vendor")
    assert len(list_entities(conn, type="vendor")) == 2
    assert len(list_entities(conn)) == 3


def test_update_entity(conn):
    insert_entity(conn, entity_id="e1", type="vendor", names=["Old"])
    update_entity(conn, "e1", names=["New"])
    e = get_entity(conn, "e1")
    assert e["names_json"] == ["New"]


def test_insert_and_get_relationship(conn):
    insert_entity(conn, entity_id="e1", type="vendor")
    insert_entity(conn, entity_id="e2", type="product")
    insert_relationship(conn, rel_id="r1", type="produces", from_id="e1", to_id="e2", confidence=0.9)
    rels = get_relationships_for_entity(conn, "e1")
    assert len(rels) == 1
    assert rels[0]["type"] == "produces"
    assert rels[0]["confidence"] == 0.9
