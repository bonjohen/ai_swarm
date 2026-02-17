"""Tests for full budget enforcement — degradation, per-node caps, human review."""

import time

import pytest

from core.budgets import BudgetLedger, DegradationHint
from core.errors import BudgetExceededError


class TestBudgetEnforcement:
    def test_run_level_token_cap(self):
        b = BudgetLedger(max_tokens=100)
        b.record(tokens_in=60, tokens_out=50)
        with pytest.raises(BudgetExceededError, match="tokens"):
            b.check()

    def test_run_level_cost_cap(self):
        b = BudgetLedger(max_cost_usd=1.0)
        b.record(cost_usd=1.5)
        with pytest.raises(BudgetExceededError, match="cost_usd"):
            b.check()

    def test_per_node_token_cap(self):
        b = BudgetLedger()
        b.record(tokens_in=50, tokens_out=50)
        with pytest.raises(BudgetExceededError, match="node_tokens"):
            b.check(node_budget={"max_tokens": 80})

    def test_per_node_cost_cap(self):
        b = BudgetLedger()
        b.record(cost_usd=0.5)
        with pytest.raises(BudgetExceededError, match="node_cost"):
            b.check(node_budget={"max_cost": 0.3})

    def test_no_cap_no_raise(self):
        b = BudgetLedger()
        b.record(tokens_in=1_000_000, cost_usd=100.0)
        b.check()  # Should not raise — all caps are 0 (unlimited)


class TestDegradation:
    def test_degradation_activates_near_limit(self):
        b = BudgetLedger(max_tokens=100, degrade_at_fraction=0.8)
        b.record(tokens_in=45, tokens_out=40)  # total=85, 85% > 80%
        b.check()
        assert b.degradation_active is True

    def test_degradation_hint(self):
        b = BudgetLedger(max_tokens=100, degrade_at_fraction=0.8)
        b.record(tokens_in=45, tokens_out=40)
        b.check()
        hint = b.get_degradation_hint()
        assert hint is not None
        assert hint.max_sources == 3
        assert hint.max_questions == 5
        assert hint.skip_deep_synthesis is True
        assert "tokens" in hint.reason

    def test_no_degradation_below_threshold(self):
        b = BudgetLedger(max_tokens=100, degrade_at_fraction=0.8)
        b.record(tokens_in=20, tokens_out=20)  # total=40, 40% < 80%
        b.check()
        assert b.degradation_active is False
        assert b.get_degradation_hint() is None

    def test_cost_degradation(self):
        b = BudgetLedger(max_cost_usd=10.0, degrade_at_fraction=0.8)
        b.record(cost_usd=8.5)  # 85% > 80%
        b.check()
        assert b.degradation_active is True
        assert "cost" in b.get_degradation_hint().reason


class TestHumanReview:
    def test_flag_human_review(self):
        b = BudgetLedger()
        assert b.needs_human_review is False
        b.flag_human_review("Budget too high")
        assert b.needs_human_review is True
        assert "Budget too high" in b.get_human_review_reasons()

    def test_multiple_flags(self):
        b = BudgetLedger()
        b.flag_human_review("Reason 1")
        b.flag_human_review("Reason 2")
        assert len(b.get_human_review_reasons()) == 2


class TestNodeCostTracking:
    def test_per_node_recording(self):
        b = BudgetLedger()
        b.record(tokens_in=10, tokens_out=5, cost_usd=0.01, node_id="node_a")
        b.record(tokens_in=20, tokens_out=10, cost_usd=0.02, node_id="node_b")
        b.record(tokens_in=5, tokens_out=3, cost_usd=0.005, node_id="node_a")

        a_cost = b.node_cost("node_a")
        assert a_cost["tokens_in"] == 15
        assert a_cost["tokens_out"] == 8

        b_cost = b.node_cost("node_b")
        assert b_cost["tokens_in"] == 20

    def test_unknown_node(self):
        b = BudgetLedger()
        cost = b.node_cost("nonexistent")
        assert cost["tokens_in"] == 0


class TestToDict:
    def test_includes_new_fields(self):
        b = BudgetLedger()
        b.record(tokens_in=10)
        d = b.to_dict()
        assert "degradation_active" in d
        assert "needs_human_review" in d
