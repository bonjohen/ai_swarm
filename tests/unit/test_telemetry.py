"""Tests for learner telemetry DAO."""

import sqlite3

import pytest

from data.dao_telemetry import (
    get_learner_events,
    get_learner_summary,
    insert_learner_event,
)
from data.db import init_schema


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    return c


class TestInsertAndQuery:
    def test_insert_and_retrieve(self, conn):
        insert_learner_event(
            conn,
            event_id="e1",
            cert_id="aws-101",
            learner_id="learner-1",
            event_type="quiz_attempt",
            objective_id="obj-1",
            question_id="q-1",
            score=0.8,
            t="2026-02-16T10:00:00Z",
        )
        events = get_learner_events(conn, "aws-101")
        assert len(events) == 1
        assert events[0]["event_id"] == "e1"
        assert events[0]["score"] == 0.8

    def test_filter_by_learner(self, conn):
        insert_learner_event(conn, event_id="e1", cert_id="c1", learner_id="L1",
                             event_type="quiz_attempt", t="2026-01-01T00:00:00Z")
        insert_learner_event(conn, event_id="e2", cert_id="c1", learner_id="L2",
                             event_type="quiz_attempt", t="2026-01-01T00:00:00Z")
        events = get_learner_events(conn, "c1", learner_id="L1")
        assert len(events) == 1
        assert events[0]["learner_id"] == "L1"

    def test_filter_by_event_type(self, conn):
        insert_learner_event(conn, event_id="e1", cert_id="c1", learner_id="L1",
                             event_type="quiz_attempt", t="2026-01-01T00:00:00Z")
        insert_learner_event(conn, event_id="e2", cert_id="c1", learner_id="L1",
                             event_type="module_view", t="2026-01-02T00:00:00Z")
        events = get_learner_events(conn, "c1", event_type="module_view")
        assert len(events) == 1
        assert events[0]["event_type"] == "module_view"


class TestLearnerSummary:
    def test_summary_aggregation(self, conn):
        # Quiz attempts
        insert_learner_event(conn, event_id="e1", cert_id="c1", learner_id="L1",
                             event_type="quiz_attempt", objective_id="obj-1",
                             score=0.9, t="2026-01-01T00:00:00Z")
        insert_learner_event(conn, event_id="e2", cert_id="c1", learner_id="L1",
                             event_type="quiz_attempt", objective_id="obj-2",
                             score=0.7, t="2026-01-02T00:00:00Z")
        # Module view
        insert_learner_event(conn, event_id="e3", cert_id="c1", learner_id="L1",
                             event_type="module_view", t="2026-01-03T00:00:00Z")
        # Lesson complete
        insert_learner_event(conn, event_id="e4", cert_id="c1", learner_id="L1",
                             event_type="lesson_complete", t="2026-01-04T00:00:00Z")

        summary = get_learner_summary(conn, "c1", "L1")
        assert summary["total_events"] == 4
        assert summary["quiz_attempts"] == 2
        assert summary["module_views"] == 1
        assert summary["lessons_completed"] == 1
        assert summary["avg_score"] == 0.8  # (0.9 + 0.7) / 2
        assert set(summary["objectives_attempted"]) == {"obj-1", "obj-2"}

    def test_empty_summary(self, conn):
        summary = get_learner_summary(conn, "c1", "L1")
        assert summary["total_events"] == 0
        assert summary["avg_score"] is None
