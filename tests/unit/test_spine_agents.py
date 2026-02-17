"""Tests for spine agents — parse/validate with sample inputs."""

import json
import uuid

import pytest

from agents.ingestor_agent import IngestorAgent
from agents.normalizer_agent import NormalizerAgent
from agents.entity_resolver_agent import EntityResolverAgent
from agents.claim_extractor_agent import ClaimExtractorAgent
from agents.metric_extractor_agent import MetricExtractorAgent
from agents.contradiction_agent import ContradictionAgent


# --- Ingestor ---

class TestIngestor:
    def setup_method(self):
        self.agent = IngestorAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "doc_ids": ["d1"],
            "segment_ids": ["s1", "s2"],
            "source_docs": [{"doc_id": "d1", "uri": "http://x"}],
            "source_segments": [{"segment_id": "s1"}, {"segment_id": "s2"}],
        })
        result = self.agent.parse(resp)
        assert result["doc_ids"] == ["d1"]
        assert len(result["segment_ids"]) == 2

    def test_validate_valid(self):
        self.agent.validate({"doc_ids": ["d1"], "segment_ids": ["s1"]})

    def test_validate_bad_doc_ids(self):
        with pytest.raises(ValueError, match="doc_ids must be a list"):
            self.agent.validate({"doc_ids": "not-a-list", "segment_ids": []})

    def test_segment_text(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        segs = IngestorAgent.segment_text("doc1", text, max_chars=20)
        assert len(segs) >= 2
        assert all(s["doc_id"] == "doc1" for s in segs)

    def test_make_doc_record(self):
        rec = IngestorAgent.make_doc_record("http://x", "web", "hello")
        assert rec["uri"] == "http://x"
        assert rec["content_hash"]


# --- Normalizer ---

class TestNormalizer:
    def setup_method(self):
        self.agent = NormalizerAgent()

    def test_parse_valid(self):
        resp = json.dumps({"normalized_segments": [{"segment_id": "s1", "text": "clean"}]})
        result = self.agent.parse(resp)
        assert len(result["normalized_segments"]) == 1

    def test_validate_valid(self):
        self.agent.validate({"normalized_segments": [{"segment_id": "s1", "text": "ok"}]})

    def test_validate_missing_text(self):
        with pytest.raises(ValueError, match="segment_id and text"):
            self.agent.validate({"normalized_segments": [{"segment_id": "s1"}]})

    def test_normalize_text_strips_html(self):
        raw = "<p>Hello <b>world</b></p>"
        assert NormalizerAgent.normalize_text(raw) == "Hello world"

    def test_normalize_text_collapses_whitespace(self):
        raw = "Hello   \t  world\n\n\n\nParagraph"
        result = NormalizerAgent.normalize_text(raw)
        assert "   " not in result
        assert "\n\n\n" not in result


# --- Entity Resolver ---

class TestEntityResolver:
    def setup_method(self):
        self.agent = EntityResolverAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "entities": [{"entity_id": "e1", "type": "vendor", "names": ["Acme"]}],
            "relationships": [{"rel_id": "r1", "type": "produces", "from_id": "e1", "to_id": "e2"}],
        })
        result = self.agent.parse(resp)
        assert len(result["entities"]) == 1
        assert len(result["relationships"]) == 1

    def test_validate_valid(self):
        self.agent.validate({
            "entities": [{"entity_id": "e1", "type": "vendor", "names": ["A"]}],
            "relationships": [{"rel_id": "r1", "type": "x", "from_id": "e1", "to_id": "e2"}],
        })

    def test_validate_missing_entity_type(self):
        with pytest.raises(ValueError, match="entity_id and type"):
            self.agent.validate({
                "entities": [{"entity_id": "e1"}],
                "relationships": [],
            })

    def test_validate_bad_relationship(self):
        with pytest.raises(ValueError, match="rel_id, type, from_id, to_id"):
            self.agent.validate({
                "entities": [],
                "relationships": [{"rel_id": "r1", "type": "x"}],
            })


# --- Claim Extractor ---

class TestClaimExtractor:
    def setup_method(self):
        self.agent = ClaimExtractorAgent()

    def _make_claim(self, **overrides):
        base = {
            "claim_id": "c1", "statement": "test", "claim_type": "factual",
            "entities": [], "citations": [{"doc_id": "d1", "segment_id": "s1"}],
            "evidence_strength": 0.9, "confidence": 0.9, "status": "active",
        }
        base.update(overrides)
        return base

    def test_parse_valid(self):
        resp = json.dumps({"claims": [self._make_claim()]})
        result = self.agent.parse(resp)
        assert len(result["claims"]) == 1

    def test_validate_valid(self):
        self.agent.validate({"claims": [self._make_claim()]})

    def test_validate_no_citations_raises(self):
        with pytest.raises(ValueError, match="no citations"):
            self.agent.validate({"claims": [self._make_claim(citations=[])]})

    def test_validate_citation_missing_doc_id(self):
        with pytest.raises(ValueError, match="doc_id or segment_id"):
            self.agent.validate({"claims": [self._make_claim(citations=[{"doc_id": "", "segment_id": "s1"}])]})

    def test_validate_missing_statement(self):
        with pytest.raises(ValueError, match="statement"):
            self.agent.validate({"claims": [self._make_claim(statement="")]})


# --- Metric Extractor ---

class TestMetricExtractor:
    def setup_method(self):
        self.agent = MetricExtractorAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "metrics": [{"metric_id": "m1", "name": "latency", "unit": "ms"}],
            "metric_points": [{"point_id": "p1", "metric_id": "m1", "t": "2026-01", "value": 42}],
        })
        result = self.agent.parse(resp)
        assert len(result["metrics"]) == 1

    def test_validate_valid(self):
        self.agent.validate({
            "metrics": [{"metric_id": "m1", "name": "x", "unit": "ms"}],
            "metric_points": [{"point_id": "p1", "metric_id": "m1", "value": 1.0}],
        })

    def test_validate_missing_unit(self):
        with pytest.raises(ValueError, match="missing unit"):
            self.agent.validate({
                "metrics": [{"metric_id": "m1", "name": "x", "unit": ""}],
                "metric_points": [],
            })

    def test_validate_point_missing_value(self):
        with pytest.raises(ValueError, match="missing value"):
            self.agent.validate({
                "metrics": [],
                "metric_points": [{"point_id": "p1", "metric_id": "m1"}],
            })


# --- Contradiction ---

class TestContradiction:
    def setup_method(self):
        self.agent = ContradictionAgent()

    def test_parse_valid(self):
        resp = json.dumps({
            "contradictions": [{"claim_a_id": "c1", "claim_b_id": "c2", "reason": "conflicting", "severity": "high"}],
            "updated_claim_ids": ["c1", "c2"],
        })
        result = self.agent.parse(resp)
        assert len(result["contradictions"]) == 1

    def test_validate_valid(self):
        self.agent.validate({
            "contradictions": [{"claim_a_id": "c1", "claim_b_id": "c2", "reason": "x"}],
            "updated_claim_ids": ["c1"],
        })

    def test_validate_no_empty_contradictions(self):
        # Empty list is fine (no contradictions found)
        self.agent.validate({"contradictions": [], "updated_claim_ids": []})

    def test_validate_missing_reason(self):
        with pytest.raises(ValueError, match="reason"):
            self.agent.validate({
                "contradictions": [{"claim_a_id": "c1", "claim_b_id": "c2"}],
                "updated_claim_ids": [],
            })
