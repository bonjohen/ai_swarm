"""Tests for claim lifecycle management."""

import pytest

from agents.contradiction_agent import CLAIM_STATUSES, transition_claim_status


class TestClaimLifecycle:
    def test_valid_statuses(self):
        assert "active" in CLAIM_STATUSES
        assert "disputed" in CLAIM_STATUSES
        assert "superseded" in CLAIM_STATUSES
        assert "archived" in CLAIM_STATUSES

    def test_active_to_disputed(self):
        claim = {"claim_id": "c1", "status": "active"}
        updated = transition_claim_status(claim, "disputed", reason="Contradiction found")
        assert updated["status"] == "disputed"
        assert updated["status_history"][0]["from"] == "active"
        assert updated["status_history"][0]["to"] == "disputed"

    def test_active_to_superseded(self):
        claim = {"claim_id": "c1", "status": "active"}
        updated = transition_claim_status(claim, "superseded")
        assert updated["status"] == "superseded"

    def test_active_to_archived(self):
        claim = {"claim_id": "c1", "status": "active"}
        updated = transition_claim_status(claim, "archived")
        assert updated["status"] == "archived"

    def test_disputed_to_active(self):
        claim = {"claim_id": "c1", "status": "disputed"}
        updated = transition_claim_status(claim, "active", reason="Resolved")
        assert updated["status"] == "active"

    def test_disputed_to_superseded(self):
        claim = {"claim_id": "c1", "status": "disputed"}
        updated = transition_claim_status(claim, "superseded")
        assert updated["status"] == "superseded"

    def test_superseded_to_archived(self):
        claim = {"claim_id": "c1", "status": "superseded"}
        updated = transition_claim_status(claim, "archived")
        assert updated["status"] == "archived"

    def test_archived_is_terminal(self):
        claim = {"claim_id": "c1", "status": "archived"}
        with pytest.raises(ValueError, match="Cannot transition"):
            transition_claim_status(claim, "active")

    def test_invalid_status(self):
        claim = {"claim_id": "c1", "status": "active"}
        with pytest.raises(ValueError, match="Invalid claim status"):
            transition_claim_status(claim, "deleted")

    def test_superseded_cannot_go_back_to_active(self):
        claim = {"claim_id": "c1", "status": "superseded"}
        with pytest.raises(ValueError, match="Cannot transition"):
            transition_claim_status(claim, "active")

    def test_does_not_mutate_original(self):
        claim = {"claim_id": "c1", "status": "active"}
        updated = transition_claim_status(claim, "disputed")
        assert claim["status"] == "active"  # Original unchanged
        assert updated["status"] == "disputed"

    def test_history_accumulates(self):
        claim = {"claim_id": "c1", "status": "active"}
        claim = transition_claim_status(claim, "disputed", reason="Conflict")
        claim = transition_claim_status(claim, "active", reason="Resolved")
        assert len(claim["status_history"]) == 2
