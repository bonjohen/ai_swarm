"""Tests for delta agent — snapshot + delta computation determinism."""

import pytest
from agents.delta_agent import DeltaAgent


@pytest.fixture
def agent():
    return DeltaAgent()


def _base_state(**overrides):
    state = {
        "scope_type": "cert",
        "scope_id": "c1",
        "run_id": "r1",
        "graph_id": "test",
        "claims": [],
        "metrics": [],
        "previous_snapshot": None,
    }
    state.update(overrides)
    return state


class TestDeltaComputation:
    def test_first_snapshot_no_previous(self, agent):
        state = _base_state(
            claims=[{"claim_id": "c1"}, {"claim_id": "c2"}],
            metrics=[{"metric_id": "m1"}],
        )
        result = agent.run(state)
        assert result["snapshot_id"]
        assert result["delta_id"]
        assert result["included_claim_ids"] == ["c1", "c2"]
        assert result["included_metric_ids"] == ["m1"]
        assert result["delta_json"]["added_claims"] == ["c1", "c2"]
        assert result["delta_json"]["removed_claims"] == []
        assert result["from_snapshot_id"] is None

    def test_delta_with_previous_snapshot(self, agent):
        prev = {
            "snapshot_id": "prev-snap",
            "included_claim_ids_json": ["c1", "c2"],
            "included_metric_ids_json": ["m1"],
        }
        state = _base_state(
            claims=[{"claim_id": "c2"}, {"claim_id": "c3"}],
            metrics=[{"metric_id": "m1"}, {"metric_id": "m2"}],
            previous_snapshot=prev,
        )
        result = agent.run(state)
        assert "c3" in result["delta_json"]["added_claims"]
        assert "c1" in result["delta_json"]["removed_claims"]
        assert "m2" in result["delta_json"]["added_metrics"]
        assert result["from_snapshot_id"] == "prev-snap"

    def test_no_changes_stability_1(self, agent):
        prev = {
            "snapshot_id": "prev-snap",
            "included_claim_ids_json": ["c1"],
            "included_metric_ids_json": ["m1"],
        }
        state = _base_state(
            claims=[{"claim_id": "c1"}],
            metrics=[{"metric_id": "m1"}],
            previous_snapshot=prev,
        )
        result = agent.run(state)
        assert result["stability_score"] == 1.0
        assert result["delta_json"]["added_claims"] == []
        assert result["delta_json"]["removed_claims"] == []

    def test_all_changed_low_stability(self, agent):
        prev = {
            "snapshot_id": "prev-snap",
            "included_claim_ids_json": ["c1", "c2"],
            "included_metric_ids_json": [],
        }
        state = _base_state(
            claims=[{"claim_id": "c3"}, {"claim_id": "c4"}],
            metrics=[],
            previous_snapshot=prev,
        )
        result = agent.run(state)
        assert result["stability_score"] < 0.5

    def test_determinism(self, agent):
        """Same input must produce same delta_json (excluding IDs which are UUIDs)."""
        state = _base_state(claims=[{"claim_id": "c1"}], metrics=[{"metric_id": "m1"}])
        r1 = agent.run(state.copy())
        r2 = agent.run(state.copy())
        assert r1["delta_json"] == r2["delta_json"]
        assert r1["stability_score"] == r2["stability_score"]
        assert r1["snapshot_hash"] == r2["snapshot_hash"]


class TestDeltaValidation:
    def test_validate_valid(self, agent):
        agent.validate({
            "snapshot_id": "s1", "delta_id": "d1",
            "delta_json": {"added_claims": []},
        })

    def test_validate_missing_snapshot_id(self, agent):
        with pytest.raises(ValueError, match="snapshot_id"):
            agent.validate({"snapshot_id": "", "delta_id": "d1", "delta_json": {}})

    def test_validate_missing_delta_json(self, agent):
        with pytest.raises(ValueError, match="delta_json must be a dict"):
            agent.validate({"snapshot_id": "s1", "delta_id": "d1", "delta_json": "not-dict"})
