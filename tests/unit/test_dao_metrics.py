"""Tests for data.dao_metrics."""

import pytest
from data.db import get_initialized_connection
from data.dao_metrics import (
    insert_metric,
    get_metric,
    list_metrics_for_scope,
    insert_metric_point,
    get_points_for_metric,
)


@pytest.fixture
def conn():
    c = get_initialized_connection(":memory:")
    yield c
    c.close()


def test_insert_and_get_metric(conn):
    insert_metric(
        conn, metric_id="m1", name="latency", unit="ms",
        scope_type="lab", scope_id="suite-1", dimensions={"model": "gpt-4"},
    )
    m = get_metric(conn, "m1")
    assert m is not None
    assert m["name"] == "latency"
    assert m["dimensions_json"] == {"model": "gpt-4"}


def test_list_metrics_for_scope(conn):
    insert_metric(conn, metric_id="m1", name="a", unit="ms", scope_type="lab", scope_id="s1")
    insert_metric(conn, metric_id="m2", name="b", unit="pct", scope_type="lab", scope_id="s1")
    assert len(list_metrics_for_scope(conn, "lab", "s1")) == 2


def test_insert_and_get_metric_points(conn):
    insert_metric(conn, metric_id="m1", name="a", unit="ms", scope_type="lab", scope_id="s1")
    insert_metric_point(conn, point_id="p1", metric_id="m1", t="2026-01-01", value=42.0)
    insert_metric_point(conn, point_id="p2", metric_id="m1", t="2026-01-02", value=43.0)
    pts = get_points_for_metric(conn, "m1")
    assert len(pts) == 2
    assert pts[0]["value"] == 42.0
    assert pts[1]["value"] == 43.0
